import json
from datetime import timedelta
from pathlib import Path
from threading import Event, Lock
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from hunter.api.app import create_app
from hunter.api.auth import hash_password
from hunter.api.dependencies import Services
from hunter.api.server import create_server_app
from hunter.config import AuthSettings, RuntimeSettings, Settings
from hunter.ingest import ClusterService
from hunter.models import BriefStatus, ContentBrief, MetricSnapshot, RawItem, SourceInput
from hunter.models.common import utcnow
from hunter.runtime.service import Runtime
from hunter.runtime.telegram import TelegramRuntime
from hunter.telegram import TelegramError

from .support import FixtureClock, approve, fixture_draft, pending_brief
from .test_runtime_server import _eventually

_FAKE_ENV = {"TELEGRAM_BOT_TOKEN": "123456:fake-runtime-test-token", "TELEGRAM_CHAT_ID": "-876543210"}
_FAKE_CHAT = int(_FAKE_ENV["TELEGRAM_CHAT_ID"])


class FakeTelegram:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], float]] = []
        self.updates: list[dict[str, object]] = []
        self.blocked = Event()
        self.release = Event()
        self._poll_lock = Lock()
        self.block_updates = False
        self.rate_limit = False
        self.fail_poll = False
        self.uncertain_send = False
        self._message_id = 0

    def __call__(self, request: Request, *, timeout: float) -> tuple[int, bytes]:
        method = request.full_url.rsplit("/", 1)[-1]
        data = json.loads(request.data or b"{}")
        self.calls.append((method, data, timeout))
        if method == "sendMessage":
            if self.uncertain_send:
                return 500, b'{"ok":false}'
            self._message_id += 1
            return 200, json.dumps({
                "ok": True, "result": {"message_id": self._message_id, "chat": {"id": _FAKE_CHAT}},
            }).encode()
        if method == "getUpdates":
            assert self._poll_lock.acquire(blocking=False), "Only the runtime may poll"
            try:
                if self.block_updates:
                    self.blocked.set()
                    assert self.release.wait(3)
                if self.rate_limit:
                    return 429, b'{"ok":false,"parameters":{"retry_after":120}}'
                if self.fail_poll:
                    raise OSError("Fake connection failed: " + request.full_url + " " + str(_FAKE_CHAT))
                updates = [update for update in self.updates if update["update_id"] >= data["offset"]]
                return 200, json.dumps({"ok": True, "result": updates}).encode()
            finally:
                self._poll_lock.release()
        if method == "answerCallbackQuery":
            return 400, b'{"ok":false,"description":"Fake stale callback"}'
        if method in {"editMessageText", "editMessageReplyMarkup"}:
            return 200, b'{"ok":true}'
        raise AssertionError("Unexpected fake Bot API method")


