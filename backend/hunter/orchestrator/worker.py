"""Dispatch jobs with fenced leases and bounded shutdown."""

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping

from hunter.ai._adapter import health_for
from hunter.config import PaidAPIForbidden
from hunter.interfaces import AIResult, AIStatus, AITask, AIWorker
from hunter.models import AIName, Job, JobError, JobLease, WorkerKind
from hunter.models.common import new_id
from hunter.queue import PersistentQueue
from hunter.services.monitor import MonitorService
from hunter.state import LeaseLost

from .resources import MemoryGovernor

JobOutcome = AIResult | JobError | None
JobHandler = Callable[[Job], Awaitable[JobOutcome]]

DEFAULT_TIMEOUTS = {
    WorkerKind.CLAUDE: 120.0,
    WorkerKind.CODEX: 120.0,
    WorkerKind.GEMINI: 120.0,
    WorkerKind.LOCAL: 60.0,
    WorkerKind.COLLECTOR: 60.0,
}
_AI_ERRORS = {
    AIStatus.AUTH_LOST: JobError.AUTH_LOST,
    AIStatus.UNAVAILABLE: JobError.UNAVAILABLE,
    AIStatus.QUOTA_EXHAUSTED: JobError.QUOTA_EXHAUSTED,
    AIStatus.TIMEOUT: JobError.TIMEOUT,
    AIStatus.ERROR: JobError.ERROR,
}


def _positive(seconds: float) -> bool:
    return math.isfinite(seconds) and seconds > 0


def _consume_outcome(task: asyncio.Task[JobOutcome]) -> None:
    if not task.cancelled():
        task.exception()


