"""One runtime-owned Telegram consumer and an approved-brief alert watcher."""

import json
import os
import sqlite3
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from threading import Lock
from time import monotonic
from urllib.request import Request

from hunter.api.dependencies import Services
from hunter.interfaces import SendStatus
from hunter.models import ContentBrief, HandoffStatus, Priority
from hunter.models.common import utcnow
from hunter.state import NotFound
from hunter.telegram import TelegramError, TelegramNotifier, format_alert, should_alert
from hunter.telegram.messages import limit_text
from hunter.telegram.transport import TelegramTransport, _urllib_transport

_ACK_LABEL = "✅ Đã nhận"
_SIGNAL_WINDOW = timedelta(minutes=30)
_ALERT_MAX_AGE = timedelta(hours=12)


def _object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _json_object(raw: bytes | None) -> dict[str, object]:
    if raw is not None and len(raw) <= 1024 * 1024:
        try:
            return _object(json.loads(raw))
        except (ValueError, RecursionError):
            pass
    return {}


@dataclass(frozen=True)
class _CallbackMessage:
    chat_id: int
    message_id: int
    text: str | None


class _CallbackTransport:
    """Edit only callbacks authorized by the notifier after its ledger commit."""

    def __init__(self, transport: TelegramTransport | None) -> None:
        self._send = _urllib_transport if transport is None else transport
        self._messages: dict[str, _CallbackMessage | None] = {}
        self._answers: list[tuple[Request, _CallbackMessage]] = []
        self._rate_lock = Lock()
        self._retry_at = 0.0

    def rate_limited(self) -> bool:
        with self._rate_lock:
            return monotonic() < self._retry_at

    def _request(self, request: Request, timeout: float) -> tuple[int, bytes]:
        if self.rate_limited():
            return 429, b'{"ok":false}'
        try:
            status, raw = self._send(request, timeout=timeout)
        except Exception:
            return 0, b""
        if status == 429:
            retry_after = _object(_json_object(raw).get("parameters")).get("retry_after")
            seconds = retry_after if type(retry_after) is int and 0 < retry_after < 2**63 else 60
            with self._rate_lock:
                self._retry_at = max(self._retry_at, monotonic() + seconds)
        return status, raw

    def __call__(self, request: Request, *, timeout: float) -> tuple[int, bytes]:
        method = request.full_url.rsplit("/", 1)[-1]
        if method == "answerCallbackQuery":
            query_id = _json_object(request.data).get("callback_query_id")
            message = self._messages.get(query_id) if isinstance(query_id, str) else None
            if message is not None:
                self._answers.append((request, message))
                # The notifier does not use this result. Dispatch the batch after its ledger work.
                return 0, b""
            return self._request(request, timeout=1)

        status, raw = self._request(request, timeout)
        if method == "getUpdates" and 200 <= status < 300:
            updates = _json_object(raw).get("result")
            if isinstance(updates, list):
                for update in updates:
                    self._remember(_object(_object(update).get("callback_query")))
        return status, raw

    def _remember(self, query: dict[str, object]) -> None:
        query_id = query.get("id")
        message = _object(query.get("message"))
        chat_id = _object(message.get("chat")).get("id")
        message_id = message.get("message_id")
        text = message.get("text")
        if isinstance(query_id, str) and type(chat_id) is int and type(message_id) is int:
            # A callback ID identifies one original message. Skip editing ambiguous updates.
            self._messages[query_id] = None if query_id in self._messages else _CallbackMessage(
                chat_id, message_id, text if isinstance(text, str) else None,
            )

    def _answer_and_edit(self, answer: Request, message: _CallbackMessage) -> None:
        self._request(answer, timeout=1)
        # A stale callback can fail to answer even though acknowledgement already committed.
        payload: dict[str, object] = {
            "chat_id": message.chat_id, "message_id": message.message_id,
            "reply_markup": {"inline_keyboard": []},
        }
        method = "editMessageReplyMarkup"
        if message.text:
            text = message.text if message.text.startswith(_ACK_LABEL + "\n") else f"{_ACK_LABEL}\n\n{message.text}"
            try:
                payload["text"] = limit_text(text)
            except (UnicodeError, ValueError):
                pass
            else:
                method = "editMessageText"
        edit = Request(
            f"{answer.full_url.rsplit('/', 1)[0]}/{method}",
            data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"},
            method="POST",
        )
        self._request(edit, timeout=1)

    def poll(self, notifier: TelegramNotifier) -> None:
        if self.rate_limited():
            return
        try:
            notifier.poll_updates()
            if self._answers:
                # A slow callback must not delay answers for other updates in the same batch.
                with ThreadPoolExecutor(max_workers=20) as pool:
                    answers = [pool.submit(self._answer_and_edit, *answer) for answer in self._answers]
                    for future in answers:
                        future.result()
        finally:
            self._messages.clear()
            self._answers.clear()


