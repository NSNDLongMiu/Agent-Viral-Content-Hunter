import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest

from hunter.config import BudgetSettings, QueueSettings
from hunter.db import Database
from hunter.interfaces import AIHealth, AIResult, AIStatus, AITask
from hunter.models import AIName, AttemptOutcome, Job, JobError, JobInput, JobStatus, QueueName, WorkerKind
from hunter.orchestrator import MemoryGovernor, Orchestrator
from hunter.queue import PersistentQueue

from .support import FixtureClock


@pytest.fixture
def clock() -> FixtureClock:
    return FixtureClock()


@pytest.fixture
def queue(tmp_path: Path, clock: FixtureClock) -> PersistentQueue:
    database = Database(tmp_path / "fixture.sqlite3")
    database.migrate()
    return PersistentQueue(
        database, QueueSettings(lease_seconds=10, local=0, retry_base_seconds=1),
        clock=clock, jitter=lambda: 0,
    )


def enqueue(
    queue: PersistentQueue, key: str, *, worker: WorkerKind = WorkerKind.CODEX,
    kind: str = "fixture", priority: QueueName = QueueName.NORMAL,
) -> Job:
    return queue.enqueue(JobInput(idempotency_key=key, kind=kind, worker=worker, queue=priority))


async def wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(4):
        while not predicate():
            await asyncio.sleep(0.005)


@asynccontextmanager
async def serving(worker: Orchestrator) -> AsyncIterator[None]:
    await worker.start()
    try:
        yield
    finally:
        await worker.stop()


def test_success_uses_queue_priority_and_worker_capacity(queue: PersistentQueue) -> None:
    normal = enqueue(queue, "fixture-normal")
    urgent = enqueue(queue, "fixture-urgent", priority=QueueName.URGENT)
    another = enqueue(queue, "fixture-another")
    disabled = enqueue(queue, "fixture-disabled", worker=WorkerKind.LOCAL)

    async def check() -> None:
        claimed: list[str] = []
        release = asyncio.Event()

        async def handle(job: Job) -> None:
            claimed.append(job.id)
            await release.wait()

        worker = Orchestrator(queue, poll_seconds=0.01, grace_seconds=0)
        worker.register("fixture", handle)
        async with serving(worker):
            await wait_until(lambda: len(claimed) == 2)
            assert claimed == [urgent.id, normal.id]
            assert queue.get(another.id).status == JobStatus.QUEUED
            release.set()
            await wait_until(lambda: queue.get(another.id).status == JobStatus.SUCCEEDED)
        assert queue.get(normal.id).status == queue.get(urgent.id).status == JobStatus.SUCCEEDED
        assert queue.get(disabled.id).attempt_count == 0

    asyncio.run(check())


def test_timeout_retries_three_times_then_dead(queue: PersistentQueue, clock: FixtureClock) -> None:
    job = enqueue(queue, "fixture-timeout")

    async def check() -> None:
        async def handle(job: Job) -> None:
            await asyncio.Event().wait()

        worker = Orchestrator(queue, poll_seconds=0.01, timeouts={WorkerKind.CODEX: 0.04})
        worker.register("fixture", handle)
        async with serving(worker):
            for attempt, delay in enumerate((1, 2, 4, None), start=1):
                await wait_until(lambda: (
                    queue.get(job.id).attempt_count == attempt
                    and queue.get(job.id).status != JobStatus.RUNNING
                ))
                failed = queue.get(job.id)
                assert failed.last_error == JobError.TIMEOUT
                if delay is None:
                    assert failed.status == JobStatus.DEAD
                else:
                    assert failed.status == JobStatus.QUEUED
                    assert failed.available_at - clock() == timedelta(seconds=delay)
                    clock.move(seconds=delay)
        assert len(queue.attempts(job.id)) == 4

    asyncio.run(check())


