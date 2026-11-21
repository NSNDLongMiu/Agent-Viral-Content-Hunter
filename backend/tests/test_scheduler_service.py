from dataclasses import replace
from pathlib import Path

import pytest

from hunter.connectors.http import HttpConnectorError
from hunter.db import Database
from hunter.models import (
    BriefStatus, ConnectorHealth, ConnectorState, JobError, JobStatus, MetricSnapshot, QueueName, ReviewInput,
    SourceInput, WorkerKind,
)
from hunter.pipeline import Pipeline
from hunter.queue import PersistentQueue
from hunter.scheduler import Scheduler
from hunter.services.brief_store import BriefStore
from hunter.services.operations import OperationsService, SettingKey
from hunter.services.review import ReviewService

from .test_pipeline_handlers import FakeCluster, FakeIngest, PipelineFixture


@pytest.fixture
def fixture(tmp_path: Path) -> PipelineFixture:
    database = Database(tmp_path / "scheduler-fixture.sqlite3")
    database.migrate()
    return PipelineFixture(database)


def restart(fixture: PipelineFixture) -> Scheduler:
    database = Database(fixture.queue.database.path)
    queue = PersistentQueue(database, clock=fixture.clock)
    operations = OperationsService(database, clock=fixture.clock)
    ingest = FakeIngest(operations)
    pipeline = Pipeline(queue, replace(
        fixture.deps, operations=operations, ingest=ingest, cluster=FakeCluster(ingest),
        briefs=BriefStore(database, clock=fixture.clock),
    ))
    return Scheduler(queue, operations, ingest, pipeline.watch_revisions, jitter=lambda key: 0.5)


def test_slot_idempotency_across_ticks_and_restart(fixture: PipelineFixture) -> None:
    scheduler = restart(fixture)
    first, = scheduler.tick(fixture.clock())
    assert first.idempotency_key == f"collect:{fixture.source.id}:0"
    assert first.queue == QueueName.NORMAL
    assert scheduler.tick() == []
    assert restart(fixture).tick() == []
    fixture.run(WorkerKind.COLLECTOR)
    assert restart(fixture).tick() == []

    fixture.clock.move(days=10)
    next_scan, = restart(fixture).tick()
    assert next_scan.idempotency_key == f"collect:{fixture.source.id}:1"
    assert restart(fixture).tick() == []
    fixture.run(WorkerKind.COLLECTOR)
    assert restart(fixture).tick() == []


def test_urgent_routing_and_resource_gate(fixture: PipelineFixture) -> None:
    hot = fixture.operations.save_source(SourceInput(
        name="Fake hot source", connector_id=fixture.source.connector_id, priority=90,
        platform="fake", url="https://example.invalid/fake-hot",
    ), reason="Test fixture")
    for flag in ({"enabled": False}, {"blocked": True}):
        fixture.operations.save_source(SourceInput(
            name="Fake excluded source", connector_id=fixture.source.connector_id, priority=99,
            platform="fake", url=f"https://example.invalid/{next(iter(flag))}", **flag,
        ), reason="Test fixture")

    ticks: list[bool] = []
    loaded = True
    scheduler = Scheduler(
        fixture.queue, fixture.operations, fixture.ingest, ticks.append,
        resource_gate=lambda: not loaded,
    )
    assert scheduler.tick() == []
    assert fixture.queue.list() == []
    loaded = False
    hot_job, normal_job = scheduler.tick()
    assert hot_job.queue == QueueName.URGENT
    assert hot_job.payload == {"source_id": hot.id}
    assert normal_job.queue == QueueName.NORMAL
    assert normal_job.payload == {"source_id": fixture.source.id}
    assert ticks == [False, True]
    lease = fixture.queue.claim(WorkerKind.COLLECTOR, "fake-worker")
    assert lease is not None
    assert lease.job.id == hot_job.id


def test_resource_gate_delays_opening_revisions(fixture: PipelineFixture) -> None:
    draft = fixture.process_to_draft_job()
    fixture.run(WorkerKind.GEMINI)
    brief_id = str(draft.payload["brief_id"])
    ReviewService(fixture.queue.database, clock=fixture.clock).decide(brief_id, ReviewInput(
        action="REQUEST_REVISION", expected_revision=0, reason="Fake review requested revision",
    ))
    scheduler = restart(fixture)
    scheduler.resource_gate = lambda: False
    assert scheduler.tick() == []
    assert fixture.queue.list(status=JobStatus.QUEUED) == []
    assert fixture.briefs.progress(brief_id).status == BriefStatus.REVISION_REQUIRED
    restart(fixture).tick()
    revision, = fixture.queue.list(status=JobStatus.QUEUED)
    assert revision.idempotency_key == f"draft:{brief_id}:rev1"


