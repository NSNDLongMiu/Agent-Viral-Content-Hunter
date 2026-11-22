"""Job handlers that collect, process, and draft through injected ports."""

import asyncio
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from hunter.briefs.drafter import GeminiBriefDrafter
from hunter.connectors.registry import available_connectors
from hunter.ingest.contracts import ClusterPort, IngestPort, IngestResult
from hunter.interfaces import (
    AIHealth, AIResult, AIStatus, AITask, AIWorker, Connector, ConnectorError, FetchLimits, Scorer,
)
from hunter.models import (
    AIName, BriefStatus, ConnectorHealth, ConnectorState, Job, JobError, JobInput, JobStatus, Source, WorkerKind,
)
from hunter.models.common import as_utc
from hunter.orchestrator import Orchestrator
from hunter.queue import PersistentQueue
from hunter.scoring.rules import RuleScorer
from hunter.services.brief_store import BriefStore
from hunter.services.operations import OperationsService
from hunter.state import InvalidTransition, NotFound

from .cooldown import failure_message, server_wait_remaining
from .gate import DraftGate
from .queries import brief_for_item, collect_history, items_missing_process_job, revision_candidates


@dataclass(frozen=True)
class ScanStats:
    collected: int = 0
    new: int = 0
    eligible: int = 0
    selected: int = 0
    skipped: int = 0
    focus_eligible: int = 0
    focus_selected: int = 0


class CollectFlow(Protocol):
    async def __call__(
        self, connector: Connector, source: Source, ingestor: IngestPort, operations: OperationsService,
        *, since: datetime | None, limits: FetchLimits,
    ) -> IngestResult: ...


def _build_connector(source: Source) -> Connector:
    factory = available_connectors().get(source.connector_id)
    if factory is None:
        raise ConnectorError("No collector is registered for this source.")
    return factory(source_id=source.id)


@dataclass(frozen=True)
class Dependencies:
    operations: OperationsService
    briefs: BriefStore
    ingest: IngestPort
    cluster: ClusterPort
    ai_worker: AIWorker
    build_connector: Callable[[Source], Connector] = _build_connector
    collect: CollectFlow | None = None
    fetch_limits: FetchLimits = field(default_factory=FetchLimits)
    scorer: Scorer = field(default_factory=RuleScorer)
    gate: DraftGate = DraftGate()


class _DraftFailure(Exception):
    def __init__(self, result: AIResult) -> None:
        super().__init__(result.status)
        self.result = result


@dataclass
class _DraftWorker:
    worker: AIWorker
    result: AIResult | None = field(init=False, default=None)

    @property
    def name(self) -> AIName:
        return self.worker.name

    def health(self) -> AIHealth:
        return self.worker.health()

    async def run(self, task: AITask) -> AIResult:
        # The drafter raises a generic RuntimeError for non-OK results.
        # Preserve the structured status so the orchestrator can record health and pause quota.
        result = await self.worker.run(task)
        if result.status != AIStatus.OK:
            raise _DraftFailure(result)
        self.result = result.validate_for(task)
        return self.result


def _identifier(job: Job, field: str) -> str:
    value = job.payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Job payload requires {field}")
    return value


def _draft_key(brief_id: str, revision: int) -> str:
    return f"draft:{brief_id}:rev{revision}"