def test_quota_pauses_kind_and_an_overlapping_success_cannot_unpause(
    queue: PersistentQueue, clock: FixtureClock,
) -> None:
    exhausted = enqueue(queue, "fixture-quota")
    overlap = enqueue(queue, "fixture-overlap")
    waiting = enqueue(queue, "fixture-waiting")
    other = enqueue(queue, "fixture-other", worker=WorkerKind.COLLECTOR)

    async def check() -> None:
        release_quota = asyncio.Event()
        release_overlap = asyncio.Event()
        overlap_started = asyncio.Event()

        async def handle(job: Job) -> AIResult | None:
            if job.id == exhausted.id and job.attempt_count == 1:
                await release_quota.wait()
                return AIResult(status=AIStatus.QUOTA_EXHAUSTED, error="fixture-private-text")
            if job.id == overlap.id:
                overlap_started.set()
                await release_overlap.wait()
                return AIResult(status=AIStatus.OK, output={})
            return None

        worker = Orchestrator(queue, poll_seconds=0.01, grace_seconds=0)
        worker.register("fixture", handle)
        async with serving(worker):
            await asyncio.wait_for(overlap_started.wait(), 4)
            release_quota.set()
            await wait_until(lambda: queue.get(exhausted.id).last_error == JobError.QUOTA_EXHAUSTED)
            release_overlap.set()
            await wait_until(lambda: queue.get(overlap.id).status == JobStatus.SUCCEEDED)
            await wait_until(lambda: queue.get(other.id).status == JobStatus.SUCCEEDED)
            clock.move(hours=1)
            assert queue.claim(WorkerKind.CODEX, "fixture-probe") is None
            assert queue.get(waiting.id).attempt_count == 0
            health = worker.monitor.ai()[0]
            assert health.status == AIStatus.QUOTA_EXHAUSTED
            assert health.last_error == "BLOCKED (quota)"
            worker.monitor.record_ai_health(AIHealth(
                name=AIName.CODEX, status=AIStatus.OK, available=True, checked_at=clock(),
            ))
            await wait_until(lambda: queue.get(exhausted.id).status == JobStatus.SUCCEEDED)
            await wait_until(lambda: queue.get(waiting.id).status == JobStatus.SUCCEEDED)

    asyncio.run(check())


@pytest.mark.parametrize(("status", "error"), [
    (AIStatus.AUTH_LOST, JobError.AUTH_LOST), (AIStatus.UNAVAILABLE, JobError.UNAVAILABLE),
    (AIStatus.TIMEOUT, JobError.TIMEOUT), (AIStatus.ERROR, JobError.ERROR),
])
def test_ai_failures_back_off_and_record_safe_health(
    status: AIStatus, error: JobError, queue: PersistentQueue, clock: FixtureClock,
) -> None:
    job = enqueue(queue, "fixture-failure")

    async def check() -> None:
        async def handle(job: Job) -> AIResult:
            return AIResult(status=status, error="fixture-private-error")

        worker = Orchestrator(queue, poll_seconds=0.01)
        worker.register("fixture", handle)
        async with serving(worker):
            await wait_until(lambda: queue.get(job.id).last_error == error)
            queued = queue.get(job.id)
            assert queued.status == JobStatus.QUEUED
            assert queued.available_at > clock() and queued.attempt_count == 1
            assert queue.claim(WorkerKind.CODEX, "fixture-probe") is None
        health = worker.monitor.ai()[0]
        assert health.status == status and not health.available
        assert "fixture-private-error" not in repr(health)

    asyncio.run(check())


def test_unknown_kind_and_paid_requirement_are_terminal(queue: PersistentQueue) -> None:
    unknown = enqueue(queue, "fixture-unknown", kind="fixture-unknown")
    paid = enqueue(queue, "fixture-paid")

    async def check() -> None:
        async def handle(job: Job) -> None:
            BudgetSettings().require_allowed(incurs_cost=True)

        worker = Orchestrator(queue, poll_seconds=0.01)
        worker.register("fixture", handle)
        async with serving(worker):
            for job in (unknown, paid):
                await wait_until(lambda: queue.get(job.id).status == JobStatus.DEAD)
                failed = queue.get(job.id)
                assert failed.last_error == JobError.POLICY_BLOCKED and failed.attempt_count == 1

    asyncio.run(check())


def test_heartbeat_extends_a_live_lease(queue: PersistentQueue, clock: FixtureClock) -> None:
    job = enqueue(queue, "fixture-heartbeat")

    async def check() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def handle(job: Job) -> None:
            started.set()
            await release.wait()

        worker = Orchestrator(queue, heartbeat_seconds=0.025, poll_seconds=0.01, grace_seconds=0)
        worker.register("fixture", handle)
        async with serving(worker):
            await asyncio.wait_for(started.wait(), 4)
            original = queue.get(job.id).lease_expires_at
            assert original is not None
            clock.move(seconds=6)
            await wait_until(lambda: queue.get(job.id).lease_expires_at == original + timedelta(seconds=6))
            clock.move(seconds=5)
            assert queue.reclaim_expired() == 0
            release.set()
            await wait_until(lambda: queue.get(job.id).status == JobStatus.SUCCEEDED)

    asyncio.run(check())


