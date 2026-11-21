"""Compose the collector, drafting pipeline and Telegram tasks for the local server."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from hunter.ai import ClaudeAdapter, CodexAdapter, GeminiAdapter, LocalAdapter
from hunter.ai.cli_runner import SubprocessRunner
from hunter.api.dependencies import Services
from hunter.ingest import ClusterService, Ingestor, collect
from hunter.interfaces import AIWorker, Connector
from hunter.models import AIName, Job, JobError, JobStatus, QueueName, Source
from hunter.orchestrator import Orchestrator
from hunter.pipeline import Dependencies, DraftGate, register_all
from hunter.scheduler import Scheduler
from hunter.services.monitor import MonitorService
from hunter.services.retention import RetentionService
from hunter.state import IntegrationUnavailable
from hunter.telegram.transport import TelegramTransport

from .telegram import TelegramRuntime

_LOG = logging.getLogger(__name__)
_RETENTION_INTERVAL_SECONDS = 24 * 60 * 60
_SUPERVISOR_RESTART_LIMIT = 5
_SUPERVISOR_STABLE_SECONDS = 60
_SERVER_CREDENTIAL_NAMES = frozenset({
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "HUNTER_AUTH__CLAUDE_SERVICE_TOKEN", "HUNTER_AUTH__ADMIN_PASSWORD_HASH",
})


async def _spawn_cli(
    program: str, /, *args: str, stdin: int, stdout: int, stderr: int,
    env: Mapping[str, str], cwd: Path | None = None, start_new_session: bool = False,
) -> asyncio.subprocess.Process:
    # The adapter runner already strips API keys. Also keep server credentials out of its child processes.
    child_env = {name: env[name] for name in env if name.upper() not in _SERVER_CREDENTIAL_NAMES}
    return await asyncio.create_subprocess_exec(
        program, *args, stdin=stdin, stdout=stdout, stderr=stderr,
        env=child_env, cwd=cwd, start_new_session=start_new_session,
    )


async def _periodic(
    stop: asyncio.Event, action: Callable[[], object], interval: float, failure_message: str, *,
    run_at_start: bool = True,
) -> None:
    while not stop.is_set():
        if run_at_start:
            try:
                await run_in_threadpool(action)
            except Exception:
                # Transport diagnostics and external payloads can contain credentials.
                _LOG.warning(failure_message)
        run_at_start = True
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue


class _RuntimeMonitor(MonitorService):
    def __init__(self, monitor: MonitorService, orchestrator: Orchestrator) -> None:
        super().__init__(monitor.database)
        self._orchestrator = orchestrator

    def queues(self) -> dict[QueueName, dict[JobStatus, int]]:
        if not self._orchestrator.running:
            raise IntegrationUnavailable("Worker supervisor unavailable")
        return super().queues()


class Runtime:
    def __init__(
        self, services: Services, *, gemini: AIWorker | None = None,
        build_connector: Callable[[Source], Connector] | None = None,
        telegram_transport: TelegramTransport | None = None, environ: Mapping[str, str] | None = None,
    ) -> None:
        self.services = services
        self.settings = services.settings.runtime
        budget = services.settings.budget
        runner = SubprocessRunner(spawn=_spawn_cli)
        self.adapters: dict[AIName, AIWorker] = {
            AIName.GEMINI: GeminiAdapter(budget=budget, runner=runner) if gemini is None else gemini,
            AIName.CODEX: CodexAdapter(budget=budget, runner=runner),
            AIName.CLAUDE: ClaudeAdapter(enabled=False, budget=budget, runner=runner),
            AIName.LOCAL: LocalAdapter(),
        }
        # The orchestrator records health from actual pipeline results. In particular,
        # publishing Claude's disabled headless state would block interactive reviews.
        self.orchestrator = Orchestrator(services.queue, monitor=services.monitor)
        ingest = Ingestor(services.database)
        gate = DraftGate(
            min_virality=self.settings.draft_min_virality,
            min_relevance=self.settings.draft_min_relevance,
            max_per_scan=self.settings.max_drafts_per_scan,
        )
        dependencies = Dependencies(
            operations=services.operations, briefs=services.briefs, ingest=ingest,
            cluster=ClusterService(services.database), ai_worker=self.adapters[AIName.GEMINI],
            collect=collect, gate=gate,
        )
        if build_connector is not None:
            dependencies = replace(dependencies, build_connector=build_connector)
        pipeline = register_all(self.orchestrator, dependencies)
        self.pipeline = pipeline

        async def collect_with_logging(job: Job) -> JobError | None:
            source_id = job.payload.get("source_id")
            prev_scan = pipeline.last_scan.get(source_id) if isinstance(source_id, str) else None
            outcome = await pipeline.collect(job)
            if isinstance(source_id, str) and source_id in pipeline.last_scan:
                stats = pipeline.last_scan[source_id]
                if stats is not prev_scan:
                    _LOG.info(
                        "Scan completed for source %s: collected=%d, new=%d, eligible=%d, selected=%d, skipped=%d",
                        source_id, stats.collected, stats.new, stats.eligible, stats.selected, stats.skipped,
                    )
            return outcome

        self.orchestrator.register("collect", collect_with_logging)
        self.scheduler = Scheduler(
            services.queue, services.operations, ingest, pipeline.watch_revisions,
            resource_gate=self.orchestrator.governor.allows_claim,
        )
        self.retention = RetentionService(services.database, services.settings.retention)
        self.telegram = TelegramRuntime(services, transport=telegram_transport, environ=environ)

    async def _watch_workers(self) -> None:
        loop = asyncio.get_running_loop()
        failures = 0
        while True:
            started = loop.time()
            try:
                await self.orchestrator.run()
            except Exception:
                # Supervisor failures may carry SQLite diagnostics or job inputs.
                pass
            _LOG.error("Worker supervisor stopped unexpectedly")
            if loop.time() - started >= _SUPERVISOR_STABLE_SECONDS:
                failures = 0
            if failures >= _SUPERVISOR_RESTART_LIMIT:
                _LOG.error("Worker supervisor restart limit reached")
                return
            await asyncio.sleep(min(30.0, 0.5 * 2 ** failures))
            failures += 1

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        stop = asyncio.Event()
        monitor = self.services.monitor
        self.services.monitor = _RuntimeMonitor(monitor, self.orchestrator)
        workers = asyncio.create_task(self._watch_workers())
        self.services.runtime_notifier = self.telegram.notifier
        tasks = (
            asyncio.create_task(_periodic(
                stop, self.scheduler.tick, self.settings.scheduler_tick_seconds, "Scheduler tick failed",
            )),
            asyncio.create_task(_periodic(
                stop, self.telegram.poll, self.settings.telegram_poll_seconds, "Telegram polling failed",
            )),
            asyncio.create_task(_periodic(
                stop, self.telegram.alert, self.settings.scheduler_tick_seconds, "Telegram alert scan failed",
            )),
            asyncio.create_task(_periodic(
                stop, self.retention.purge, _RETENTION_INTERVAL_SECONDS, "Scheduled SQLite retention failed",
                run_at_start=False,
            )),
        )
        try:
            yield
        finally:
            self.services.runtime_notifier = None
            stop.set()
            workers.cancel()
            try:
                await asyncio.gather(workers, return_exceptions=True)
                await asyncio.gather(*tasks)
            finally:
                self.services.monitor = monitor
