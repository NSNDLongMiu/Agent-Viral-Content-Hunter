"""Tests for the draft gate: filtering weak items and conserving AI quota."""

import asyncio
from datetime import UTC, datetime
import logging
from math import inf, nan
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hunter.api.dependencies import Services
from hunter.api.server import create_server_app
from hunter.config import AuthSettings, RuntimeSettings, Settings, SettingsError, load_settings
from hunter.db import Database
from hunter.interfaces.briefs import ScoringResult
from hunter.models import FocusTag, JobInput, JobStatus, Priority, RawItem, Source, SourceInput, WorkerKind
from hunter.orchestrator import Orchestrator
from hunter.pipeline import Dependencies, DraftGate, ScanStats, register_all
from hunter.queue import PersistentQueue
from hunter.runtime.service import Runtime
from hunter.services.brief_store import BriefStore
from hunter.services.operations import OperationsService

from .support import FixtureClock
from .test_pipeline_handlers import FakeAIWorker, FakeCluster, FakeConnector, FakeIngest
from .test_runtime_server import _eventually


def _scoring_result(
    virality: float = 50.0,
    relevance: float = 40.0,
    credibility: float = 35.0,
    priority: Priority = Priority.P3,
    focus_tags: tuple[FocusTag, ...] = (),
) -> ScoringResult:
    return ScoringResult(
        virality=virality,
        relevance=relevance,
        credibility=credibility,
        priority=priority,
        explanation="Test score",
        focus_tags=list(focus_tags),
    )


# -----------------------------------------------------------------------------
# 1. DraftGate Unit Tests (Validation, Eligibility, Deterministic Selection)
# -----------------------------------------------------------------------------


def test_draft_gate_defaults_and_validation() -> None:
    gate = DraftGate()
    assert gate.min_virality == 60.0
    assert gate.min_relevance == 45.0
    assert gate.max_per_scan == 4
    assert gate.min_focus_relevance == 50.0
    assert gate.max_focus_per_scan == 10

    # Boundary values that must be accepted
    assert DraftGate(min_virality=0.0, min_relevance=0.0, max_per_scan=1)
    assert DraftGate(min_virality=100.0, min_relevance=100.0, max_per_scan=100)

    # Invalid min_virality
    for bad in (-0.1, 100.1, -10.0, nan, inf, -inf, "60", True, False, None):
        with pytest.raises(ValueError):
            DraftGate(min_virality=bad)  # type: ignore[arg-type]

    # Invalid min_relevance
    for bad in (-0.1, 100.1, -5.0, nan, inf, -inf, "45", True, False, None):
        with pytest.raises(ValueError):
            DraftGate(min_relevance=bad)  # type: ignore[arg-type]

    # Invalid max_per_scan
    for bad in (0, -1, -10, 8.5, True, False, "8", None):
        with pytest.raises(ValueError):
            DraftGate(max_per_scan=bad)  # type: ignore[arg-type]

    assert DraftGate(min_focus_relevance=0.0, max_focus_per_scan=1)
    assert DraftGate(min_focus_relevance=100.0)
    for bad in (-0.1, 100.1, nan, inf, -inf, "50", True, None):
        with pytest.raises(ValueError, match="min_focus_relevance"):
            DraftGate(min_focus_relevance=bad)  # type: ignore[arg-type]
    for bad in (0, -1, 6.5, True, "6", None):
        with pytest.raises(ValueError, match="max_focus_per_scan"):
            DraftGate(max_focus_per_scan=bad)  # type: ignore[arg-type]


def test_draft_gate_eligibility_and_boundaries() -> None:
    gate = DraftGate(min_virality=60.0, min_relevance=45.0, max_per_scan=8)

    # P1 is always eligible, regardless of scores
    assert gate.is_eligible(_scoring_result(virality=0.0, relevance=0.0, priority=Priority.P1))
    assert gate.is_eligible(_scoring_result(virality=10.0, relevance=20.0, priority=Priority.P1))

    # P2 is always eligible, regardless of scores
    assert gate.is_eligible(_scoring_result(virality=0.0, relevance=0.0, priority=Priority.P2))
    assert gate.is_eligible(_scoring_result(virality=30.0, relevance=40.0, priority=Priority.P2))

    # P3 requires virality >= min_virality AND relevance >= min_relevance
    # Exact boundary: both meet threshold
    assert gate.is_eligible(_scoring_result(virality=60.0, relevance=45.0, priority=Priority.P3))
    # Above threshold
    assert gate.is_eligible(_scoring_result(virality=75.0, relevance=55.0, priority=Priority.P3))

    # Below boundary on relevance
    assert not gate.is_eligible(_scoring_result(virality=60.0, relevance=44.9, priority=Priority.P3))
    # Below boundary on virality
    assert not gate.is_eligible(_scoring_result(virality=59.9, relevance=45.0, priority=Priority.P3))
    # One very high, the other below threshold
    assert not gate.is_eligible(_scoring_result(virality=100.0, relevance=44.0, priority=Priority.P3))
    assert not gate.is_eligible(_scoring_result(virality=55.0, relevance=100.0, priority=Priority.P3))
    # Both low
    assert not gate.is_eligible(_scoring_result(virality=10.0, relevance=10.0, priority=Priority.P3))


