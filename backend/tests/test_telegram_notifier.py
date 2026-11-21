"""Offline coverage of delivery, acknowledgement, and the HTTP boundary."""

import json
import ssl
import sys
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request

import pytest

from hunter.interfaces import SendStatus
from hunter.telegram import TelegramError, TelegramNotifier, smoke
from hunter.telegram import transport as wire

_FAKE_CHAT = -1007771234599
_FAKE_TOKEN = "555111:fake-test-token"
_FAKE_ENV = {"TELEGRAM_BOT_TOKEN": _FAKE_TOKEN, "TELEGRAM_CHAT_ID": str(_FAKE_CHAT)}
_HANDOFF_KEY = "handoff:fixture-key"


def fake_ok(result: object) -> tuple[int, bytes]:
    return 200, json.dumps({"ok": True, "result": result}).encode()


def fake_sent(message_id: int = 1234, *, chat_id: int = _FAKE_CHAT) -> tuple[int, bytes]:
    return fake_ok({"message_id": message_id, "chat": {"id": chat_id}})


class FakeTransport:
    def __init__(self, *responses: tuple[int, bytes] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __call__(self, request: Request, *, timeout: float) -> tuple[int, bytes]:
        assert request.data is not None
        assert request.get_method() == "POST"
        assert request.full_url.startswith(f"https://api.telegram.org/bot{_FAKE_TOKEN}/")
        assert 0 < timeout <= 10
        self.calls.append((request.full_url.rsplit("/", 1)[1], json.loads(request.data)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_notifier(path: Path, transport: wire.TelegramTransport, *, poll_on_check: bool = False) -> TelegramNotifier:
    return TelegramNotifier(ledger_path=path, transport=transport, environ=_FAKE_ENV, poll_on_check=poll_on_check)


def button_data(transport: FakeTransport) -> str:
    markup = transport.calls[0][1]["reply_markup"]
    assert isinstance(markup, dict)
    [[button]] = markup["inline_keyboard"]
    assert button["text"] == "✅ Đã nhận"
    data = button["callback_data"]
    assert isinstance(data, str)
    return data


def fake_callback(update_id: int, data: str, *, chat_id: int = _FAKE_CHAT, receipt: int = 1234) -> dict[str, object]:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"fake-callback-{update_id}",
            "data": data,
            "message": {"chat": {"id": chat_id}, "message_id": receipt},
        },
    }


def test_send_is_idempotent_across_instances_and_keeps_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "telegram.sqlite3"
    fake = FakeTransport(fake_sent())
    notifier = make_notifier(path, fake)
    key = "handoff:" + "dữ liệu giả" * 100
    # All MarkdownV2 special characters, including a literal backslash.
    plain_text = "Tiêu đề _ * [ ] ( ) ~ ` > # + - = | { } . ! \\"
    assert notifier.incurs_cost is False
    assert notifier.lookup_send(key).status == SendStatus.UNKNOWN
    result = notifier.send(plain_text, key)
    assert result.status == SendStatus.SENT and result.external_id == "1234"
    assert notifier.send(plain_text, key) == result
    reopened = make_notifier(path, fake)
    assert reopened.lookup_send(key) == result
    assert reopened.send("Changed content", key) == result
    assert not reopened.check_ack("1234", key)
    assert len(fake.calls) == 1
    method, data = fake.calls[0]
    assert method == "sendMessage"
    assert data["chat_id"] == _FAKE_CHAT
    assert data["text"] == plain_text
    assert "parse_mode" not in data
    assert len(button_data(fake).encode()) <= 64
    assert key not in button_data(fake)
    assert key.encode() not in path.read_bytes()


def test_reservation_survives_crash_after_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeCrash(BaseException):
        pass

    path = tmp_path / "telegram.sqlite3"
    fake = FakeTransport(fake_sent())
    notifier = make_notifier(path, fake)

    def crash_before_confirmation(*args: object) -> None:
        raise FakeCrash

    monkeypatch.setattr(notifier._ledger, "finish", crash_before_confirmation)
    with pytest.raises(FakeCrash):
        notifier.send("Tin nhắn thử", _HANDOFF_KEY)
    restarted = make_notifier(path, fake)
    assert restarted.lookup_send(_HANDOFF_KEY).status == SendStatus.UNKNOWN
    assert restarted.send("Tin nhắn thử", _HANDOFF_KEY).status == SendStatus.UNKNOWN
    assert len(fake.calls) == 1


def test_definitive_failure_permits_retry_with_same_callback(tmp_path: Path) -> None:
    fake = FakeTransport((403, b'{"ok":false,"description":"fake rejection"}'), fake_sent())
    notifier = make_notifier(tmp_path / "telegram.sqlite3", fake)
    assert notifier.send("Thử", _HANDOFF_KEY).status == SendStatus.FAILED
    assert notifier.lookup_send(_HANDOFF_KEY).status == SendStatus.FAILED
    assert notifier.send("Thử lại", _HANDOFF_KEY).status == SendStatus.SENT
    assert notifier.lookup_send(_HANDOFF_KEY).external_id == "1234"
    assert fake.calls[0][1]["reply_markup"] == fake.calls[1][1]["reply_markup"]


@pytest.mark.parametrize("response", [
    TimeoutError("fake timeout"),
    ConnectionResetError("fake disconnect"),
    (502, b'{"ok":false}'),
    (403, b"invalid JSON"),
    (200, b'{"ok":false}'),
    (307, b'{"ok":false}'),
    fake_sent(chat_id=157),
    fake_sent(message_id=0),
    (200, b" " * (wire._MAX_RESPONSE_BYTES + 1)),
])
def test_ambiguous_response_never_resends(tmp_path: Path, response: tuple[int, bytes] | Exception) -> None:
    fake = FakeTransport(response)
    notifier = make_notifier(tmp_path / "telegram.sqlite3", fake)
    assert notifier.send("Thử", _HANDOFF_KEY).status == SendStatus.UNKNOWN
    assert notifier.lookup_send(_HANDOFF_KEY).status == SendStatus.UNKNOWN
    assert notifier.send("Thử lại", _HANDOFF_KEY).status == SendStatus.UNKNOWN
    assert len(fake.calls) == 1


def test_transport_diagnostics_and_ledger_omit_credentials(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "telegram.sqlite3"
    diagnostic = f"https://api.telegram.org/bot{_FAKE_TOKEN}/getUpdates for {_FAKE_CHAT}"
    fake = FakeTransport(TimeoutError(diagnostic), RuntimeError(diagnostic))
    notifier = make_notifier(path, fake)
    assert notifier.send("Thử", f"handoff:{_FAKE_TOKEN}|{_FAKE_CHAT}").status == SendStatus.UNKNOWN
    with pytest.raises(TelegramError) as poll_error:
        notifier.poll_updates()
    with pytest.raises(TelegramError) as config_error:
        TelegramNotifier(ledger_path=path, transport=fake, environ={"TELEGRAM_BOT_TOKEN": diagnostic})

    for secret in (_FAKE_TOKEN, str(_FAKE_CHAT)):
        assert secret not in str(poll_error.value)
        assert secret not in str(config_error.value)
        assert secret not in caplog.text
        assert secret.encode() not in path.read_bytes()
    assert poll_error.value.__context__ is None


def test_send_truncates_and_preserves_dashboard_link(tmp_path: Path) -> None:
    fake = FakeTransport(fake_sent())
    notifier = make_notifier(tmp_path / "telegram.sqlite3", fake)
    link = "https://dashboard.example/briefs/brief-fixture"
    message = f"{'à' * 3900}{'😀' * 200}\nDashboard: {link}"
    assert notifier.send(message, "alert:fixture").status == SendStatus.SENT
    data = fake.calls[0][1]
    text = data["text"]
    assert isinstance(text, str)
    assert len(text.encode("utf-16-le")) <= 4096 * 2
    assert text.endswith(f"…\n\nDashboard: {link}")
    assert "reply_markup" not in data


def test_callback_requires_configured_chat_matching_receipt_and_key(tmp_path: Path) -> None:
    path = tmp_path / "telegram.sqlite3"
    fake = FakeTransport(fake_sent())
    notifier = make_notifier(path, fake)
    notifier.send("Thử", _HANDOFF_KEY)
    data = button_data(fake)
    fake.responses.append(fake_ok([
        fake_callback(101, data, chat_id=-7),
        fake_callback(102, data, receipt=4321),
        fake_callback(103, "h:" + "0" * 48),
    ]))
    notifier.poll_updates()
    assert not notifier.check_ack("1234", _HANDOFF_KEY)
    assert len(fake.calls) == 2
    assert fake.calls[1][0] == "getUpdates"
    assert fake.calls[1][1]["offset"] == 0
    assert fake.calls[1][1]["allowed_updates"] == ["callback_query", "message"]

    fake.responses.extend((fake_ok([fake_callback(104, data)]), fake_ok(True)))
    restarted = make_notifier(path, fake)
    restarted.poll_updates()
    assert fake.calls[2][1]["offset"] == 104
    assert fake.calls[3] == ("answerCallbackQuery", {"callback_query_id": "fake-callback-104"})
    reopened = make_notifier(path, fake)
    assert reopened.check_ack("1234", _HANDOFF_KEY)
    assert not reopened.check_ack("1234", "handoff:other-fixture")
    assert not reopened.check_ack("5555", _HANDOFF_KEY)

    fake.responses.append(fake_ok([fake_callback(104, data)]))
    reopened.poll_updates()
    assert fake.calls[4][1]["offset"] == 105
    assert len(fake.calls) == 5


def test_reply_polling_requires_explicit_action_in_configured_chat(tmp_path: Path) -> None:
    def fake_reply(update_id: int, chat_id: int, receipt: int) -> dict[str, object]:
        return {
            "update_id": update_id,
            "message": {"chat": {"id": chat_id}, "reply_to_message": {"message_id": receipt}},
        }

    fake = FakeTransport(
        fake_sent(),
        fake_ok([
            fake_reply(1, -4, 1234), fake_reply(2, _FAKE_CHAT, 5678),
            {"update_id": 3, "message": {"chat": {"id": _FAKE_CHAT}, "text": "Fake unrelated message"}},
        ]),
        fake_ok([fake_reply(4, _FAKE_CHAT, 1234)]),
    )
    notifier = make_notifier(tmp_path / "telegram.sqlite3", fake, poll_on_check=True)
    notifier.send("Thử", _HANDOFF_KEY)
    assert not notifier.check_ack("1234", _HANDOFF_KEY)
    assert notifier.check_ack("1234", _HANDOFF_KEY)
    assert [method for method, _ in fake.calls] == ["sendMessage", "getUpdates", "getUpdates"]


def test_ack_during_send_waits_for_matching_committed_receipt(tmp_path: Path) -> None:
    path = tmp_path / "telegram.sqlite3"
    polled = FakeTransport()
    poller = make_notifier(path, polled)
    observed: list[bool] = []

    def fake_send_with_poll(request: Request, *, timeout: float) -> tuple[int, bytes]:
        sent = FakeTransport(fake_sent())
        result = sent(request, timeout=timeout)
        polled.responses.extend((fake_ok([fake_callback(1, button_data(sent))]), TimeoutError()))
        observed.append(poller.send("Repeated handoff", _HANDOFF_KEY).status == SendStatus.UNKNOWN)
        poller.poll_updates()
        observed.append(poller.check_ack("1234", _HANDOFF_KEY))
        return result

    notifier = make_notifier(path, fake_send_with_poll)
    assert notifier.send("Thử", _HANDOFF_KEY).status == SendStatus.SENT
    assert observed == [True, False]
    assert notifier.check_ack("1234", _HANDOFF_KEY)
    assert [method for method, _ in polled.calls] == ["getUpdates", "answerCallbackQuery"]


def test_urllib_transport_uses_verified_tls_no_proxies_and_bounded_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    built_handlers: list[object] = []
    reads: list[int] = []

    class FakeStream(BytesIO):
        def read(self, size: int = -1) -> bytes:
            reads.append(size)
            return super().read(size)

    class FakeOpener:
        def open(self, request: Request, *, timeout: float) -> None:
            assert timeout == 8.0
            raise HTTPError(request.full_url, 403, "fake HTTP error", None, FakeStream(b'{"ok":false}'))

    def fake_build_opener(*handlers: object) -> FakeOpener:
        built_handlers.extend(handlers)
        return FakeOpener()

    monkeypatch.setattr(wire, "build_opener", fake_build_opener)
    request = Request("https://api.telegram.org/fake-offline-test")
    assert wire._urllib_transport(request, timeout=8.0) == (403, b'{"ok":false}')
    proxies, redirects, https = built_handlers
    assert isinstance(proxies, ProxyHandler) and proxies.proxies == {}
    assert isinstance(redirects, wire._NoRedirect)
    assert redirects.redirect_request(request, None, 302, "", {}, "https://example.com") is None
    assert isinstance(https, wire.HTTPSHandler)
    assert https._context.verify_mode == ssl.CERT_REQUIRED
    assert https._context.check_hostname
    assert reads == [wire._MAX_RESPONSE_BYTES + 1]


def test_smoke_only_prints_status_and_masked_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTransport(fake_sent())
    factory: Callable[..., TelegramNotifier] = lambda **_: make_notifier(tmp_path / "smoke.sqlite3", fake)
    monkeypatch.setattr(smoke, "TelegramNotifier", factory)
    monkeypatch.setattr(sys, "argv", ["smoke", "send-test"])
    assert smoke.main() == 0
    assert smoke.main() == 0
    assert capsys.readouterr().out == "SENT receipt=****34\nSENT receipt=****34\n"
    fake.responses.extend((fake_ok([fake_callback(1, button_data(fake))]), fake_ok(True)))
    monkeypatch.setattr(sys, "argv", ["smoke", "poll"])
    assert smoke.main() == 0
    assert capsys.readouterr().out == "ACKNOWLEDGED\n"
    assert [method for method, _ in fake.calls] == ["sendMessage", "getUpdates", "answerCallbackQuery"]
