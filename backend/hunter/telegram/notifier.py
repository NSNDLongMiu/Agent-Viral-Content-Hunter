"""Telegram delivery and acknowledgement for one bot and chat per ledger.

Telegram has no client idempotency key. A crash or ambiguous response after a
durable reservation can leave delivery unknown until a recipient confirms a
handoff. Such keys are never resent. Only one consumer per bot may call
getUpdates, whether directly, through check_ack, or from the smoke CLI.
"""

import os
import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from threading import Lock

from hunter.interfaces import Notifier, SendResult, SendStatus

from .ledger import Ledger
from .messages import limit_text
from .transport import BotAPI, TelegramTransport

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parents[2] / "data" / "telegram.sqlite3"


class TelegramError(RuntimeError):
    """Credential-free configuration or polling error."""


def _object(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _receipt(message: dict[str, object]) -> str | None:
    message_id = message.get("message_id")
    if type(message_id) is int and 0 < message_id < 2**63:
        return str(message_id)
    return None


def _key_hash(dedup_key: str) -> str:
    return sha256(dedup_key.encode("utf-8")).hexdigest()


class TelegramNotifier(Notifier):
    incurs_cost = False

    def __init__(
        self, *, ledger_path: Path = DEFAULT_LEDGER_PATH,
        transport: TelegramTransport | None = None,
        environ: Mapping[str, str] | None = None, poll_on_check: bool = False,
    ) -> None:
        env = os.environ if environ is None else environ
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat = env.get("TELEGRAM_CHAT_ID", "").strip()
        if not re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{1,128}", token) or not re.fullmatch(
            r"-?[0-9]{1,20}", chat,
        ):
            raise TelegramError("Set the Telegram bot token and numeric chat ID in the environment")
        self._chat_id = int(chat)
        self._bot_id = int(token.split(":", 1)[0])
        self._api = BotAPI(token, transport)
        self._ledger = Ledger(ledger_path)
        self._poll_on_check = poll_on_check
        self._poll_lock = Lock()

    def _in_configured_chat(self, message: dict[str, object]) -> bool:
        chat_id = _object(message.get("chat")).get("id")
        return type(chat_id) is int and chat_id == self._chat_id

    def send(self, message: str, dedup_key: str) -> SendResult:
        key_hash = _key_hash(dedup_key)
        # HandoffService uses this prefix. Ordinary P1 alerts have no keyboard.
        callback_data = f"h:{key_hash[:48]}" if dedup_key.startswith("handoff:") else None
        if not self._ledger.reserve(key_hash, callback_data):
            return self._ledger.lookup(key_hash)

        result = self._send_reserved(message, callback_data)
        self._ledger.finish(key_hash, result)
        return self._ledger.lookup(key_hash) if result.status == SendStatus.UNKNOWN else result

    def _send_reserved(self, message: str, callback_data: str | None) -> SendResult:
        try:
            text = limit_text(message)
        except ValueError:
            return SendResult(status=SendStatus.FAILED)
        if not text.strip():
            return SendResult(status=SendStatus.FAILED)

        payload: dict[str, object] = {"chat_id": self._chat_id, "text": text}
        if callback_data is not None:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": "✅ Đã nhận", "callback_data": callback_data}]],
            }
        status, body = self._api.post("sendMessage", payload)
        if 200 <= status < 300 and body.get("ok") is True:
            message_data = _object(body.get("result"))
            receipt = _receipt(message_data)
            if receipt is not None and self._in_configured_chat(message_data):
                return SendResult(status=SendStatus.SENT, external_id=receipt)
        if 400 <= status < 500 and body.get("ok") is False:
            return SendResult(status=SendStatus.FAILED)
        return SendResult(status=SendStatus.UNKNOWN)

    def lookup_send(self, dedup_key: str) -> SendResult:
        return self._ledger.lookup(_key_hash(dedup_key))

    def check_ack(self, external_id: str, dedup_key: str) -> bool:
        key_hash = _key_hash(dedup_key)
        if self._ledger.acknowledged(key_hash, external_id):
            return True
        if self._poll_on_check:
            self.poll_updates()
            return self._ledger.acknowledged(key_hash, external_id)
        return False

    def poll_updates(self) -> None:
        """Fetch one batch. Run a single getUpdates consumer for the bot."""
        with self._poll_lock:
            offset = self._ledger.offset()
            status, body = self._api.post("getUpdates", {
                "offset": offset, "limit": 20, "timeout": 0,
                "allowed_updates": ["callback_query", "message"],
            })
            updates = body.get("result")
            if not (200 <= status < 300 and body.get("ok") is True and isinstance(updates, list)):
                raise TelegramError("Telegram updates are temporarily unavailable")
            self._apply_updates(updates, offset)

    def _apply_updates(self, updates: list[object], offset: int) -> None:
        next_offset = offset
        callbacks: list[tuple[str, str, str]] = []
        replies: list[tuple[str, bool]] = []
        for item in updates:
            update = _object(item)
            update_id = update.get("update_id")
            if type(update_id) is not int or not offset <= update_id < 2**63 - 1:
                continue
            next_offset = max(next_offset, update_id + 1)
            callback = self._read_callback(_object(update.get("callback_query")))
            if callback is not None:
                callbacks.append(callback)
            reply = self._read_reply(_object(update.get("message")))
            if reply is not None:
                replies.append(reply)

        if next_offset == offset:
            return
        for query_id in self._ledger.apply_updates(next_offset, replies, callbacks):
            # The recipient action is durable even if Telegram cannot dismiss the spinner.
            self._api.post("answerCallbackQuery", {"callback_query_id": query_id})

    def _read_callback(self, query: dict[str, object]) -> tuple[str, str, str] | None:
        message = _object(query.get("message"))
        receipt = _receipt(message)
        data = query.get("data")
        query_id = query.get("id")
        if (
            receipt is not None and self._in_configured_chat(message)
            and isinstance(data, str) and re.fullmatch(r"h:[0-9a-f]{48}", data)
            and isinstance(query_id, str) and query_id
        ):
            return receipt, data, query_id
        return None

    def _read_reply(self, message: dict[str, object]) -> tuple[str, bool] | None:
        reply_to = _object(message.get("reply_to_message"))
        receipt = _receipt(reply_to)
        if receipt is None or not self._in_configured_chat(message):
            return None
        if "chat" in reply_to and not self._in_configured_chat(reply_to):
            return None
        sender = _object(reply_to.get("from"))
        from_bot = sender.get("is_bot") is True and sender.get("id") == self._bot_id
        return receipt, from_bot