class Pipeline:
    def __init__(self, queue: PersistentQueue, deps: Dependencies) -> None:
        self.queue = queue
        self.deps = deps
        self._connector_locks: dict[str, asyncio.Lock] = {}
        self.last_scan: dict[str, ScanStats] = {}

    async def collect(self, job: Job) -> JobError | None:
        source_id = _identifier(job, "source_id")
        try:
            source = self.deps.operations.get_source(source_id)
        except NotFound:
            return None
        lock = self._connector_locks.setdefault(source.connector_id, asyncio.Lock())
        async with lock:
            if self.queue.get(job.id).status == JobStatus.SUCCEEDED:
                return None
            # Recheck after waiting, as the administrator may have disabled the source.
            try:
                source = self.deps.operations.get_source(source_id)
            except NotFound:
                return None
            if not source.enabled or source.blocked:
                return None
            return await self._collect_source(source)

    async def _collect_source(self, source: Source) -> JobError | None:
        deps = self.deps
        health = next(
            (health for health in deps.operations.connector_health() if health.connector_id == source.connector_id),
            None,
        )
        if server_wait_remaining(health, as_utc(self.queue.clock())) > 0:
            # T1 can only retry on its own cadence. Refuse the fetch while the server's delay is active.
            return JobError.ERROR

        with closing(collect_history(self.queue.database, source.id, status=JobStatus.SUCCEEDED)) as history:
            last_scan = next(history, None)
        # Overlap a scan's full window so items published while it was in flight can be collected.
        since = last_scan.created_at if last_scan else None
        connector: Connector | None = None
        try:
            connector = deps.build_connector(source)
            if deps.collect is None:
                result = deps.ingest.ingest(source, await connector.fetch(since, deps.fetch_limits))
                deps.operations.record_connector_health(connector.health())
            else:
                result = await deps.collect(
                    connector, source, deps.ingest, deps.operations, since=since, limits=deps.fetch_limits,
                )
        except ConnectorError as error:
            observed = connector.health() if connector is not None else None
            status = observed.status if observed else ConnectorState.UNAVAILABLE
            deps.operations.record_connector_health(ConnectorHealth(
                connector_id=source.connector_id,
                status=ConnectorState.DEGRADED if status == ConnectorState.AVAILABLE else status,
                checked_at=max(as_utc(self.queue.clock()), observed.checked_at) if observed else self.queue.clock(),
                last_success_at=health.last_success_at if health else None,
                last_error=failure_message(error),
            ))
            return JobError.ERROR

        recovery_since = last_scan.updated_at if last_scan else None
        recovery_ids = items_missing_process_job(self.queue.database, source.id, since=recovery_since)
        all_new_ids = list(dict.fromkeys([*recovery_ids, *result.new_item_ids]))

        # Call ClusterPort.assign for ALL new items first (cross-source corroboration)
        for raw_item_id in all_new_ids:
            try:
                deps.cluster.assign(raw_item_id)
            except NotFound:
                pass

        # Score each new item with ClusterPort.related_items + the scorer
        candidates: list[tuple[str, ScoringResult]] = []
        for raw_item_id in all_new_ids:
            related = deps.cluster.related_items(raw_item_id)
            if not related:
                continue
            candidates.append((raw_item_id, deps.scorer.score(related)))

        # Apply the draft gate
        eligible = {item_id: scoring for item_id, scoring in candidates if deps.gate.is_eligible(scoring)}
        selected_ids = deps.gate.select(candidates)

        collected_count = len(result.new_item_ids) + result.duplicate_count + result.rejected_count
        new_count = len(all_new_ids)
        selected_count = len(selected_ids)
        skipped_count = new_count - selected_count

        self.last_scan[source.id] = ScanStats(
            collected=collected_count,
            new=new_count,
            eligible=len(eligible),
            selected=selected_count,
            skipped=skipped_count,
            focus_eligible=sum(bool(scoring.focus_tags) for scoring in eligible.values()),
            focus_selected=sum(bool(eligible[item_id].focus_tags) for item_id in selected_ids),
        )

        # Enqueue process_item ONLY for the selected items
        for raw_item_id in selected_ids:
            self._enqueue_process(raw_item_id)
        return None

    def _enqueue_process(self, raw_item_id: str) -> None:
        self.queue.enqueue(JobInput(
            kind="process_item", worker=WorkerKind.LOCAL, idempotency_key=f"process:{raw_item_id}",
            payload={"raw_item_id": raw_item_id},
        ))

    async def process_item(self, job: Job) -> None:
        raw_item_id = _identifier(job, "raw_item_id")
        briefs = self.deps.briefs
        brief = brief_for_item(briefs.database, raw_item_id)
        if brief is None or brief.status == BriefStatus.COLLECTED:
            try:
                self.deps.cluster.assign(raw_item_id)
            except NotFound:
                # Retention may have removed the item before its job was claimed.
                return
            if brief is None:
                brief = briefs.create(raw_item_id=raw_item_id)
        if brief.status == BriefStatus.COLLECTED:
            brief = briefs.advance(brief.id, BriefStatus.PREPROCESSED)
        if brief.status == BriefStatus.PREPROCESSED:
            brief = briefs.advance(brief.id, BriefStatus.PROCESSING)
        if brief.status == BriefStatus.PROCESSING and brief.revision_count == 0:
            self._enqueue_draft(brief.id, raw_item_id, 0, None)

    def _enqueue_draft(self, brief_id: str, raw_item_id: str, revision: int, feedback: str | None) -> None:
        self.queue.enqueue(JobInput(
            kind="draft_brief", worker=WorkerKind.GEMINI, idempotency_key=_draft_key(brief_id, revision),
            payload={"brief_id": brief_id, "raw_item_id": raw_item_id, "feedback": feedback},
        ))

    async def draft_brief(self, job: Job) -> AIResult | JobError | None:
        brief_id = _identifier(job, "brief_id")
        raw_item_id = _identifier(job, "raw_item_id")
        feedback = job.payload.get("feedback")
        if feedback is not None and not isinstance(feedback, str):
            raise ValueError("Draft feedback must be a string or null")

        briefs = self.deps.briefs
        try:
            brief = briefs.progress(brief_id)
        except NotFound:
            return None
        revision = brief.revision_count
        if brief.status != BriefStatus.PROCESSING or job.idempotency_key != _draft_key(brief_id, revision):
            return None

        items = self.deps.cluster.related_items(raw_item_id)
        scores = self.deps.scorer.score(items)
        worker = _DraftWorker(self.deps.ai_worker)
        try:
            draft = await GeminiBriefDrafter(worker).draft(items, scores, feedback=feedback)
        except _DraftFailure as error:
            return error.result
        except ValueError:
            return JobError.ERROR
        try:
            briefs.submit_draft(brief_id, draft, expected_revision=revision)
        except NotFound:
            return None
        except InvalidTransition:
            current = briefs.progress(brief_id)
            if current.status == BriefStatus.PROCESSING and current.revision_count == revision:
                raise
            # An overlapping completion or a newer revision has already moved this brief on.
        return worker.result

    def watch_revisions(self, allow_enqueue: bool = True) -> None:
        """Open requested revisions and recover any opened before their enqueue committed."""
        if not allow_enqueue:
            return
        briefs = self.deps.briefs
        for candidate in revision_candidates(briefs.database):
            try:
                detail = briefs.detail(candidate.id)
                if (
                    detail.brief.status != candidate.status
                    or detail.brief.revision_count != candidate.revision_count
                    or not detail.review_history
                ):
                    continue
                feedback = detail.review_history[-1].reason
                if candidate.status == BriefStatus.REVISION_REQUIRED:
                    progress = briefs.advance(candidate.id, BriefStatus.PROCESSING)
                else:
                    progress = candidate
            except (NotFound, InvalidTransition):
                continue
            self._enqueue_draft(candidate.id, candidate.raw_item_id, progress.revision_count, feedback)


def register_all(orchestrator: Orchestrator, deps: Dependencies) -> Pipeline:
    pipeline = Pipeline(orchestrator.queue, deps)
    orchestrator.register("collect", pipeline.collect)
    orchestrator.register("process_item", pipeline.process_item)
    orchestrator.register("draft_brief", pipeline.draft_brief)
    return pipeline