class TelegramRuntime:
    def __init__(
        self, services: Services, *, transport: TelegramTransport | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.services = services
        self._environ = os.environ if environ is None else environ
        self._transport = _CallbackTransport(transport)
        self._lock = Lock()
        path = services.database.path
        self._ledger_path = path.with_name(f"{path.stem}.telegram.sqlite3")
        self._notifier: TelegramNotifier | None = None
        self._invalid_credentials = False

    def notifier(self) -> TelegramNotifier | None:
        if not self.services.operations.preferences().telegram_enabled:
            return None
        with self._lock:
            if self._notifier is None and not self._invalid_credentials:
                try:
                    self._notifier = TelegramNotifier(
                        ledger_path=self._ledger_path,
                        transport=self._transport, environ=self._environ, poll_on_check=False,
                    )
                except TelegramError:
                    self._invalid_credentials = True
                except (OSError, sqlite3.Error):
                    return None
            return self._notifier

    def poll(self) -> None:
        notifier = self.notifier()
        if notifier is None:
            return
        self.services.settings.budget.require_allowed(incurs_cost=notifier.incurs_cost)
        try:
            self._transport.poll(notifier)
        finally:
            # Reconcile durable ledger entries even when the current fetch failed.
            for handoff in self.services.handoffs.list(status=HandoffStatus.SENT, limit=-1):
                try:
                    self.services.handoffs.check_ack(handoff.id, notifier)
                except NotFound:
                    continue

    def _alert_keys(self, brief: ContentBrief) -> tuple[str, list[str]]:
        with self.services.database.connection() as connection:
            cluster = connection.execute(
                """SELECT m.cluster_id FROM briefs AS b
                   JOIN trend_cluster_members AS m ON m.raw_item_id = b.raw_item_id
                   WHERE b.id = ? ORDER BY m.cluster_id LIMIT 1""", (brief.id,),
            ).fetchone()
            if cluster is None:
                return f"p1:brief:{brief.id}", []
            cluster_id = cluster["cluster_id"]
            member_keys = [f"p1:brief:{row['id']}" for row in connection.execute(
                """SELECT b.id FROM trend_cluster_members AS m JOIN briefs AS b ON m.raw_item_id = b.raw_item_id
                   WHERE m.cluster_id = ?""", (cluster_id,),
            )]
        return f"p1:cluster:{cluster_id}", member_keys

    def _member_alert_attempted(self, keys: list[str]) -> bool:
        # A brief can join a cluster after standalone delivery. The public lookup
        # uses UNKNOWN for both absent and uncertain attempts. Preserve both reservations and receipts.
        hashes = [sha256(key.encode()).hexdigest() for key in keys]
        with closing(sqlite3.connect(self._ledger_path, timeout=5)) as ledger:
            return ledger.execute(
                "SELECT 1 FROM deliveries WHERE key_hash IN (SELECT value FROM json_each(?)) LIMIT 1",
                (json.dumps(hashes),),
            ).fetchone() is not None

    def alert(self) -> None:
        notifier = self.notifier()
        if notifier is None or self._transport.rate_limited():
            return
        self.services.settings.budget.require_allowed(incurs_cost=notifier.incurs_cost)
        threshold = self.services.operations.preferences().p1_threshold
        briefs = self.services.inbox.list(priority=Priority.P1, discovered_after=utcnow() - _ALERT_MAX_AGE, limit=-1)
        for brief in briefs:
            if self._transport.rate_limited():
                return
            now = utcnow()
            key, member_keys = self._alert_keys(brief)
            previous = notifier.lookup_send(key)
            fresh_signal = brief.metrics_snapshot_at is not None and timedelta(0) <= (
                now - brief.metrics_snapshot_at
            ) <= _SIGNAL_WINDOW
            decision = should_alert(
                brief, now=now, cluster_alerted=bool(member_keys) and (
                    previous.status == SendStatus.SENT or self._member_alert_attempted(member_keys)
                ),
                duplicate_alert_key=previous.status != SendStatus.UNKNOWN,
                backlogged=now - brief.discovered_at > _SIGNAL_WINDOW, signals_current=True if fresh_signal else None,
                max_age=_ALERT_MAX_AGE, p1_threshold=threshold,
            )
            if decision.allowed:
                notifier.send(format_alert(brief, dashboard_base_url=self.services.settings.runtime.dashboard_url), key)
