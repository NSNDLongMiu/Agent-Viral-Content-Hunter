import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request

import pytest
from fastapi.testclient import TestClient

from hunter.api.server import create_server_app
from hunter.config import AuthSettings, Settings
from hunter.db import Database
from hunter.leader.__main__ import main
from hunter.services.brief_store import BriefStore

from .support import FixtureClock, pending_brief

_FAKE_TOKEN = "fake-claude-review-test-token-not-a-secret"
_FAKE_ENV = {"HUNTER_AUTH__CLAUDE_SERVICE_TOKEN": _FAKE_TOKEN}


class FakeReviewServer:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def __call__(self, request: Request) -> bytes:
        url = urlsplit(request.full_url)
        assert url.scheme == "http" and url.hostname == "127.0.0.1" and url.port == 8000
        assert url.path.startswith("/api/review/")
        assert request.get_header("Authorization") == f"Bearer {_FAKE_TOKEN}"
        method = request.get_method()
        data = json.loads(request.data) if request.data is not None else None
        self.calls.append((method, url.path, data))
        response = self.client.request(
            method, url.path + (f"?{url.query}" if url.query else ""),
            headers=dict(request.headers), content=request.data,
        )
        if response.is_error:
            raise HTTPError(request.full_url, response.status_code, "Fake HTTP error", {}, BytesIO(response.content))
        return response.content


def test_pending_show_and_decide_against_mounted_api(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    database = Database(tmp_path / "hunter.sqlite3")
    settings = Settings(database_path=database.path, auth=AuthSettings(claude_service_token=_FAKE_TOKEN))
    with TestClient(create_server_app(settings)) as client:
        brief = pending_brief(BriefStore(database), FixtureClock())
        fake = FakeReviewServer(client)
        assert client.get(f"/api/review/{brief.id}").status_code == 401
        assert main(["pending"], environ=_FAKE_ENV, transport=fake) == 0
        pending, = json.loads(capsys.readouterr().out)
        assert pending["revision_count"] == 0
        assert pending["summary_vi"] == brief.summary_vi
        assert pending["why_notable"] == brief.why_notable
        assert pending["original_url"] == str(brief.original_url) and pending["related_urls"] == []
        assert pending["virality_score"] == brief.virality_score
        assert main(["show", brief.id], environ=_FAKE_ENV, transport=fake) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "PENDING_CLAUDE_REVIEW"

        argv = ["decide", brief.id, "--action", "APPROVE", "--reason", "  Test fixture review  ", "--revision"]
        assert main([*argv, "1"], environ=_FAKE_ENV, transport=fake) == 1
        assert "HTTP 409" in capsys.readouterr().err
        assert main([*argv, "0"], environ=_FAKE_ENV, transport=fake) == 0
        assert json.loads(capsys.readouterr().out)["resulting_status"] == "APPROVED_BY_CLAUDE"
        assert fake.calls[-1] == ("POST", f"/api/review/{brief.id}/decision", {
            "action": "APPROVE", "reason": "Test fixture review", "expected_revision": 0,
        })
        assert main(["show", brief.id], environ=_FAKE_ENV, transport=fake) == 1
        assert "HTTP 404" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [
    ["decide", "fixture-id", "--action", "APPROVE", "--reason", "", "--revision", "0"],
    ["decide", "fixture-id", "--action", "APPROVE", "--reason", "Test fixture reason"],
    ["decide", "fixture-id", "--action", "APPROVE", "--reason", _FAKE_TOKEN, "--revision", "0"],
    ["show", "../settings"],
    [_FAKE_TOKEN],
])
def test_invalid_arguments_do_not_dispatch_or_echo_secrets(
    argv: list[str], capsys: pytest.CaptureFixture[str],
) -> None:
    def no_transport(request: Request) -> bytes:
        pytest.fail("Invalid commands must not dispatch any HTTP request")

    with pytest.raises(SystemExit) as stopped:
        main(argv, environ=_FAKE_ENV, transport=no_transport)
    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert _FAKE_TOKEN not in captured.out + captured.err


def test_http_errors_and_responses_redact_the_service_token(capsys: pytest.CaptureFixture[str]) -> None:
    def broken(request: Request) -> bytes:
        raise OSError(f"Fake transport error including {_FAKE_TOKEN}")

    def reflected(request: Request) -> bytes:
        return json.dumps({"summary_vi": _FAKE_TOKEN}).encode()

    assert main(["pending"], environ=_FAKE_ENV, transport=broken) == 1
    assert _FAKE_TOKEN not in capsys.readouterr().err
    assert main(["show", "fixture-id"], environ=_FAKE_ENV, transport=reflected) == 0
    assert json.loads(capsys.readouterr().out) == {"summary_vi": "[redacted]"}
    assert main(["pending"], environ={}, transport=broken) == 2