def test_stored_empty_and_strong_scans_change_schedule_after_restart(fixture: PipelineFixture) -> None:
    fixture.operations.set_preference(
        SettingKey.SCAN_INTERVALS, {"low_activity": 10}, reason="Test fixture",
    )
    restart(fixture).tick()
    # First scan finds a new item with little engagement evidence.
    fixture.run(WorkerKind.COLLECTOR)
    fixture.clock.move(minutes=10)
    restart(fixture).tick()
    # Second scan returns the same item, so ingest observes no new items.
    fixture.run(WorkerKind.COLLECTOR)
    fixture.clock.move(minutes=10)
    assert restart(fixture).tick() == []
    fixture.clock.move(minutes=5)
    assert len(restart(fixture).tick()) == 1
    fixture.connector.item = fixture.connector.item.model_copy(update={
        "source_url": "https://example.invalid/fake-strong",
        "fetched_at": fixture.clock(),
        "metrics": MetricSnapshot(views=10_000_000),
        "metrics_snapshot_at": fixture.clock(),
    })
    fixture.run(WorkerKind.COLLECTOR)
    fixture.clock.move(minutes=7, seconds=29)
    assert restart(fixture).tick() == []
    fixture.clock.move(seconds=1)
    growth, = restart(fixture).tick()
    assert growth.queue == QueueName.URGENT
    assert growth.idempotency_key == f"collect:{fixture.source.id}:3"


@pytest.mark.parametrize("status", [ConnectorState.BLOCKED, ConnectorState.UNAVAILABLE])
def test_health_blocks_new_scans_until_backoff_expires(fixture: PipelineFixture, status: ConnectorState) -> None:
    fixture.operations.set_preference(SettingKey.SCAN_INTERVALS, {"low_activity": 1}, reason="Test fixture")
    fixture.operations.record_connector_health(ConnectorHealth(
        connector_id=fixture.source.connector_id, status=status, checked_at=fixture.clock(),
        last_error="Fake connector status",
    ))
    assert restart(fixture).tick() == []
    fixture.clock.move(seconds=119)
    assert restart(fixture).tick() == []
    fixture.clock.move(seconds=1)
    assert len(restart(fixture).tick()) == 1


def test_historical_health_supplies_last_scan_when_there_is_no_job(fixture: PipelineFixture) -> None:
    fixture.operations.set_preference(SettingKey.SCAN_INTERVALS, {"low_activity": 1}, reason="Test fixture")
    fixture.operations.record_connector_health(ConnectorHealth(
        connector_id=fixture.source.connector_id, status=ConnectorState.AVAILABLE,
        checked_at=fixture.clock(), last_success_at=fixture.clock(),
    ))
    assert restart(fixture).tick() == []
    fixture.clock.move(minutes=1)
    assert len(restart(fixture).tick()) == 1


def test_retry_after_survives_terminal_collect_failure_and_restart(fixture: PipelineFixture) -> None:
    fixture.operations.set_preference(SettingKey.SCAN_INTERVALS, {"low_activity": 1}, reason="Test fixture")
    fixture.connector.failure = HttpConnectorError(
        "Fake endpoint reported a rate limit.", status=429, retry_after_seconds=180, rate_limit_reached=True,
    )
    captured_at = fixture.clock()
    restart(fixture).tick()
    for _ in range(4):
        failed = fixture.run(WorkerKind.COLLECTOR)
        fixture.clock.now = failed.available_at
    assert failed.status == JobStatus.DEAD
    assert failed.last_error == JobError.ERROR
    assert len(fixture.connector.calls) == 1

    fixture.clock.now = captured_at
    fixture.clock.move(seconds=179)
    assert restart(fixture).tick() == []
    fixture.clock.move(seconds=1)
    scheduled, = restart(fixture).tick()
    assert scheduled.idempotency_key == f"collect:{fixture.source.id}:1"
