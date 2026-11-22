import ast
import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hunter.briefs.prompts import REQUIRED_WHY_NOTABLE_LABELS
from hunter.connectors.http import HttpConnectorError
from hunter.db import Database
from hunter.ingest.contracts import IngestPort, IngestResult
from hunter.interfaces import AIHealth, AIResult, AIStatus, AITask, Connector, FetchLimits
from hunter.models import (
    AIName, BriefStatus, ConnectorHealth, ConnectorState, Job, JobError, JobInput, JobStatus,
    RawItem, ReviewInput, Source, SourceInput, WorkerKind,
)
from hunter.models.common import utcnow
from hunter.orchestrator import Orchestrator
from hunter.pipeline import Dependencies, DraftGate, Pipeline, ScanStats, register_all
from hunter.queue import PersistentQueue
from hunter.services.brief_store import BriefStore
from hunter.services.operations import OperationsService
from hunter.services.review import ReviewService
from hunter.state import NotFound

from .support import FixtureClock


class FakeIngest:
    def __init__(self, operations: OperationsService) -> None:
        self.operations = operations

    def ingest(self, source: Source, items: Sequence[RawItem]) -> IngestResult:
        ids: list[str] = []
        for item in items:
            with self.operations.database.connection() as connection:
                duplicate = connection.execute(
                    "SELECT 1 FROM raw_items WHERE source_id = ? AND source_url = ?",
                    (source.id, str(item.source_url)),
                ).fetchone()
            if duplicate is None:
                ids.append(self.operations.store_raw_item(item))
        return IngestResult(new_item_ids=ids, duplicate_count=len(items) - len(ids))

    def get_item(self, raw_item_id: str) -> RawItem:
        with self.operations.database.connection() as connection:
            row = connection.execute("SELECT * FROM raw_items WHERE id = ?", (raw_item_id,)).fetchone()
        if row is None:
            raise NotFound("Fake item missing")
        data = dict(row)
        del data["id"], data["created_at"]
        data["metrics"] = json.loads(data.pop("metrics_json") or "null")
        data["metadata"] = json.loads(data.pop("metadata_json"))
        return RawItem.model_validate(data)


@dataclass
class FakeCluster:
    ingest: FakeIngest
    assigned: set[str] = field(default_factory=set)

    def assign(self, raw_item_id: str) -> str | None:
        self.ingest.get_item(raw_item_id)
        self.assigned.add(raw_item_id)
        return None

    def related_items(self, raw_item_id: str, *, limit: int = 10) -> list[RawItem]:
        return [self.ingest.get_item(raw_item_id)]


class FakeConnector:
    id = "fake_connector"
    capabilities = ()

    def __init__(self, clock: FixtureClock, source: Source) -> None:
        self.clock = clock
        self.item = RawItem(
            source_id=source.id, source_url="https://example.invalid/fake-item",
            fetched_at=clock(), title="Dữ liệu kiểm thử",
        )
        self.calls: list[datetime | None] = []
        self.failure: HttpConnectorError | None = None

    async def fetch(self, since: datetime | None, limits: FetchLimits) -> list[RawItem]:
        self.calls.append(since)
        if self.failure is not None:
            raise self.failure
        return [self.item]

    def health(self) -> ConnectorHealth:
        return ConnectorHealth(
            connector_id=self.id, checked_at=self.clock(),
            status=ConnectorState.UNAVAILABLE if self.failure else ConnectorState.AVAILABLE,
            last_success_at=None if self.failure else self.clock(),
        )