def test_draft_gate_select_deterministic_ranking_capping_and_tie_breaking() -> None:
    gate = DraftGate(min_virality=60.0, min_relevance=45.0, max_per_scan=3)

    candidates = [
        ("item_p3_ineligible", _scoring_result(virality=30.0, relevance=30.0, priority=Priority.P3)),
        ("item_p3_strong", _scoring_result(virality=80.0, relevance=70.0, priority=Priority.P3)),  # sum 150
        ("item_p2_low_sum", _scoring_result(virality=10.0, relevance=10.0, priority=Priority.P2)),  # sum 20
        ("item_p1_mid_sum", _scoring_result(virality=40.0, relevance=40.0, priority=Priority.P1)),  # sum 80
        ("item_p3_mid", _scoring_result(virality=65.0, relevance=50.0, priority=Priority.P3)),     # sum 115
    ]

    # Eligible items are:
    # item_p1_mid_sum (P1)
    # item_p2_low_sum (P2)
    # item_p3_strong (P3, sum 150)
    # item_p3_mid (P3, sum 115)
    # Ranked: P1 first, then P2, then P3 sorted by sum desc -> item_p3_strong, then item_p3_mid.
    # Capped at max_per_scan=3: top 3 selected.
    selected = gate.select(candidates)
    assert selected == ["item_p1_mid_sum", "item_p2_low_sum", "item_p3_strong"]


def test_draft_gate_select_tie_breaking_by_raw_item_id() -> None:
    gate = DraftGate(min_virality=60.0, min_relevance=45.0, max_per_scan=2)

    # Identical priority (P3) and identical score sum (60 + 50 = 110)
    candidates = [
        ("item_z", _scoring_result(virality=60.0, relevance=50.0, priority=Priority.P3)),
        ("item_a", _scoring_result(virality=60.0, relevance=50.0, priority=Priority.P3)),
        ("item_m", _scoring_result(virality=60.0, relevance=50.0, priority=Priority.P3)),
    ]

    # Tied on priority and sum, tie-break by raw_item_id ascending: item_a, item_m, item_z
    # Capped to 2 -> ["item_a", "item_m"]
    selected = gate.select(candidates)
    assert selected == ["item_a", "item_m"]


def test_draft_gate_select_empty_or_all_ineligible() -> None:
    gate = DraftGate()
    assert gate.select([]) == []

    ineligible = [
        ("id1", _scoring_result(virality=20.0, relevance=20.0, priority=Priority.P3)),
        ("id2", _scoring_result(virality=50.0, relevance=40.0, priority=Priority.P3)),
    ]
    assert gate.select(ineligible) == []


def test_focus_eligibility_adds_a_relevance_only_route() -> None:
    gate = DraftGate()
    tags = ("micro_drama",)
    assert not gate.is_eligible(_scoring_result(virality=10.0, relevance=49.9, focus_tags=tags))
    assert gate.is_eligible(_scoring_result(virality=10.0, relevance=50.0, focus_tags=tags))
    assert not gate.is_eligible(_scoring_result(virality=10.0, relevance=50.0))
    assert gate.is_eligible(_scoring_result(virality=60.0, relevance=45.0, focus_tags=tags))
    assert gate.is_eligible(_scoring_result(virality=0.0, relevance=0.0, priority=Priority.P2, focus_tags=tags))


