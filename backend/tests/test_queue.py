from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from hunter.config import QueueSettings
from hunter.interfaces import AIHealth
from hunter.models import AttemptOutcome, JobError, JobInput, JobStatus, QueueName, WorkerKind
from hunter.queue import PersistentQueue
from hunter.services.monitor import MonitorService
from hunter.state import InvalidTransition, LeaseLost
from hunter.state.jobs import validate_job_transition

from .support import DatabaseTestCase


def fixture_job(key: str, queue: QueueName = QueueName.NORMAL) -> JobInput:
    return JobInput(idempotency_key=key, kind="test-fixture", worker=WorkerKind.CODEX, queue=queue)


class QueueTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.queue = PersistentQueue(
            self.database, QueueSettings(lease_seconds=10, retry_base_seconds=4),
            clock=self.clock, jitter=lambda: 0.5,
        )

    def test_atomic_claim(self) -> None:
        expected = self.queue.enqueue(fixture_job("fixture-unique"))
        start = Barrier(8)

        def claim(index: int):
            start.wait(timeout=5)
            return self.queue.claim(WorkerKind.CODEX, f"fixture-worker-{index}")

        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = [lease for lease in pool.map(claim, range(8)) if lease is not None]
        self.assertEqual([lease.job.id for lease in claims], [expected.id])
        self.assertEqual(len(self.queue.attempts(expected.id)), 1)

    def test_urgent_capacity_and_non_preemption(self) -> None:
        first = self.queue.enqueue(fixture_job("fixture-first"))
        running = self.queue.claim(WorkerKind.CODEX, "fixture-worker-1")
        self.assertEqual(running.job.id, first.id)
        normal = self.queue.enqueue(fixture_job("fixture-normal"))
        urgent = self.queue.enqueue(fixture_job("fixture-urgent", QueueName.URGENT))
        priority_lease = self.queue.claim(WorkerKind.CODEX, "fixture-worker-2")
        self.assertEqual(priority_lease.job.id, urgent.id)
        self.assertEqual(self.queue.get(running.job.id).status, JobStatus.RUNNING)
        self.assertIsNone(self.queue.claim(WorkerKind.CODEX, "fixture-worker-3"))
        self.queue.complete(running.job.id, running.token)
        self.assertEqual(self.queue.claim(WorkerKind.CODEX, "fixture-worker-3").job.id, normal.id)

    def test_crash_recovery_and_fenced_heartbeat(self) -> None:
        job = self.queue.enqueue(fixture_job("fixture-crash"))
        first = self.queue.claim(WorkerKind.CODEX, "fixture-crashed-worker")
        self.clock.move(seconds=8)
        self.queue.heartbeat(job.id, first.token)
        self.clock.move(seconds=3)
        restarted = PersistentQueue(self.database, clock=self.clock)
        self.assertEqual(restarted.reclaim_expired(), 0)
        self.clock.move(seconds=7)
        self.assertEqual(restarted.reclaim_expired(), 1)
        self.assertEqual(restarted.reclaim_expired(), 0)
        recovered = restarted.get(job.id)
        self.assertEqual((recovered.status, recovered.attempt_count), (JobStatus.QUEUED, 1))
        self.assertEqual(restarted.attempts(job.id)[0].outcome, AttemptOutcome.EXPIRED)
        second = restarted.claim(WorkerKind.CODEX, "fixture-restarted-worker")
        self.assertEqual(second.job.attempt_count, 2)
        with self.assertRaises(LeaseLost):
            restarted.heartbeat(job.id, first.token)
        with self.assertRaises(LeaseLost):
            restarted.complete(job.id, first.token)
        self.assertEqual(restarted.complete(job.id, second.token).status, JobStatus.SUCCEEDED)

    def test_three_retries_back_off_then_dead(self) -> None:
        job = self.queue.enqueue(fixture_job("fixture-retry"))
        for attempt, delay in enumerate((4.5, 9, 18, None), start=1):
            lease = self.queue.claim(WorkerKind.CODEX, "fixture-worker")
            self.assertEqual(lease.job.attempt_count, attempt)
            failed = self.queue.fail(job.id, lease.token, JobError.TIMEOUT)
            if delay is None:
                self.assertEqual(failed.status, JobStatus.DEAD)
                break
            self.assertEqual(failed.status, JobStatus.QUEUED)
            self.assertEqual((failed.available_at - self.clock()).total_seconds(), delay)
            self.assertIsNone(self.queue.claim(WorkerKind.CODEX, "fixture-worker"))
            self.clock.move(seconds=delay)
        self.clock.move(days=1)
        self.assertIsNone(self.queue.claim(WorkerKind.CODEX, "fixture-worker"))
        self.assertEqual([attempt.outcome for attempt in self.queue.attempts(job.id)], 4 * [AttemptOutcome.FAILED])

    def test_repeated_crashes_cannot_retry_forever(self) -> None:
        job = self.queue.enqueue(fixture_job("fixture-repeated-crash"))
        for attempt in range(1, 5):
            self.assertEqual(self.queue.claim(WorkerKind.CODEX, "fixture-worker").job.attempt_count, attempt)
            self.clock.move(seconds=10)
            self.assertEqual(self.queue.reclaim_expired(), 1)
        self.assertEqual(self.queue.get(job.id).status, JobStatus.DEAD)
        self.assertIsNone(self.queue.claim(WorkerKind.CODEX, "fixture-worker"))

    def test_idempotent_enqueue(self) -> None:
        first = self.queue.enqueue(fixture_job("fixture-repeat"))
        second = self.queue.enqueue(fixture_job("fixture-repeat", QueueName.URGENT))
        self.assertEqual(first, second)
        self.assertEqual(len(self.queue.list()), 1)

    def test_quota_holds_claims_until_reset_and_policy_failure_is_terminal(self) -> None:
        job = self.queue.enqueue(fixture_job("fixture-quota"))
        lease = self.queue.claim(WorkerKind.CODEX, "fixture-worker")
        self.assertEqual(self.queue.fail(job.id, lease.token, JobError.QUOTA_EXHAUSTED).status, JobStatus.QUEUED)
        self.clock.move(minutes=5)
        self.assertIsNone(self.queue.claim(WorkerKind.CODEX, "fixture-worker"))
        monitor = MonitorService(self.database)
        self.assertEqual(monitor.ai()[0].last_error, "BLOCKED (quota)")
        monitor.record_ai_health(AIHealth(name="codex", status="TIMEOUT", available=False, checked_at=self.clock()))
        self.assertIsNone(self.queue.claim(WorkerKind.CODEX, "fixture-worker"))
        monitor.record_ai_health(AIHealth(name="codex", status="OK", available=True, checked_at=self.clock()))
        resumed = self.queue.claim(WorkerKind.CODEX, "fixture-worker")
        self.assertEqual(resumed.job.attempt_count, 1)
        self.assertEqual(self.queue.fail(job.id, resumed.token, JobError.POLICY_BLOCKED).status, JobStatus.DEAD)

    def test_invalid_job_transition(self) -> None:
        with self.assertRaises(InvalidTransition):
            validate_job_transition(JobStatus.QUEUED, JobStatus.SUCCEEDED)