@dataclass
class FakeAIWorker:
    clock: FixtureClock
    name = AIName.GEMINI
    status: AIStatus = AIStatus.OK
    valid: bool = True
    calls: list[AITask] = field(default_factory=list)

    async def run(self, task: AITask) -> AIResult:
        self.calls.append(task)
        if self.status != AIStatus.OK:
            return AIResult(status=self.status, error="Fake AI returned a failure")
        return AIResult.success(task, {
            "title_vi": "Dữ liệu kiểm thử",
            "summary_vi": " ".join(["Nội dung kiểm thử"] * 13) if self.valid else "Thiếu",
            "why_notable": "\n".join(f"{label} Dữ liệu kiểm thử." for label in REQUIRED_WHY_NOTABLE_LABELS),
            "risks_and_notes": ["Dữ liệu kiểm thử"],
            "suggested_formats": [],
            "ai_production": {
                "feasibility": "CAO",
                "approach_vi": (
                    "Tạo hình minh họa và dựng một đoạn phim hoạt hình gốc với các nhân vật hư cấu."
                ),
                "constraints_vi": ["Dùng nhân vật hư cấu và kiểm tra quyền sử dụng hình ảnh."],
            },
        })

    def health(self) -> AIHealth:
        return AIHealth(
            name=self.name, status=self.status, available=self.status == AIStatus.OK,
            checked_at=self.clock(), quota_exhausted=self.status == AIStatus.QUOTA_EXHAUSTED,
        )


class PipelineFixture:
    def __init__(self, database: Database) -> None:
        self.clock = FixtureClock()
        self.queue = PersistentQueue(database, clock=self.clock, jitter=lambda: 0.0)
        self.operations = OperationsService(database, clock=self.clock)
        self.briefs = BriefStore(database, clock=self.clock)
        self.source = self.operations.save_source(SourceInput(
            name="Fake source", connector_id=FakeConnector.id, platform="fake",
            url="https://example.invalid/fake-feed",
        ), reason="Test fixture")
        self.ingest = FakeIngest(self.operations)
        self.cluster = FakeCluster(self.ingest)
        self.connector = FakeConnector(self.clock, self.source)
        self.ai = FakeAIWorker(self.clock)
        self.orchestrator = Orchestrator(self.queue)
        self.deps = Dependencies(
            self.operations, self.briefs, self.ingest, self.cluster, self.ai,
            build_connector=lambda source: self.connector,
            gate=DraftGate(min_virality=0.0, min_relevance=0.0),
        )
        self.pipeline = register_all(self.orchestrator, self.deps)

    def enqueue_collect(self, slot: int = 0) -> Job:
        return self.queue.enqueue(JobInput(
            kind="collect", worker=WorkerKind.COLLECTOR, idempotency_key=f"collect:{self.source.id}:{slot}",
            payload={"source_id": self.source.id},
        ))

    def run(self, worker: WorkerKind) -> Job:
        lease = self.queue.claim(worker, "fake-worker")
        assert lease is not None
        asyncio.run(self.orchestrator._execute(lease))
        return self.queue.get(lease.job.id)

    def process_to_draft_job(self) -> Job:
        self.enqueue_collect()
        assert self.run(WorkerKind.COLLECTOR).status == JobStatus.SUCCEEDED
        assert self.run(WorkerKind.LOCAL).status == JobStatus.SUCCEEDED
        return self.queue.list(status=JobStatus.QUEUED)[0]


@pytest.fixture
def fixture(tmp_path: Path) -> PipelineFixture:
    database = Database(tmp_path / "pipeline-fixture.sqlite3")
    database.migrate()
    return PipelineFixture(database)


def test_full_chain_and_idempotent_handler_replay(fixture: PipelineFixture) -> None:
    collect = fixture.enqueue_collect()
    assert fixture.enqueue_collect().id == collect.id
    draft = fixture.process_to_draft_job()
    process = next(job for job in fixture.queue.list() if job.kind == "process_item")
    brief_id = str(draft.payload["brief_id"])
    raw_id = str(process.payload["raw_item_id"])
    assert process.idempotency_key == f"process:{raw_id}"
    assert draft.idempotency_key == f"draft:{brief_id}:rev0"

    assert fixture.run(WorkerKind.GEMINI).status == JobStatus.SUCCEEDED
    # Replay stale handlers, including a retry after submit succeeded.
    asyncio.run(fixture.pipeline.collect(collect))
    asyncio.run(fixture.pipeline.process_item(process))
    assert asyncio.run(fixture.pipeline.draft_brief(draft)) is None

    assert len(fixture.queue.list()) == 3
    assert fixture.connector.calls == [None]
    assert len(fixture.ai.calls) == 1
    assert fixture.cluster.assigned == {raw_id}
    detail = fixture.briefs.detail(brief_id)
    assert detail.brief.status == BriefStatus.PENDING_CLAUDE_REVIEW
    assert detail.brief.original_url == fixture.connector.item.source_url
    assert detail.review_history == []
    with fixture.queue.database.connection() as connection:
        assert connection.execute("SELECT count(*) FROM raw_items").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM briefs").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM brief_revisions").fetchone()[0] == 1