def test_single_poller_records_ack_even_when_telegram_rejects_the_callback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    bot = FakeTelegram()
    password = "Fake dashboard password"
    settings = Settings(
        database_path=tmp_path / "hunter.sqlite3", auth=AuthSettings(admin_password_hash=hash_password(password)),
        runtime=RuntimeSettings(
            enabled=True, telegram_poll_seconds=0.01, dashboard_url="http://127.0.0.1:8000/dashboard-test",
        ),
    )
    runtimes: list[Runtime] = []

    def factory(services: Services) -> Runtime:
        runtime = Runtime(services, telegram_transport=bot, environ=_FAKE_ENV)
        runtimes.append(runtime)
        return runtime

    with TestClient(create_server_app(settings, runtime_factory=factory)) as client:
        backend = runtimes[0].services
        clock = FixtureClock()
        clock.now = utcnow()
        brief = pending_brief(backend.briefs, clock)
        approve(backend.review, brief)
        handoff = backend.handoffs.select_by_admin(brief.id)
        send = f"/api/handoffs/{handoff.id}/send"
        check = f"/api/handoffs/{handoff.id}/check-ack"
        token = client.post("/api/auth/login", json={"password": password}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post(send, headers=headers).status_code == 501
        assert not bot.calls
        client.put("/api/settings/telegram_enabled", headers=headers, json={"value": True, "reason": "Test fixture"})
        assert client.post(send, headers=headers, json={"message": "Untrusted caller text"}).json()["status"] == "SENT"
        _, message, _ = next(call for call in bot.calls if call[0] == "sendMessage")
        assert "Untrusted caller text" not in message["text"]
        assert "BÀN GIAO SẢN XUẤT" in message["text"]
        assert f"{settings.runtime.dashboard_url}/briefs/{brief.id}" in message["text"]
        callback = message["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        bot.block_updates = True
        assert bot.blocked.wait(3)
        try:
            for _ in range(3):
                assert client.post(check, headers=headers).json()["status"] == "SENT"
            bot.updates = [
                {"update_id": index, "callback_query": {
                    "id": query_id, "data": callback,
                    "message": {"chat": {"id": chat}, "message_id": 1, "text": message["text"]},
                }}
                for index, query_id, chat in ((1, "foreign-fixture", 99001), (2, "local-fixture", _FAKE_CHAT))
            ]
        finally:
            bot.release.set()
        _eventually(lambda: client.post(check, headers=headers).json()["status"] == "ACKNOWLEDGED")
        callback_calls = [call for call in bot.calls if call[0] in {"answerCallbackQuery", "editMessageText"}]
        assert [method for method, _, _ in callback_calls] == ["answerCallbackQuery", "editMessageText"]
        _, answer, timeout = callback_calls[0]
        assert answer == {"callback_query_id": "local-fixture"}
        assert timeout <= 1
        _, edit, _ = callback_calls[1]
        assert edit["chat_id"] == _FAKE_CHAT and edit["message_id"] == 1
        assert edit["reply_markup"] == {"inline_keyboard": []}
        assert edit["text"].startswith("✅ Đã nhận\n\nBÀN GIAO SẢN XUẤT")
        bot.fail_poll = True
        _eventually(lambda: "Telegram polling failed" in caplog.text)
    assert not any(secret in caplog.text for secret in _FAKE_ENV.values())
    for path in tmp_path.glob("*.sqlite3"):
        assert not any(secret.encode() in path.read_bytes() for secret in _FAKE_ENV.values())


def _draft(
    backend: Services, clock: FixtureClock, title: str, *, raw_item_id: str | None = None,
    approved: bool = True, age: timedelta = timedelta(0), publish_age: timedelta = timedelta(0),
    fresh_metrics: bool = False,
) -> ContentBrief:
    store = backend.briefs
    brief = store.create(raw_item_id=raw_item_id)
    store.advance(brief.id, BriefStatus.PREPROCESSED)
    store.advance(brief.id, BriefStatus.PROCESSING)
    draft = fixture_draft(clock).model_copy(update={
        "title_vi": title, "verification_level": "verified", "discovered_at": clock() - age,
        "published_at": clock() - publish_age if publish_age else None,
        "engagement_metrics": MetricSnapshot(views=9000) if fresh_metrics else None,
        "metrics_snapshot_at": clock() if fresh_metrics else None,
    })
    result = store.submit_draft(brief.id, draft, expected_revision=0)
    if approved:
        approve(backend.review, result)
    return result


def test_watcher_requires_approval_freshness_and_cluster_dedup_across_restart(tmp_path: Path) -> None:
    clock = FixtureClock()
    clock.now = utcnow()
    bot = FakeTelegram()
    with TestClient(create_app(Settings(database_path=tmp_path / "hunter.sqlite3"))) as client:
        backend = client.app.state.services
        backend.operations.set_preference("telegram_enabled", True, reason="Test fixture")
        _draft(backend, clock, "Unapproved P1 fixture", approved=False)
        _draft(backend, clock, "Stale P1 fixture", publish_age=timedelta(hours=13))
        _draft(backend, clock, "Backlogged P1 fixture", age=timedelta(hours=1))
        _draft(backend, clock, "Rechecked P1 fixture", age=timedelta(hours=1), fresh_metrics=True)
        source = backend.operations.save_source(SourceInput(
            connector_id="fake-alert-source", name="Fixture source", platform="fixture",
            url="https://example.invalid/fake-alert-feed",
        ), reason="Test fixture")
        members = [backend.operations.store_raw_item(RawItem(
            source_id=source.id, source_url=f"https://example.invalid/fake-article-{index}", fetched_at=clock(),
            title="Chủ đề xu hướng thử nghiệm",
        )) for index in range(2)]
        cluster = ClusterService(backend.database)
        assert cluster.assign(members[0]) == cluster.assign(members[1]) is not None
        for index, item in enumerate(members):
            _draft(backend, clock, f"Current clustered P1 fixture {index}", raw_item_id=item)
        for _ in range(2):
            TelegramRuntime(backend, transport=bot, environ=_FAKE_ENV).alert()
        messages = [data["text"] for method, data, _ in bot.calls if method == "sendMessage"]
        assert len(messages) == 2
        for title in ("Current clustered P1 fixture", "Rechecked P1 fixture"):
            assert any(title in text for text in messages)


def test_cluster_formation_preserves_an_uncertain_standalone_alert(tmp_path: Path) -> None:
    clock = FixtureClock()
    clock.now = utcnow()
    bot = FakeTelegram()
    bot.uncertain_send = True
    with TestClient(create_app(Settings(database_path=tmp_path / "hunter.sqlite3"))) as client:
        backend = client.app.state.services
        backend.operations.set_preference("telegram_enabled", True, reason="Test fixture")
        source = backend.operations.save_source(SourceInput(
            connector_id="fake-alert-source", name="Fixture source", platform="fixture",
            url="https://example.invalid/fake-alert-feed",
        ), reason="Test fixture")
        first = backend.operations.store_raw_item(RawItem(
            source_id=source.id, source_url="https://example.invalid/first", fetched_at=clock(),
            title="Chủ đề xu hướng thử nghiệm",
        ))
        _draft(backend, clock, "Standalone P1 fixture", raw_item_id=first)
        TelegramRuntime(backend, transport=bot, environ=_FAKE_ENV).alert()
        second = backend.operations.store_raw_item(RawItem(
            source_id=source.id, source_url="https://example.invalid/second", fetched_at=clock(),
            title="Chủ đề xu hướng thử nghiệm",
        ))
        assert ClusterService(backend.database).assign(second) is not None
        _draft(backend, clock, "Related P1 fixture", raw_item_id=second)
        bot.uncertain_send = False
        TelegramRuntime(backend, transport=bot, environ=_FAKE_ENV).alert()
        assert [method for method, _, _ in bot.calls] == ["sendMessage"]


def test_telegram_without_credentials_and_rate_limited_polling(tmp_path: Path) -> None:
    bot = FakeTelegram()
    bot.rate_limit = True
    with TestClient(create_app(Settings(database_path=tmp_path / "hunter.sqlite3"))) as client:
        backend = client.app.state.services
        backend.operations.set_preference("telegram_enabled", True, reason="Test fixture")
        unavailable = TelegramRuntime(backend, transport=bot, environ={})
        assert unavailable.notifier() is None
        unavailable.poll()
        assert not bot.calls
        telegram = TelegramRuntime(backend, transport=bot, environ=_FAKE_ENV)
        with pytest.raises(TelegramError):
            telegram.poll()
        telegram.poll()
        assert [call[0] for call in bot.calls] == ["getUpdates"]