def test_draft_gate_ranks_and_caps_separate_focus_and_general_pools() -> None:
    gate = DraftGate(max_focus_per_scan=3, max_per_scan=2)
    tags = ("phim_ngan", "giai_tri")
    candidates = [
        ("focus-z", _scoring_result(virality=60.0, relevance=50.0, focus_tags=tags)),
        ("general-p3", _scoring_result(virality=80.0, relevance=50.0)),
        ("focus-a", _scoring_result(virality=60.0, relevance=50.0, focus_tags=tags)),
        ("focus-p2", _scoring_result(virality=0.0, relevance=0.0, priority=Priority.P2, focus_tags=tags)),
        ("general-out", _scoring_result(virality=70.0, relevance=50.0)),
        ("focus-low", _scoring_result(virality=10.0, relevance=80.0, focus_tags=tags)),
        ("general-p1", _scoring_result(priority=Priority.P1)),
        ("focus-ineligible", _scoring_result(virality=10.0, relevance=49.9, focus_tags=tags)),
    ]

    expected = ["focus-p2", "focus-a", "focus-z", "general-p1", "general-p3"]
    assert gate.select(candidates) == expected
    assert gate.select(list(reversed(candidates))) == expected


# -----------------------------------------------------------------------------
# 2. Pipeline Integration Tests (Draft Gate, Idempotency, Cluster Scoring)
# -----------------------------------------------------------------------------


class MultiItemConnector:
    id = "multi_item_connector"
    capabilities = ()

    def __init__(self, clock: FixtureClock, items: list[RawItem]) -> None:
        self.clock = clock
        self.items = items
        self.calls: list[datetime | None] = []

    async def fetch(self, since: datetime | None, limits: object) -> list[RawItem]:
        self.calls.append(since)
        return self.items

    def health(self) -> object:
        from hunter.models import ConnectorHealth, ConnectorState
        return ConnectorHealth(
            connector_id=self.id, checked_at=self.clock(),
            status=ConnectorState.AVAILABLE, last_success_at=self.clock(),
        )


class ControlledScorer:
    """Fake scorer assigning controlled scores per raw_item_id."""

    def __init__(self, scores: dict[str, ScoringResult] | None = None) -> None:
        self.scores = scores or {}
        self.scored_items: list[list[RawItem]] = []

    def score(self, items: list[RawItem]) -> ScoringResult:
        self.scored_items.append(items)
        for key in (items[0].external_id, str(items[0].source_url)):
            if key and key in self.scores:
                return self.scores[key]
        return _scoring_result(virality=10.0, relevance=10.0, priority=Priority.P3)


def test_unselected_items_get_no_process_job_and_no_brief(tmp_path: Path) -> None:
    database = Database(tmp_path / "test_gate_unselected.sqlite3")
    database.migrate()
    clock = FixtureClock()
    queue = PersistentQueue(database, clock=clock, jitter=lambda: 0.0)
    operations = OperationsService(database, clock=clock)
    briefs = BriefStore(database, clock=clock)
    source = operations.save_source(SourceInput(
        name="Source A", connector_id="multi_item_connector", platform="test",
        url="https://example.invalid/feed-a",
    ), reason="Test")
    ingest = FakeIngest(operations)
    cluster = FakeCluster(ingest)
    ai = FakeAIWorker(clock)

    # Item 1: weak (P3, 20/20) -> should be skipped
    # Item 2: strong (P3, 70/50) -> should be selected
    weak_item = RawItem(
        source_id=source.id, source_url="https://example.invalid/item-weak",
        external_id="weak_1", fetched_at=clock(), title="Weak item",
    )
    strong_item = RawItem(
        source_id=source.id, source_url="https://example.invalid/item-strong",
        external_id="strong_1", fetched_at=clock(), title="Strong item",
    )
    connector = MultiItemConnector(clock, [weak_item, strong_item])

    scorer = ControlledScorer({
        "https://example.invalid/item-weak": _scoring_result(virality=20.0, relevance=20.0, priority=Priority.P3),
        "https://example.invalid/item-strong": _scoring_result(virality=70.0, relevance=50.0, priority=Priority.P3),
    })
    gate = DraftGate(min_virality=60.0, min_relevance=45.0, max_per_scan=8)

    deps = Dependencies(
        operations=operations, briefs=briefs, ingest=ingest, cluster=cluster, ai_worker=ai,
        build_connector=lambda s: connector, scorer=scorer, gate=gate,
    )
    orchestrator = Orchestrator(queue)
    pipeline = register_all(orchestrator, deps)

    collect_job = queue.enqueue(JobInput(
        kind="collect", worker=WorkerKind.COLLECTOR, idempotency_key=f"collect:{source.id}:0",
        payload={"source_id": source.id},
    ))
    lease = queue.claim(WorkerKind.COLLECTOR, "worker-1")
    assert lease is not None
    asyncio.run(orchestrator._execute(lease))

    # Check that collect succeeded
    assert queue.get(collect_job.id).status == JobStatus.SUCCEEDED

    # Check pipeline scan stats
    stats = pipeline.last_scan[source.id]
    assert stats == ScanStats(collected=2, new=2, eligible=1, selected=1, skipped=1)

    # Check queued jobs: ONLY strong_item should have a process_item job
    queued_jobs = queue.list(status=JobStatus.QUEUED)
    assert len(queued_jobs) == 1
    process_job = queued_jobs[0]
    assert process_job.kind == "process_item"

    # Find the raw item ids in the database
    with database.connection() as connection:
        rows = connection.execute("SELECT id, source_url FROM raw_items ORDER BY id").fetchall()
        assert len(rows) == 2
        id_by_url = {row["source_url"]: row["id"] for row in rows}

    weak_id = id_by_url["https://example.invalid/item-weak"]
    strong_id = id_by_url["https://example.invalid/item-strong"]

    # Verify process_item job payload matches strong item
    assert process_job.payload["raw_item_id"] == strong_id

    # Verify NO brief exists for weak item
    with database.connection() as connection:
        brief_count = connection.execute("SELECT count(*) FROM briefs WHERE raw_item_id = ?", (weak_id,)).fetchone()[0]
        assert brief_count == 0