def test_collect_port_recovers_items_if_ingest_commits_before_enqueue(fixture: PipelineFixture) -> None:
    calls: list[IngestResult] = []

    async def fake_collect_flow(
        connector: Connector, source: Source, ingestor: IngestPort, operations: OperationsService,
        *, since: datetime | None, limits: FetchLimits,
    ) -> IngestResult:
        result = ingestor.ingest(source, await connector.fetch(since, limits))
        calls.append(result)
        if len(calls) == 1:
            raise OSError("Simulated interruption after ingest")
        operations.record_connector_health(connector.health())
        return result

    register_all(fixture.orchestrator, replace(fixture.deps, collect=fake_collect_flow))
    first = fixture.enqueue_collect()
    failed = fixture.run(WorkerKind.COLLECTOR)
    assert failed.id == first.id
    assert failed.status == JobStatus.QUEUED
    fixture.clock.now = failed.available_at
    assert fixture.run(WorkerKind.COLLECTOR).status == JobStatus.SUCCEEDED
    assert calls[0].new_item_ids
    assert calls[1].new_item_ids == []
    assert fixture.queue.list(status=JobStatus.QUEUED)[0].payload == {"raw_item_id": calls[0].new_item_ids[0]}


def test_collect_enqueues_metricless_focus_item(fixture: PipelineFixture) -> None:
    now = utcnow()
    focus_item = RawItem(
        source_id=fixture.source.id, source_url="https://example.invalid/focus",
        fetched_at=now, title="Short film showcase",
    )
    general_item = RawItem(
        source_id=fixture.source.id, source_url="https://example.invalid/general",
        fetched_at=now, title="Local transport timetable",
    )

    class FakeFeed(FakeConnector):
        async def fetch(self, since: datetime | None, limits: FetchLimits) -> list[RawItem]:
            return [focus_item, general_item]

    pipeline = register_all(fixture.orchestrator, replace(
        fixture.deps, build_connector=lambda source: FakeFeed(fixture.clock, source), gate=DraftGate(),
    ))
    fixture.enqueue_collect()
    assert fixture.run(WorkerKind.COLLECTOR).status == JobStatus.SUCCEEDED

    assert pipeline.last_scan[fixture.source.id] == ScanStats(
        collected=2, new=2, eligible=1, selected=1, skipped=1, focus_eligible=1, focus_selected=1,
    )
    queued_jobs = fixture.queue.list(status=JobStatus.QUEUED)
    assert len(queued_jobs) == 1
    assert queued_jobs[0].kind == "process_item"
    queued_item = fixture.ingest.get_item(str(queued_jobs[0].payload["raw_item_id"]))
    assert queued_item == focus_item


@pytest.mark.parametrize("status", [BriefStatus.COLLECTED, BriefStatus.PREPROCESSED, BriefStatus.PROCESSING])
def test_process_item_resumes_existing_brief(fixture: PipelineFixture, status: BriefStatus) -> None:
    fixture.enqueue_collect()
    fixture.run(WorkerKind.COLLECTOR)
    process, = fixture.queue.list(status=JobStatus.QUEUED)
    raw_item_id = str(process.payload["raw_item_id"])
    original = fixture.briefs.create(raw_item_id=raw_item_id)
    if status in (BriefStatus.PREPROCESSED, BriefStatus.PROCESSING):
        fixture.briefs.advance(original.id, BriefStatus.PREPROCESSED)
    if status == BriefStatus.PROCESSING:
        fixture.briefs.advance(original.id, BriefStatus.PROCESSING)

    assert fixture.run(WorkerKind.LOCAL).status == JobStatus.SUCCEEDED
    draft, = fixture.queue.list(status=JobStatus.QUEUED)
    assert draft.idempotency_key == f"draft:{original.id}:rev0"
    assert fixture.briefs.progress(original.id).status == BriefStatus.PROCESSING


