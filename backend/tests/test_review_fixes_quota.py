from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hunter.config import QueueSettings, SettingsError, load_settings
from hunter.interfaces import AIHealth
from hunter.models import JobError, JobLease, JobStatus, QueueName, WorkerKind
from hunter.queue import PersistentQueue
from hunter.services.monitor import MonitorService

from .support import FixtureClock
from .test_orchestrator_worker import clock, enqueue, queue


def test_quota_cooldown_environment_override_and_validation(tmp_path: Path) -> None:
    path = tmp_path / "settings.toml"
    path.write_text("[queue]\nquota_cooldown_minutes = 15\n", encoding="utf-8")
    key = "HUNTER_QUEUE__QUOTA_COOLDOWN_MINUTES"
    assert QueueSettings().quota_cooldown_minutes == 30
    assert load_settings(path, environ={}).queue.quota_cooldown_minutes == 15
    assert load_settings(path, environ={key: "7"}).queue.quota_cooldown_minutes == 7
    for value in ("0", "-1"):
        with pytest.raises(SettingsError, match="queue.quota_cooldown_minutes"):
            load_settings(path, environ={key: value})


def test_persisted_quota_allows_one_concurrent_probe_and_keeps_blocked_jobs(
    queue: PersistentQueue, clock: FixtureClock,
) -> None:
    job = enqueue(queue, "fixture-quota", priority=QueueName.URGENT)
    waiting = enqueue(queue, "fixture-waiting")
    lease = queue.claim(WorkerKind.CODEX, "fixture-first")
    assert lease is not None
    queue.fail(job.id, lease.token, JobError.QUOTA_EXHAUSTED)
    restarted = PersistentQueue(queue.database, queue.settings, clock=clock)

    clock.move(minutes=29, seconds=59)
    assert restarted.claim(WorkerKind.CODEX, "fixture-early") is None
    clock.move(seconds=1)

    def claim(index: int) -> JobLease | None:
        return restarted.claim(WorkerKind.CODEX, f"fixture-probe-{index}")

    with ThreadPoolExecutor(max_workers=6) as pool:
        probe, = [candidate for candidate in pool.map(claim, range(6)) if candidate is not None]
    assert probe.job.id == job.id
    restarted.fail(job.id, probe.token, JobError.QUOTA_EXHAUSTED)

    for _ in range(5):
        assert restarted.claim(WorkerKind.CODEX, "fixture-too-soon") is None
        clock.move(days=30)
        probe = restarted.claim(WorkerKind.CODEX, "fixture-probe")
        assert probe is not None and probe.job.id == job.id
        assert restarted.fail(job.id, probe.token, JobError.QUOTA_EXHAUSTED).status == JobStatus.QUEUED
    assert restarted.get(waiting.id).attempt_count == 0
    assert restarted.get(job.id).attempt_count == 1

    clock.move(minutes=30)
    probe = restarted.claim(WorkerKind.CODEX, "fixture-recovered")
    assert probe is not None
    restarted.complete(job.id, probe.token, health=AIHealth(
        name="codex", status="OK", available=True, checked_at=clock(),
    ))
    assert MonitorService(queue.database).ai()[0].available
    assert restarted.claim(WorkerKind.CODEX, "fixture-next").job.id == waiting.id


def test_newer_quota_report_wins_even_if_a_probe_succeeds(
    queue: PersistentQueue, clock: FixtureClock,
) -> None:
    job = enqueue(queue, "fixture-quota")
    waiting = enqueue(queue, "fixture-waiting")
    lease = queue.claim(WorkerKind.CODEX, "fixture-first")
    queue.fail(job.id, lease.token, JobError.QUOTA_EXHAUSTED)
    clock.move(minutes=30)
    probe = queue.claim(WorkerKind.CODEX, "fixture-probe")
    assert probe is not None
    clock.move(seconds=1)
    monitor = MonitorService(queue.database)
    monitor.record_ai_health(AIHealth(
        name="codex", status="QUOTA_EXHAUSTED", available=False, quota_exhausted=True, checked_at=clock(),
    ))
    queue.complete(probe.job.id, probe.token, health=AIHealth(
        name="codex", status="OK", available=True, checked_at=clock(),
    ))
    assert monitor.ai()[0].quota_exhausted
    assert queue.claim(WorkerKind.CODEX, "fixture-paused") is None
    assert queue.get(waiting.id).status == JobStatus.QUEUED


def test_expired_probe_restarts_cooldown(queue: PersistentQueue, clock: FixtureClock) -> None:
    job = enqueue(queue, "fixture-quota")
    lease = queue.claim(WorkerKind.CODEX, "fixture-first")
    queue.fail(job.id, lease.token, JobError.QUOTA_EXHAUSTED)
    clock.move(minutes=30)
    assert queue.claim(WorkerKind.CODEX, "fixture-probe") is not None
    clock.move(seconds=queue.settings.lease_seconds)
    assert queue.claim(WorkerKind.CODEX, "fixture-expired") is None
    assert queue.get(job.id).last_error == JobError.LEASE_EXPIRED
    clock.move(minutes=30)
    assert queue.claim(WorkerKind.CODEX, "fixture-next") is not None


def test_legacy_quota_dead_letter_gets_the_same_final_execution_attempt(
    queue: PersistentQueue, clock: FixtureClock,
) -> None:
    job = enqueue(queue, "fixture-legacy-quota")
    for delay in (1, 2, 4):
        lease = queue.claim(WorkerKind.CODEX, "fixture-first")
        assert lease is not None
        queue.fail(job.id, lease.token, JobError.ERROR)
        clock.move(seconds=delay)
    lease = queue.claim(WorkerKind.CODEX, "fixture-final")
    assert lease is not None
    queue.fail(job.id, lease.token, JobError.QUOTA_EXHAUSTED)
    with queue.database.transaction() as connection:
        connection.execute("UPDATE jobs SET status = 'dead' WHERE id = ?", (job.id,))
    assert queue.claim(WorkerKind.CODEX, "fixture-too-soon") is None
    clock.move(minutes=30)
    recovered = queue.claim(WorkerKind.CODEX, "fixture-recovered")
    assert recovered is not None and recovered.job.attempt_count == 4
    assert queue.fail(job.id, recovered.token, JobError.ERROR).status == JobStatus.DEAD
    assert [attempt.error_code for attempt in queue.attempts(job.id)] == [JobError.ERROR] * 4