def test_selected_items_enqueued_exactly_once_when_collect_runs_twice(tmp_path: Path) -> None:
    database = Database(tmp_path / "test_gate_twice.sqlite3")
    database.migrate()
    clock = FixtureClock()
    queue = PersistentQueue(database, clock=clock, jitter=lambda: 0.0)
    operations = OperationsService(database, clock=clock)
    briefs = BriefStore(database, clock=clock)
    source = operations.save_source(SourceInput(
        name="Source B", connector_id="multi_item_connector", platform="test",
        url="https://example.invalid/feed-b",
    ), reason="Test")
    ingest = FakeIngest(operations)
    cluster = FakeCluster(ingest)
    ai = FakeAIWorker(clock)

    weak_item = RawItem(
        source_id=source.id, source_url="https://example.invalid/weak-2",
        external_id="weak_2", fetched_at=clock(), title="Weak 2",
    )
    strong_item = RawItem(
        source_id=source.id, source_url="https://example.invalid/strong-2",
        external_id="strong_2", fetched_at=clock(), title="Strong 2",
    )
    connector = MultiItemConnector(clock, [weak_item, strong_item])

    scorer = ControlledScorer({
        "https://example.invalid/weak-2": _scoring_result(virality=15.0, relevance=15.0, priority=Priority.P3),
        "https://example.invalid/strong-2": _scoring_result(virality=75.0, relevance=60.0, priority=Priority.P3),
    })
    gate = DraftGate(min_virality=60.0, min_relevance=45.0, max_per_scan=8)

    deps = Dependencies(
        operations=operations, briefs=briefs, ingest=ingest, cluster=cluster, ai_worker=ai,
        build_connector=lambda s: connector, scorer=scorer, gate=gate,
    )
    orchestrator = Orchestrator(queue)
    pipeline = register_all(orchestrator, deps)

    # First collect run
    queue.enqueue(JobInput(
        kind="collect", worker=WorkerKind.COLLECTOR, idempotency_key=f"collect:{source.id}:0",
        payload={"source_id": source.id},
    ))
    lease = queue.claim(WorkerKind.COLLECTOR, "worker-1")
    assert lease is not None
    asyncio.run(orchestrator._execute(lease))

    # Process jobs after first run: exactly 1 (for strong_item)
    queued_jobs = [j for j in queue.list() if j.kind == "process_item"]
    assert len(queued_jobs) == 1

    # Second collect run
    queue.enqueue(JobInput(
        kind="collect", worker=WorkerKind.COLLECTOR, idempotency_key=f"collect:{source.id}:1",
        payload={"source_id": source.id},
    ))
    lease2 = queue.claim(WorkerKind.COLLECTOR, "worker-1")
    assert lease2 is not None
    asyncio.run(orchestrator._execute(lease2))

    # Process jobs after second run: STILL exactly 1! Not duplicated, and weak item still skipped!
    all_process_jobs = [j for j in queue.list() if j.kind == "process_item"]
    assert len(all_process_jobs) == 1
    assert all_process_jobs[0].id == queued_jobs[0].id

    # The second scan should report new=0, skipped=0
    assert pipeline.last_scan[source.id].new == 0
    assert pipeline.last_scan[source.id].selected == 0