def test_revision_loop_recovers_open_revision_and_enforces_limit(fixture: PipelineFixture) -> None:
    original = fixture.process_to_draft_job()
    fixture.run(WorkerKind.GEMINI)
    brief_id = str(original.payload["brief_id"])
    reviewer = ReviewService(fixture.queue.database, clock=fixture.clock)
    for revision in (0, 1, 2):
        reason = f"Fake review reason {revision}"
        reviewer.decide(brief_id, ReviewInput(action="REQUEST_REVISION", reason=reason, expected_revision=revision))
        if revision == 0:
            # Simulate a restart after advancing but before writing the revision job.
            fixture.briefs.advance(brief_id, BriefStatus.PROCESSING)
        restarted = Pipeline(fixture.queue, fixture.deps)
        restarted.watch_revisions()
        restarted.watch_revisions()
        if revision == 2:
            assert fixture.queue.list(status=JobStatus.QUEUED) == []
        else:
            progress = fixture.briefs.progress(brief_id)
            assert (progress.status, progress.revision_count) == (BriefStatus.PROCESSING, revision + 1)
            assert asyncio.run(restarted.draft_brief(original)) is None
            job = fixture.run(WorkerKind.GEMINI)
            assert job.idempotency_key == f"draft:{brief_id}:rev{revision + 1}"
            assert job.payload["feedback"] == reason
            assert fixture.ai.calls[-1].input["feedback"] == reason
    assert fixture.briefs.progress(brief_id).status == BriefStatus.REVIEW_FAILED
    assert len(fixture.ai.calls) == 3
    assert len([job for job in fixture.queue.list() if job.kind == "draft_brief"]) == 3


def test_connector_error_records_diagnostic_and_honors_server_delay(fixture: PipelineFixture) -> None:
    fixture.connector.failure = HttpConnectorError(
        "Fake endpoint requested backoff.", status=429, retry_after_seconds=30, rate_limit_reached=True,
    )
    original = fixture.enqueue_collect()
    failed = fixture.run(WorkerKind.COLLECTOR)
    assert failed.id == original.id
    assert (failed.status, failed.last_error) == (JobStatus.QUEUED, JobError.ERROR)
    health, = fixture.operations.connector_health()
    assert health.status == ConnectorState.UNAVAILABLE
    assert "Fake endpoint requested backoff." in str(health.last_error)
    assert len(fixture.queue.list()) == 1

    fixture.clock.now = failed.available_at
    fixture.connector.failure = None
    assert fixture.run(WorkerKind.COLLECTOR).status == JobStatus.QUEUED
    assert len(fixture.connector.calls) == 1
    fixture.clock.now = health.checked_at + timedelta(seconds=30)
    assert fixture.run(WorkerKind.COLLECTOR).status == JobStatus.SUCCEEDED
    assert len(fixture.connector.calls) == 2


def test_invalid_draft_retries_and_goes_dead(fixture: PipelineFixture) -> None:
    fixture.ai.valid = False
    draft = fixture.process_to_draft_job()
    for attempt in range(1, 5):
        failed = fixture.run(WorkerKind.GEMINI)
        assert failed.last_error == JobError.ERROR
        assert failed.attempt_count == attempt
        assert failed.status == (JobStatus.QUEUED if attempt < 4 else JobStatus.DEAD)
        fixture.clock.now = failed.available_at
    assert fixture.briefs.progress(str(draft.payload["brief_id"])).status == BriefStatus.PROCESSING


def test_gemini_quota_exhaustion_pauses_worker(fixture: PipelineFixture) -> None:
    fixture.ai.status = AIStatus.QUOTA_EXHAUSTED
    fixture.process_to_draft_job()
    failed = fixture.run(WorkerKind.GEMINI)
    assert failed.last_error == JobError.QUOTA_EXHAUSTED
    fixture.clock.now = failed.available_at
    assert fixture.queue.claim(WorkerKind.GEMINI, "fake-worker") is None


def test_runtime_modules_do_not_import_review_or_alert_services() -> None:
    backend = Path(__file__).resolve().parents[1]
    for package in ("pipeline", "scheduler"):
        for module in (backend / "hunter" / package).glob("*.py"):
            imports: list[str] = []
            for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imports.extend(alias.name for alias in node.names)
            assert all("review" not in name and "telegram" not in name and "alert" not in name for name in imports)
