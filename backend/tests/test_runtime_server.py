from collections.abc import Callable
from pathlib import Path
from threading import enumerate as running_threads
from time import monotonic, sleep
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from hunter.api.dependencies import Services
from hunter.api.server import create_server_app
from hunter.config import AuthSettings, RuntimeSettings, Settings, SettingsError, load_settings
from hunter.connectors.registry import default_sources
from hunter.db import Database
from hunter.models import AIName, Source, SourceInput
from hunter.runtime.__main__ import main as runtime_main
from hunter.runtime.service import Runtime
from hunter.services.operations import OperationsService

from .support import FixtureClock
from .test_pipeline_handlers import FakeAIWorker, FakeConnector


def _eventually(predicate: Callable[[], bool], *, seconds: float = 6) -> None:
    deadline = monotonic() + seconds
    while not predicate():
        assert monotonic() < deadline, "The expected runtime state was not observed"
        sleep(0.01)


def test_root_mount_and_dashboard_only_serve_build_files(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<html>Dashboard fixture</html>", encoding="utf-8")
    (assets / "index-fixture.js").write_text("const fixture = true", encoding="utf-8")
    (assets / "index-fixture.js.map").write_text("source map fixture", encoding="utf-8")
    (dist / "private.toml").write_text("private settings fixture", encoding="utf-8")
    runtime_factory = Mock(side_effect=AssertionError("Runtime starts only when enabled"))
    settings = Settings(database_path=tmp_path / "hunter.sqlite3", runtime=RuntimeSettings(dashboard_dir=dist))
    with TestClient(create_server_app(settings, runtime_factory=runtime_factory)) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/briefs/inbox").status_code == 200
        assert client.get("/api/review/pending").status_code == 401  # only the Claude leader's token opens review
        assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
        assert client.get("/api/missing").status_code == 404
        assert client.get("/health").status_code == 404
        for path in ("/", "/sources", "/settings", "/briefs/fixture"):
            assert client.get(path).text == "<html>Dashboard fixture</html>"
        assert client.get("/assets/index-fixture.js").text == "const fixture = true"
        assert client.get("/assets/index-fixture.js.map").status_code == 404
        assert client.get("/assets/%2e%2e/private.toml").status_code == 404
        assert client.get("/assets/..%5cprivate.toml").status_code == 404
        assert client.get("/private.toml").text == "<html>Dashboard fixture</html>"
    runtime_factory.assert_not_called()


def test_missing_dashboard_leaves_mounted_api_available(tmp_path: Path) -> None:
    settings = Settings(
        database_path=tmp_path / "hunter.sqlite3", runtime=RuntimeSettings(dashboard_dir=tmp_path / "missing"),
    )
    with TestClient(create_server_app(settings)) as client:
        missing = client.get("/settings")
        assert missing.status_code == 503
        assert "Dashboard build not found" in missing.json()["detail"]
        assert client.get("/api/health").status_code == 200


def test_runtime_settings_environment_override_and_cost_lock(tmp_path: Path) -> None:
    config = tmp_path / "settings.toml"
    config.write_text("[runtime]\nenabled = false\nscheduler_tick_seconds = 44\n", encoding="utf-8")
    settings = load_settings(config, environ={
        "HUNTER_RUNTIME__ENABLED": "1", "HUNTER_RUNTIME__TELEGRAM_POLL_SECONDS": "0.25",
        "HUNTER_RUNTIME__DASHBOARD_URL": "http://localhost:8000/",
    })
    assert settings.runtime.enabled
    assert settings.runtime.scheduler_tick_seconds == 44
    assert settings.runtime.telegram_poll_seconds == 0.25
    assert settings.runtime.dashboard_url == "http://localhost:8000"
    assert settings.runtime.dashboard_dir.is_absolute()
    with pytest.raises(SettingsError):
        load_settings(config, environ={"HUNTER_BUDGET__ALLOW_PAID_API": "true"})


def test_seed_sources_command_is_explicit_idempotent_and_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "hunter.sqlite3"
    config = tmp_path / "settings.toml"
    config.write_text("[runtime]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setenv("HUNTER_CONFIG", str(config))
    monkeypatch.setenv("HUNTER_DATABASE_PATH", str(path))
    with TestClient(create_server_app(load_settings())):
        assert OperationsService(Database(path)).list_sources() == []
    assert runtime_main(["seed-sources"]) == 0
    operations = OperationsService(Database(path))
    sources = operations.list_sources()
    assert {item.connector_id for item in sources} == {item.connector_id for item in default_sources()}
    assert runtime_main(["seed-sources"]) == 0
    assert operations.list_sources() == sources
    assert len(operations.audit()) == len(sources)
    assert all(item.reason for item in operations.audit())
    assert "Default sources added: 0" in capsys.readouterr().out


def test_runtime_runs_real_pipeline_with_fakes_and_shuts_down(tmp_path: Path) -> None:
    clock = FixtureClock()
    fake_ai = FakeAIWorker(clock)
    token = "test-fixture-claude-token-not-a-secret"
    settings = Settings(
        database_path=tmp_path / "hunter.sqlite3", auth=AuthSettings(claude_service_token=token),
        runtime=RuntimeSettings(
            enabled=True, scheduler_tick_seconds=0.01, telegram_poll_seconds=0.01,
            draft_min_virality=0.0, draft_min_relevance=0.0,
        ),
    )
    runtimes: list[Runtime] = []
    original_threads = set(running_threads())

    def build_connector(source: Source) -> FakeConnector:
        return FakeConnector(clock, source)

    def factory(services: Services) -> Runtime:
        runtime = Runtime(services, gemini=fake_ai, build_connector=build_connector, environ={})
        runtimes.append(runtime)
        return runtime

    with TestClient(create_server_app(settings, runtime_factory=factory)) as client:
        runtime, = runtimes
        assert set(runtime.adapters) == set(AIName)
        assert runtime.services.monitor.ai() == []
        runtime.services.operations.save_source(SourceInput(
            name="Fake runtime source", platform="fixture", connector_id=FakeConnector.id,
            url="https://example.invalid/fake-runtime-feed",
        ), reason="Test fixture")
        _eventually(lambda: bool(runtime.services.review.pending()) and bool(runtime.services.monitor.ai()))
        assert len(fake_ai.calls) == 1
        health, = runtime.services.monitor.ai()
        assert health.name == AIName.GEMINI and health.available
        assert client.get("/api/review/pending", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert runtime.services.runtime_notifier is None
    _eventually(lambda: set(running_threads()) <= original_threads)
