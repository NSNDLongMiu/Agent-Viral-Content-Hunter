"""Schedule a single due collection per source using durable scan history."""

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from hashlib import blake2b
from itertools import chain, takewhile

from hunter.ingest.contracts import IngestPort
from hunter.interfaces import Scorer
from hunter.models import ConnectorHealth, ConnectorState, Job, JobInput, JobStatus, QueueName, Source, WorkerKind
from hunter.models.common import as_utc
from hunter.pipeline.cooldown import server_wait_remaining
from hunter.pipeline.queries import CollectScan, collect_history, has_rising_cluster, scan_items
from hunter.queue import PersistentQueue
from hunter.scoring.rules import RuleScorer
from hunter.services.operations import OperationsService
from hunter.state import NotFound

from .policy import ScanOutcome, ScanPolicy, SourceClass, source_class


def _stable_jitter(key: str) -> float:
    digest = blake2b(key.encode(), digest_size=8).digest()
    return int.from_bytes(digest) / (2**64 - 1)


def _allows_collection() -> bool:
    return True


@dataclass
class _Observation:
    item_ids: list[str]
    strong_count: int

    @property
    def outcome(self) -> ScanOutcome:
        if not self.item_ids:
            return ScanOutcome.EMPTY
        return ScanOutcome.STRONG if self.strong_count else ScanOutcome.NORMAL


class Scheduler:
    def __init__(
        self, queue: PersistentQueue, operations: OperationsService, ingest: IngestPort,
        watch_revisions: Callable[[bool], None], *, resource_gate: Callable[[], bool] = _allows_collection,
        policy: ScanPolicy | None = None, scorer: Scorer | None = None,
        clock: Callable[[], datetime] | None = None, jitter: Callable[[str], float] = _stable_jitter,
    ) -> None:
        self.queue = queue
        self.operations = operations
        self.ingest = ingest
        self.watch_revisions = watch_revisions
        self.resource_gate = resource_gate
        self.policy = policy if policy is not None else ScanPolicy()
        self.scorer = scorer if scorer is not None else RuleScorer()
        self.clock = clock if clock is not None else queue.clock
        self.jitter = jitter

    def tick(self, now: datetime | None = None) -> list[Job]:
        """Check for revisions and enqueue at most one due collect job per source."""
        instant = as_utc(now if now is not None else self.clock())
        allow_enqueue = self.resource_gate()
        self.watch_revisions(allow_enqueue)
        if not allow_enqueue:
            return []

        # SQLite's negative LIMIT returns all rows from OperationsService.list_sources.
        sources = self.operations.list_sources(limit=-1)
        connector_counts = Counter(source.connector_id for source in sources)
        health = {status.connector_id: status for status in self.operations.connector_health()}
        intervals = self.operations.preferences().scan_intervals_minutes
        jobs: list[Job] = []
        for source in sources:
            if not source.enabled or source.blocked:
                continue
            observation = health.get(source.connector_id)
            base_seconds = self.policy.base_seconds(source.priority, intervals)
            collect = self._due_collect(
                source, observation, instant, base_seconds, connector_counts[source.connector_id] == 1,
            )
            if collect is not None:
                jobs.append(self.queue.enqueue(collect, available_at=instant))
        return jobs

    def _due_collect(
        self, source: Source, health: ConnectorHealth | None, now: datetime, base_seconds: int,
        only_connector_source: bool,
    ) -> JobInput | None:
        if server_wait_remaining(health, now) > 0:
            return None

        with closing(collect_history(self.queue.database, source.id)) as history:
            latest = next(history, None)
            if latest is not None and latest.status in (JobStatus.QUEUED, JobStatus.RUNNING):
                return None
            failures = (
                1 + sum(1 for _ in takewhile(lambda scan: scan.status == JobStatus.DEAD, history))
                if latest is not None and latest.status == JobStatus.DEAD else 0
            )

        last_scan = latest.updated_at if latest is not None else None
        if health is not None:
            if last_scan is None and only_connector_source and health.last_success_at is not None:
                if health.last_success_at >= source.created_at:
                    last_scan = health.last_success_at
            if health.status in (ConnectorState.BLOCKED, ConnectorState.UNAVAILABLE):
                last_scan = max(last_scan, health.checked_at) if last_scan is not None else health.checked_at
                failures = max(failures, 1)

        # The next interval starts from persisted completion. If several intervals were
        # missed, enqueue only the next slot. Changing the cadence never reuses a slot.
        slot = latest.slot + 1 if latest is not None else 0
        key = f"collect:{source.id}:{slot}"
        elapsed = (now - last_scan).total_seconds() if last_scan is not None else None
        if elapsed is not None and elapsed < base_seconds * self.policy.minimum_factor:
            return None

        rising = False
        if elapsed is not None:
            with closing(collect_history(self.queue.database, source.id, status=JobStatus.SUCCEEDED)) as history:
                observations = (self._observe(source.id, scan) for scan in history)
                current = next(observations, None)
                previous = next(observations, None)
                first = (observation for observation in (current, previous) if observation is not None)
                outcomes = (observation.outcome for observation in chain(first, observations))
                delay = self.policy.delay_seconds(base_seconds, outcomes, failures=failures, jitter=self.jitter(key))
                if elapsed < delay:
                    return None
                rising = current is not None and (
                    has_rising_cluster(self.queue.database, current.item_ids)
                    or (previous is not None and current.strong_count > previous.strong_count)
                )

        urgent = source_class(source.priority) == SourceClass.HOT_NEWS or rising
        return JobInput(
            idempotency_key=key, kind="collect", worker=WorkerKind.COLLECTOR,
            queue=QueueName.URGENT if urgent else QueueName.NORMAL, payload={"source_id": source.id},
        )

    def _observe(self, source_id: str, scan: CollectScan) -> _Observation:
        item_ids = scan_items(self.queue.database, source_id, scan.created_at, scan.updated_at)
        strong_count = 0
        for raw_item_id in item_ids:
            try:
                item = self.ingest.get_item(raw_item_id)
            except NotFound:
                continue
            if self.scorer.score([item]).virality >= self.policy.strong_virality:
                strong_count += 1
        return _Observation(item_ids, strong_count)