def test_clustering_happens_before_scoring(tmp_path: Path) -> None:
    """An item that passes ONLY thanks to cluster corroboration is selected."""
    database = Database(tmp_path / "test_cluster_before_score.sqlite3")
    database.migrate()
    clock = FixtureClock()
    queue = PersistentQueue(database, clock=clock, jitter=lambda: 0.0)
    operations = OperationsService(database, clock=clock)
    briefs = BriefStore(database, clock=clock)
    source = operations.save_source(SourceInput(
        name="Source C", connector_id="multi_item_connector", platform="test",
        url="https://example.invalid/feed-c",
    ), reason="Test")
    ingest = FakeIngest(operations)

    # Custom Cluster double that groups item-1 and item-2 together once assign is called
    class CoordinatedCluster:
        def __init__(self, ingest: FakeIngest) -> None:
            self.ingest = ingest
            self.assigned_ids: set[str] = set()

        def assign(self, raw_item_id: str) -> str | None:
            self.assigned_ids.add(raw_item_id)
            return "cluster-1"

        def related_items(self, raw_item_id: str, *, limit: int = 10) -> list[RawItem]:
            # Returns all items assigned so far
            return [self.ingest.get_item(iid) for iid in self.assigned_ids]

    cluster = CoordinatedCluster(ingest)
    ai = FakeAIWorker(clock)

    # Scorer that returns 50 (below 60 gate) if only 1 item in cluster,
    # but returns 70 (above 60 gate) if >= 2 items in cluster!
    class ClusterAwareScorer:
        def score(self, items: list[RawItem]) -> ScoringResult:
            if len(items) >= 2:
                # Corroborated across cluster!
                return _scoring_result(virality=70.0, relevance=50.0, priority=Priority.P3)
            # Alone, score is too weak
            return _scoring_result(virality=50.0, relevance=50.0, priority=Priority.P3)

    item1 = RawItem(
        source_id=source.id, source_url="https://example.invalid/clustered-1",
        fetched_at=clock(), title="Chủ đề cụm 1",
    )
    item2 = RawItem(
        source_id=source.id, source_url="https://example.invalid/clustered-2",
        fetched_at=clock(), title="Chủ đề cụm 2",
    )
    connector = MultiItemConnector(clock, [item1, item2])

    gate = DraftGate(min_virality=60.0, min_relevance=45.0, max_per_scan=8)
    deps = Dependencies(
        operations=operations, briefs=briefs, ingest=ingest, cluster=cluster, ai_worker=ai,
        build_connector=lambda s: connector, scorer=ClusterAwareScorer(), gate=gate,
    )
    orchestrator = Orchestrator(queue)
    pipeline = register_all(orchestrator, deps)

    queue.enqueue(JobInput(
        kind="collect", worker=WorkerKind.COLLECTOR, idempotency_key=f"collect:{source.id}:0",
        payload={"source_id": source.id},
    ))
    lease = queue.claim(WorkerKind.COLLECTOR, "worker-1")
    assert lease is not None
    asyncio.run(orchestrator._execute(lease))

    # Because assign was called for ALL new items FIRST:
    # When scoring runs, related_items returns both items, so virality is 70.0 >= 60.0!
    # Both items should be eligible and selected!
    stats = pipeline.last_scan[source.id]
    assert stats.eligible == 2
    assert stats.selected == 2
    assert stats.skipped == 0
    process_jobs = [j for j in queue.list() if j.kind == "process_item"]
    assert len(process_jobs) == 2


# -----------------------------------------------------------------------------
# 3. Configuration & Runtime Service Tests
# -----------------------------------------------------------------------------


