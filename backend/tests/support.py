from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from hunter.db import Database
from hunter.models import BriefContent, BriefStatus, ContentBrief, ReviewInput
from hunter.services.brief_store import BriefStore
from hunter.services.review import ReviewService


class FixtureClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def move(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class DatabaseTestCase(TestCase):
    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.database = Database(Path(directory.name) / "test-fixture.sqlite3")
        self.database.migrate()
        self.clock = FixtureClock()


def fixture_draft(clock: FixtureClock, *, priority: str = "P1") -> BriefContent:
    return BriefContent(
        title_vi="DỮ LIỆU KIỂM THỬ",
        original_title="Test fixture title",
        content_type="fixture",
        platform="fixture",
        original_language="vi",
        published_at=None,
        discovered_at=clock(),
        creator=None,
        summary_vi=" ".join(["dữ liệu kiểm thử"] * 13),
        why_notable="Test fixture only",
        virality_score=90,
        relevance_score=80,
        credibility=70,
        priority=priority,
        original_url="https://example.invalid/test-fixture",
        related_urls=[],
        engagement_metrics=None,
        metrics_snapshot_at=None,
        verification_level="fixture",
        risks_and_notes=[],
        suggested_formats=[],
    )


def pending_brief(
    store: BriefStore, clock: FixtureClock, *, raw_item_id: str | None = None, priority: str = "P1",
) -> ContentBrief:
    brief = store.create(raw_item_id=raw_item_id)
    store.advance(brief.id, BriefStatus.PREPROCESSED)
    store.advance(brief.id, BriefStatus.PROCESSING)
    return store.submit_draft(brief.id, fixture_draft(clock, priority=priority), expected_revision=0)


def approve(service: ReviewService, brief: ContentBrief) -> None:
    service.decide(brief.id, ReviewInput(
        action="APPROVE", reason="Test fixture decision", expected_revision=brief.revision_count,
    ))
