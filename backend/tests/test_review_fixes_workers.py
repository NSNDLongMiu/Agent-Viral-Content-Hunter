import asyncio
import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hunter.api.auth import hash_password
from hunter.api.dependencies import Services
from hunter.api.server import create_server_app
from hunter.config import AuthSettings, RuntimeSettings, Settings
from hunter.models import Job, JobError, JobLease, JobStatus, WorkerKind
from hunter.orchestrator import Orchestrator
from hunter.queue import PersistentQueue
from hunter.runtime.service import Runtime

from .test_orchestrator_worker import clock, enqueue, queue, serving, wait_until
from .test_runtime_server import _eventually


@pytest.mark.parametrize("operation", ["claim", "heartbeat", "complete", "fail"])
def test_worker_retries_transient_sqlite_operations(
    queue: PersistentQueue, operation: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = enqueue(queue, "fixture-retry")
    original: Callable[..., object] = getattr(queue, operation)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        await asyncio.sleep(0)

    retry_pending = True

    def fail_once(*args: object, **kwargs: object) -> object:
        nonlocal retry_pending
        if retry_pending and (operation != "claim" or args[0] == WorkerKind.CODEX):
            retry_pending = False
            raise sqlite3.OperationalError("database is locked")
        return original(*args, **kwargs)

    monkeypatch.setattr(queue, operation, fail_once)

    async def check() -> None:
        worker = Orchestrator(
            queue, poll_seconds=0.01, heartbeat_seconds=0.02, sleep=fake_sleep, jitter=lambda: 1.0,
        )

        async def handler(_job: Job) -> JobError | None:
            if operation == "heartbeat":
                await wait_until(lambda: bool(delays))
            return JobError.TIMEOUT if operation == "fail" else None

        worker.register("fixture", handler)
        async with serving(worker):
            if operation == "fail":
                await wait_until(lambda: queue.get(job.id).last_error == JobError.TIMEOUT)
            else:
                await wait_until(lambda: queue.get(job.id).status == JobStatus.SUCCEEDED)
            assert queue.get(job.id).attempt_count == 1
            assert delays == [0.5]

    asyncio.run(check())


@pytest.mark.parametrize("busy", [True, False])
def test_persistent_claim_failure_stays_alive_and_backs_off(
    queue: PersistentQueue, busy: bool, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    job = enqueue(queue, "fixture-blocked")
    other = enqueue(queue, "fixture-other", worker=WorkerKind.COLLECTOR)
    original = queue.claim
    private_diagnostic = "fixture SQL parameter containing secret"
    delays: list[float] = []

    release: asyncio.Event

    def fake_claim(worker: WorkerKind, worker_id: str) -> JobLease | None:
        if worker == WorkerKind.CODEX and len(delays) < 9:
            if busy:
                raise sqlite3.OperationalError("database busy")
            raise sqlite3.OperationalError(private_diagnostic)
        return original(worker, worker_id)

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) == 9:
            await release.wait()
        else:
            await asyncio.sleep(0)

    async def handler(_job: Job) -> None:
        pass

    monkeypatch.setattr(queue, "claim", fake_claim)

    async def check() -> None:
        nonlocal release
        release = asyncio.Event()
        worker = Orchestrator(queue, poll_seconds=0.01, sleep=fake_sleep, jitter=lambda: 1.0)
        worker.register("fixture", handler)
        async with serving(worker):
            await wait_until(lambda: len(delays) == 9)
            await wait_until(lambda: queue.get(other.id).status == JobStatus.SUCCEEDED)
            assert queue.get(job.id).status == JobStatus.QUEUED
            assert worker.running
            release.set()
            await wait_until(lambda: queue.get(job.id).status == JobStatus.SUCCEEDED)

    asyncio.run(check())
    assert delays == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    assert private_diagnostic not in caplog.text
    if not busy:
        assert "Worker loop failed for codex" in caplog.text


def test_crashing_job_handler_does_not_stop_other_workers(
    queue: PersistentQueue, caplog: pytest.LogCaptureFixture,
) -> None:
    crashing = enqueue(queue, "fixture-crashing")
    other = enqueue(queue, "fixture-other", worker=WorkerKind.COLLECTOR)
    private_diagnostic = "fixture credential in handler exception"

    async def check() -> None:
        handler_crashed = asyncio.Event()

        async def handler(job: Job) -> None:
            if job.id == crashing.id:
                handler_crashed.set()
                raise RuntimeError(private_diagnostic)
            await handler_crashed.wait()

        worker = Orchestrator(queue, poll_seconds=0.01)
        worker.register("fixture", handler)
        async with serving(worker):
            await wait_until(lambda: queue.get(crashing.id).last_error == JobError.ERROR)
            await wait_until(lambda: queue.get(other.id).status == JobStatus.SUCCEEDED)
            assert worker.running

    asyncio.run(check())
    assert "Job handler failed for codex" in caplog.text
    assert private_diagnostic not in caplog.text


@pytest.mark.parametrize("restarts_successfully", [True, False])
def test_runtime_monitors_and_restarts_unexpected_supervisor_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    restarts_successfully: bool,
) -> None:
    monkeypatch.setattr("hunter.runtime.service._SUPERVISOR_RESTART_LIMIT", 1)
    password = "Fixture supervisor monitor password"
    settings = Settings(
        database_path=tmp_path / "hunter.sqlite3",
        auth=AuthSettings(admin_password_hash=hash_password(password)),
        runtime=RuntimeSettings(enabled=True),
    )
    starts: list[None] = []
    private_diagnostic = "fixture SQL values from supervisor"

    def factory(services: Services) -> Runtime:
        runtime = Runtime(services, environ={})
        serve = runtime.orchestrator._serve

        async def fake_serve() -> None:
            starts.append(None)
            if len(starts) == 1:
                # An unexpected clean return must also be detected.
                return
            if restarts_successfully:
                await serve()
            else:
                raise RuntimeError(private_diagnostic)

        monkeypatch.setattr(runtime.orchestrator, "_serve", fake_serve)
        return runtime

    with TestClient(create_server_app(settings, runtime_factory=factory)) as client:
        token = client.post("/api/auth/login", json={"password": password}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        _eventually(lambda: "Worker supervisor stopped unexpectedly" in caplog.text)
        queues = "/api/monitor/queues"
        outage = client.get(queues, headers=headers)
        assert outage.status_code == 503
        assert outage.json()["detail"] == "Worker supervisor unavailable"
        assert client.get("/api/health").status_code == 200
        if restarts_successfully:
            _eventually(lambda: client.get(queues, headers=headers).status_code == 200)
        else:
            _eventually(lambda: "Worker supervisor restart limit reached" in caplog.text)
            assert client.get(queues, headers=headers).status_code == 503
        assert len(starts) == 2
    assert private_diagnostic not in caplog.text
