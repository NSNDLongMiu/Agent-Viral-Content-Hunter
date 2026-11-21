"""Dispatch jobs with fenced leases and bounded shutdown."""

import asyncio
import logging
import math
import random
import sqlite3
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

_LOG = logging.getLogger(__name__)
_BACKOFF_START = 0.5
_BACKOFF_LIMIT = 30.0
DEFAULT_TIMEOUTS = {
    WorkerKind.CLAUDE: 120.0,
    WorkerKind.CODEX: 120.0,
    WorkerKind.GEMINI: 420.0,  # Initial draft, corrective retry, and job overhead.
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


def _sqlite_busy(error: Exception) -> bool:
    if not isinstance(error, sqlite3.OperationalError):
        return False
    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        return code & 0xff in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    message = str(error).casefold()
    return "locked" in message or "busy" in message


class Orchestrator:
    """Run cooperative async handlers; the queue owns all persisted transitions."""

    def __init__(
        self, queue: PersistentQueue, *, monitor: MonitorService | None = None,
        governor: MemoryGovernor | None = None, poll_seconds: float = 0.5,
        grace_seconds: float = 10.0, heartbeat_seconds: float | None = None,
        timeouts: Mapping[WorkerKind, float] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
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
        self._sleep = sleep
        self._jitter = jitter
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
        if self.running:
            return
        self.queue.reclaim_expired()
        self._stopping = asyncio.Event()
        self._supervisor = asyncio.create_task(self._serve())

    @property
    def running(self) -> bool:
        return self._supervisor is not None and not self._supervisor.done()

    async def run(self) -> None:
        """Start and serve until stopped. Cancellation requests a graceful stop."""
        await self.start()
        assert self._supervisor is not None
        try:
            await asyncio.shield(self._supervisor)
        except asyncio.CancelledError:
            if not asyncio.current_task().cancelling():
                raise RuntimeError("Worker supervisor was cancelled unexpectedly") from None
            await self.stop()
            raise
        if not self._stopping.is_set():
            raise RuntimeError("Worker supervisor exited unexpectedly")

    async def stop(self) -> None:
        if self._supervisor is not None:
            self._stopping.set()
            await asyncio.gather(asyncio.shield(self._supervisor), return_exceptions=True)

    async def _serve(self) -> None:
        stopped = asyncio.create_task(self._stopping.wait())
        try:
            enabled = [worker for worker in WorkerKind if getattr(self.queue.settings, worker.value)]
            if not enabled:
                await stopped
                return
            async with asyncio.TaskGroup() as workers:
                for worker in enabled:
                    workers.create_task(self._worker(worker, stopped))
            if not self._stopping.is_set():
                raise RuntimeError("Workers exited unexpectedly")
        finally:
            stopped.cancel()
            await asyncio.gather(stopped, return_exceptions=True)

    async def _worker(self, worker: WorkerKind, stopped: asyncio.Task[bool]) -> None:
        limit = getattr(self.queue.settings, worker.value)
        active: set[asyncio.Task[None]] = set()
        delay = _BACKOFF_START
        try:
            while not self._stopping.is_set():
                try:
                    for attempt in tuple(active):
                        if not attempt.done():
                            continue
                        active.remove(attempt)
                        if attempt.cancelled():
                            raise RuntimeError("Worker attempt was cancelled unexpectedly")
                        attempt.result()
                    leases: list[JobLease] = []
                    try:
                        while (
                            not self._stopping.is_set() and len(active) + len(leases) < limit
                            and self.governor.allows_claim()
                        ):
                            lease = await asyncio.to_thread(self.queue.claim, worker, f"{self._id}-{worker}")
                            if lease is None:
                                break
                            leases.append(lease)
                    finally:
                        active.update(asyncio.create_task(self._execute(lease)) for lease in leases)
                    await asyncio.wait(
                        (*active, stopped), timeout=self._poll, return_when=asyncio.FIRST_COMPLETED,
                    )
                except Exception as error:
                    if not _sqlite_busy(error):
                        _LOG.error("Worker loop failed for %s. Retrying.", worker)
                    sleeper = asyncio.ensure_future(self._sleep(self._backoff(delay)))
                    try:
                        await asyncio.wait((stopped, sleeper), return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        sleeper.cancel()
                        await asyncio.gather(sleeper, return_exceptions=True)
                    delay = min(delay * 2, _BACKOFF_LIMIT)
                else:
                    delay = _BACKOFF_START
            if active and self._grace > 0:
                done, active = await asyncio.wait(active, timeout=self._grace)
                await asyncio.gather(*done, return_exceptions=True)
        finally:
            for attempt in active:
                attempt.cancel()
            await asyncio.gather(*active, return_exceptions=True)

    def _backoff(self, delay: float) -> float:
        return delay * (0.75 + 0.25 * self._jitter())

    async def _retry_sqlite[T](self, operation: Callable[[], T]) -> T:
        delay = _BACKOFF_START
        while True:
            try:
                return await asyncio.to_thread(operation)
            except sqlite3.OperationalError as error:
                if not _sqlite_busy(error):
                    raise
                await self._sleep(self._backoff(delay))
                delay = min(delay * 2, _BACKOFF_LIMIT)

    async def _execute(self, lease: JobLease) -> None:
        try:
            registered = self._handlers.get(lease.job.kind)
            if registered is None:
                await self._retry_sqlite(lambda: self.queue.fail(lease.job.id, lease.token, JobError.POLICY_BLOCKED))
                return
            handler, timeout = registered
            deadline_seconds = timeout if timeout is not None else self._timeouts[lease.job.worker]
            outcome = await self._handle(lease, handler, deadline_seconds)
            await self._finish(lease, outcome)
        except LeaseLost:
            # Heartbeat, completion and failure all fence stale attempts.
            return

    async def _handle(self, lease: JobLease, handler: JobHandler, timeout: float) -> JobOutcome:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        task = asyncio.create_task(self._call_handler(handler, lease.job))
        task.add_done_callback(_consume_outcome)
        try:
            async with asyncio.timeout_at(deadline):
                while True:
                    done, _ = await asyncio.wait((task,), timeout=self._heartbeat)
                    if loop.time() >= deadline:
                        return JobError.TIMEOUT
                    if done:
                        return task.result() if not task.cancelled() else JobError.ERROR
                    await self._retry_sqlite(lambda: self.queue.heartbeat(lease.job.id, lease.token))
        except TimeoutError:
            return JobError.TIMEOUT
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
            _LOG.error("Job handler failed for %s", job.worker)
            return JobError.ERROR

    async def _finish(self, lease: JobLease, outcome: JobOutcome) -> None:
        job = lease.job
        if isinstance(outcome, AIResult):
            error = _AI_ERRORS.get(outcome.status)
        elif outcome is None or isinstance(outcome, JobError):
            error = outcome
        else:
            error = JobError.ERROR
        health = {}
        if isinstance(outcome, AIResult) and job.worker != WorkerKind.COLLECTOR:
            health["health"] = health_for(AIName(job.worker), outcome.status, checked_at=self.queue.clock())
        if error is None:
            await self._retry_sqlite(lambda: self.queue.complete(job.id, lease.token, **health))
        else:
            await self._retry_sqlite(lambda: self.queue.fail(job.id, lease.token, error, **health))