class Orchestrator:
    """Run cooperative async handlers; the queue owns all persisted transitions."""

    def __init__(
        self, queue: PersistentQueue, *, monitor: MonitorService | None = None,
        governor: MemoryGovernor | None = None, poll_seconds: float = 0.5,
        grace_seconds: float = 10.0, heartbeat_seconds: float | None = None,
        timeouts: Mapping[WorkerKind, float] | None = None,
    ) -> None:
        self.queue = queue
        self.monitor = MonitorService(queue.database) if monitor is None else monitor
        self.governor = MemoryGovernor() if governor is None else governor
        self._heartbeat = queue.settings.lease_seconds / 3 if heartbeat_seconds is None else heartbeat_seconds
        self._timeouts = {**DEFAULT_TIMEOUTS, **(timeouts or {})}
        if not _positive(poll_seconds) or not math.isfinite(grace_seconds) or grace_seconds < 0:
            raise ValueError("Polling must be positive and shutdown grace must be nonnegative")
        if not _positive(self._heartbeat) or self._heartbeat > queue.settings.lease_seconds / 2:
            raise ValueError("Heartbeat must be positive and at most half the lease duration")
        if any(not _positive(timeout) for timeout in self._timeouts.values()):
            raise ValueError("Worker timeouts must be positive and finite")
        self._poll = poll_seconds
        self._grace = grace_seconds
        self._id = new_id()
        self._handlers: dict[str, tuple[JobHandler, float | None]] = {}
        self._stopping = asyncio.Event()
        self._supervisor: asyncio.Task[None] | None = None

    def register(self, kind: str, handler: JobHandler, *, timeout_seconds: float | None = None) -> None:
        """Register an async handler. Returning None means the handler completed its work."""
        kind = kind.strip()
        if not kind:
            raise ValueError("A job kind is required")
        if timeout_seconds is not None and not _positive(timeout_seconds):
            raise ValueError("Job timeouts must be positive and finite")
        self._handlers[kind] = handler, timeout_seconds

    def register_ai(
        self, kind: str, adapter: AIWorker, make_task: Callable[[Job], AITask],
        *, timeout_seconds: float | None = None,
    ) -> None:
        """Register an AI-only handler and revalidate its output using the original task."""
        async def handle(job: Job) -> AIResult:
            task = make_task(job)
            return (await adapter.run(task)).validate_for(task)

        self.register(kind, handle, timeout_seconds=timeout_seconds)

    async def start(self) -> None:
        if self._supervisor is not None and not self._supervisor.done():
            return
        self.queue.reclaim_expired()
        self._stopping = asyncio.Event()
        self._supervisor = asyncio.create_task(self._serve())

    async def run(self) -> None:
        """Start and serve until stopped. Cancellation requests a graceful stop."""
        await self.start()
        assert self._supervisor is not None
        try:
            await asyncio.shield(self._supervisor)
        except asyncio.CancelledError:
            await self.stop()
            raise

    async def stop(self) -> None:
        if self._supervisor is not None:
            self._stopping.set()
            await asyncio.shield(self._supervisor)

    async def _serve(self) -> None:
        stopped = asyncio.create_task(self._stopping.wait())
        try:
            async with asyncio.TaskGroup() as workers:
                for worker in WorkerKind:
                    workers.create_task(self._worker(worker, stopped))
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)

    async def _worker(self, worker: WorkerKind, stopped: asyncio.Task[bool]) -> None:
        limit = getattr(self.queue.settings, worker.value)
        if limit == 0:
            return
        active: set[asyncio.Task[None]] = set()
        try:
            while not self._stopping.is_set():
                while len(active) < limit and self.governor.allows_claim():
                    lease = self.queue.claim(worker, f"{self._id}-{worker}")
                    if lease is None:
                        break
                    active.add(asyncio.create_task(self._execute(lease)))
                finished, _ = await asyncio.wait(
                    (*active, stopped), timeout=self._poll, return_when=asyncio.FIRST_COMPLETED,
                )
                for attempt in tuple(active):
                    if attempt in finished:
                        active.remove(attempt)
                        attempt.result()
            if active and self._grace > 0:
                done, active = await asyncio.wait(active, timeout=self._grace)
                for attempt in done:
                    attempt.result()
        finally:
            for attempt in active:
                attempt.cancel()
            await asyncio.gather(*active, return_exceptions=True)

    async def _execute(self, lease: JobLease) -> None:
        try:
            registered = self._handlers.get(lease.job.kind)
            if registered is None:
                self.queue.fail(lease.job.id, lease.token, JobError.POLICY_BLOCKED)
                return
            handler, timeout = registered
            deadline_seconds = timeout if timeout is not None else self._timeouts[lease.job.worker]
            outcome = await self._handle(lease, handler, deadline_seconds)
            self._finish(lease, outcome)
        except LeaseLost:
            # Heartbeat, completion and failure all fence stale attempts.
            return

    async def _handle(self, lease: JobLease, handler: JobHandler, timeout: float) -> JobOutcome:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        task = asyncio.create_task(self._call_handler(handler, lease.job))
        task.add_done_callback(_consume_outcome)
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return JobError.TIMEOUT
                done, _ = await asyncio.wait((task,), timeout=min(self._heartbeat, remaining))
                if loop.time() >= deadline:
                    return JobError.TIMEOUT
                if done:
                    return task.result() if not task.cancelled() else JobError.ERROR
                self.queue.heartbeat(lease.job.id, lease.token)
        finally:
            if not task.done():
                task.cancel()

    @staticmethod
    async def _call_handler(handler: JobHandler, job: Job) -> JobOutcome:
        try:
            return await handler(job)
        except PaidAPIForbidden:
            return JobError.POLICY_BLOCKED
        except TimeoutError:
            return JobError.TIMEOUT
        except Exception:
            # Exception text can include credentials or input data.
            return JobError.ERROR

    def _finish(self, lease: JobLease, outcome: JobOutcome) -> None:
        job = lease.job
        if isinstance(outcome, AIResult):
            error = _AI_ERRORS.get(outcome.status)
        elif outcome is None or isinstance(outcome, JobError):
            error = outcome
        else:
            error = JobError.ERROR
        finished = self.queue.complete(job.id, lease.token) if error is None else (
            self.queue.fail(job.id, lease.token, error)
        )
        if not isinstance(outcome, AIResult) or job.worker == WorkerKind.COLLECTOR:
            return
        name = AIName(job.worker)
        if outcome.status == AIStatus.OK and any(
            health.name == name and health.quota_exhausted for health in self.monitor.ai()
        ):
            # An overlapping attempt may finish after a different attempt paused the worker.
            return
        self.monitor.record_ai_health(health_for(name, outcome.status, checked_at=finished.updated_at))