def test_config_defaults_and_env_overrides(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.toml"
    config_file.write_text("[runtime]\nenabled = false\n", encoding="utf-8")

    # Default settings
    settings = load_settings(config_file, environ={})
    assert settings.runtime.draft_min_virality == 60.0
    assert settings.runtime.draft_min_relevance == 45.0
    assert settings.runtime.max_drafts_per_scan == 4
    assert settings.runtime.draft_min_focus_relevance == 50.0
    assert settings.runtime.max_focus_drafts_per_scan == 10

    # Overrides via HUNTER_RUNTIME__...
    overrides = {
        "HUNTER_RUNTIME__DRAFT_MIN_VIRALITY": "72.5",
        "HUNTER_RUNTIME__DRAFT_MIN_RELEVANCE": "55.0",
        "HUNTER_RUNTIME__MAX_DRAFTS_PER_SCAN": "5",
        "HUNTER_RUNTIME__DRAFT_MIN_FOCUS_RELEVANCE": "65.5",
        "HUNTER_RUNTIME__MAX_FOCUS_DRAFTS_PER_SCAN": "3",
    }
    settings_overridden = load_settings(config_file, environ=overrides)
    assert settings_overridden.runtime.draft_min_virality == 72.5
    assert settings_overridden.runtime.draft_min_relevance == 55.0
    assert settings_overridden.runtime.max_drafts_per_scan == 5
    assert settings_overridden.runtime.draft_min_focus_relevance == 65.5
    assert settings_overridden.runtime.max_focus_drafts_per_scan == 3

    # Validation errors on invalid env values
    with pytest.raises(SettingsError):
        load_settings(config_file, environ={"HUNTER_RUNTIME__DRAFT_MIN_VIRALITY": "150.0"})
    with pytest.raises(SettingsError):
        load_settings(config_file, environ={"HUNTER_RUNTIME__DRAFT_MIN_VIRALITY": "-5.0"})
    with pytest.raises(SettingsError):
        load_settings(config_file, environ={"HUNTER_RUNTIME__MAX_DRAFTS_PER_SCAN": "0"})
    for bad in ("-0.1", "100.1", "nan", "inf"):
        with pytest.raises(SettingsError, match="draft_min_focus_relevance"):
            load_settings(config_file, environ={"HUNTER_RUNTIME__DRAFT_MIN_FOCUS_RELEVANCE": bad})
    for bad in ("0", "6.5"):
        with pytest.raises(SettingsError, match="max_focus_drafts_per_scan"):
            load_settings(config_file, environ={"HUNTER_RUNTIME__MAX_FOCUS_DRAFTS_PER_SCAN": bad})


def test_runtime_passes_draft_gate_to_dependencies_and_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    clock = FixtureClock()
    fake_ai = FakeAIWorker(clock)
    settings = Settings(
        database_path=tmp_path / "hunter.sqlite3",
        auth=AuthSettings(claude_service_token="test-claude-token-at-least-32-chars-long"),
        runtime=RuntimeSettings(
            enabled=True, scheduler_tick_seconds=0.01, telegram_poll_seconds=0.01,
            draft_min_virality=75.0, draft_min_relevance=50.0, max_drafts_per_scan=4,
            draft_min_focus_relevance=65.0, max_focus_drafts_per_scan=2,
        ),
    )

    caplog.set_level(logging.INFO)

    def build_connector(source: Source) -> FakeConnector:
        connector = FakeConnector(clock, source)
        connector.item = connector.item.model_copy(update={
            "title": "Short film showcase", "fetched_at": datetime.now(UTC),
        })
        return connector

    services_holder: list[Services] = []
    runtimes: list[Runtime] = []

    def factory(services: Services) -> Runtime:
        services_holder.append(services)
        runtime = Runtime(services, gemini=fake_ai, build_connector=build_connector, environ={})
        runtimes.append(runtime)
        return runtime

    with TestClient(create_server_app(settings, runtime_factory=factory)):
        runtime = runtimes[0]
        # Verify the gate on dependencies received the config values
        gate = runtime.pipeline.deps.gate
        assert gate.min_virality == 75.0
        assert gate.min_relevance == 50.0
        assert gate.max_per_scan == 4
        assert gate.min_focus_relevance == 65.0
        assert gate.max_focus_per_scan == 2

        # Add a source so a scan is scheduled and run
        source = runtime.services.operations.save_source(SourceInput(
            name="Logged Runtime Source", platform="fixture", connector_id=FakeConnector.id,
            url="https://example.invalid/logged-runtime-feed",
        ), reason="Test")

        _eventually(lambda: any(
            record.levelno == logging.INFO and f"Scan completed for source {source.id}" in record.message
            for record in caplog.records
        ))
        stats = runtime.pipeline.last_scan[source.id]
        assert stats.collected >= 1
        assert stats.focus_eligible == stats.focus_selected == 1
        message = next(
            record.message for record in caplog.records
            if record.levelno == logging.INFO and f"Scan completed for source {source.id}" in record.message
        )
        assert f"collected={stats.collected}" in message
        assert f"skipped={stats.skipped}" in message
        assert "focus_eligible=1, focus_selected=1" in message
        assert "Short film showcase" not in message
        assert "example.invalid" not in message