@pytest.mark.parametrize("lose_on_heartbeat", [True, False])
def test_result_from_lost_lease_is_discarded(
    lose_on_heartbeat: bool, queue: PersistentQueue, clock: FixtureClock,
) -> None:
    job = enqueue(queue, "fixture-stale")

    async def check() -> None:
        used_capacity = False
        release = asyncio.Event()
        started = asyncio.Event()
        cancelled = asyncio.Event()
        governor = MemoryGovernor(80, sample=lambda: 100 if used_capacity else 0)

        async def handle(job: Job) -> AIResult:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
            return AIResult(status=AIStatus.QUOTA_EXHAUSTED)

        worker = Orchestrator(
            queue, governor=governor, heartbeat_seconds=0.025, poll_seconds=0.01, grace_seconds=1,
        )
        worker.register("fixture", handle)
        async with serving(worker):
            await asyncio.wait_for(started.wait(), 4)
            used_capacity = True
            clock.move(seconds=10)
            replacement = queue.claim(WorkerKind.CODEX, "fixture-replacement")
            assert replacement is not None
            if lose_on_heartbeat:
                await asyncio.wait_for(cancelled.wait(), 4)
            else:
                release.set()
            await worker.stop()
            assert queue.get(job.id) == replacement.job
            assert worker.monitor.ai() == []
            assert queue.attempts(job.id)[0].outcome == AttemptOutcome.EXPIRED
            queue.complete(job.id, replacement.token)

    asyncio.run(check())


@pytest.mark.parametrize("finish_in_grace", [True, False])
def test_graceful_stop_stops_claiming_and_only_completes_finished_jobs(
    finish_in_grace: bool, queue: PersistentQueue,
) -> None:
    job = enqueue(queue, "fixture-running", worker=WorkerKind.CLAUDE)
    waiting = enqueue(queue, "fixture-waiting", worker=WorkerKind.CLAUDE)

    async def check() -> None:
        release = asyncio.Event()
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def handle(job: Job) -> None:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()

        worker = Orchestrator(queue, poll_seconds=0.01, grace_seconds=0.1 if finish_in_grace else 0)
        worker.register("fixture", handle)
        async with serving(worker):
            await asyncio.wait_for(started.wait(), 4)
            stopping = asyncio.create_task(worker.stop())
            await asyncio.sleep(0)
            if finish_in_grace:
                release.set()
            await asyncio.wait_for(stopping, 4)
            if not finish_in_grace:
                assert cancelled.is_set()
                release.set()
                await asyncio.sleep(0)
        assert queue.get(waiting.id).attempt_count == 0
        assert queue.get(job.id).status == (JobStatus.SUCCEEDED if finish_in_grace else JobStatus.RUNNING)

    asyncio.run(check())


def test_startup_reclaims_expired_work_even_when_memory_blocks_claims(
    queue: PersistentQueue, clock: FixtureClock,
) -> None:
    job = enqueue(queue, "fixture-restart")
    assert queue.claim(WorkerKind.CODEX, "fixture-crashed") is not None
    clock.move(seconds=10)
    restarted_queue = PersistentQueue(queue.database, queue.settings, clock=clock)

    async def check() -> None:
        used = 95
        worker = Orchestrator(
            restarted_queue, governor=MemoryGovernor(90, sample=lambda: used), poll_seconds=0.01,
        )

        async def handle(job: Job) -> None:
            assert job.attempt_count == 2

        worker.register("fixture", handle)
        async with serving(worker):
            assert restarted_queue.get(job.id).status == JobStatus.QUEUED
            assert restarted_queue.attempts(job.id)[0].outcome == AttemptOutcome.EXPIRED
            await asyncio.sleep(0.04)
            assert restarted_queue.get(job.id).attempt_count == 1
            used = 90
            await wait_until(lambda: restarted_queue.get(job.id).status == JobStatus.SUCCEEDED)

    asyncio.run(check())


def test_registered_ai_response_is_validated_at_the_worker_boundary(queue: PersistentQueue) -> None:
    job = enqueue(queue, "fixture-ai")
    task = AITask(
        id=job.id, instructions="Fixture", input={},
        output_schema={"type": "object", "required": ["ok"]},
    )

    class FakeAdapter:
        name = AIName.CODEX

        async def run(self, task: AITask) -> AIResult:
            return AIResult(status=AIStatus.OK, output={})

        def health(self) -> AIHealth:
            raise AssertionError("Health is derived from the fenced outcome")

    async def check() -> None:
        worker = Orchestrator(queue, poll_seconds=0.01)
        worker.register_ai("fixture", FakeAdapter(), lambda job: task)
        async with serving(worker):
            await wait_until(lambda: queue.get(job.id).last_error == JobError.ERROR)
        assert queue.get(job.id).status == JobStatus.QUEUED

    asyncio.run(check())
