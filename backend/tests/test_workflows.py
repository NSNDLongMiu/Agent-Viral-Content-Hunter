import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from pydantic import ValidationError

from hunter.config import PaidAPIForbidden
from hunter.interfaces import AIHealth, SendResult, SendStatus
from hunter.models import BriefStatus, HandoffStatus, RawItem, ReviewAction, ReviewInput, SourceInput
from hunter.models.common import utc_iso
from hunter.services.brief_store import BriefStore
from hunter.services.handoffs import HandoffService
from hunter.services.inbox import InboxService
from hunter.services.monitor import MonitorService
from hunter.services.operations import OperationsService, SettingKey
from hunter.services.retention import RetentionResult, RetentionService
from hunter.services.review import ReviewService
from hunter.state import Conflict, InvalidTransition, NotFound

from .support import DatabaseTestCase, approve, fixture_draft, pending_brief


class FixtureNotifier:
    incurs_cost = False

    def __init__(self) -> None:
        self.keys: list[str] = []
        self.lookup_keys: list[str] = []
        self.acknowledged = False
        self.status = SendStatus.SENT
        self.lookup_status = SendStatus.UNKNOWN

    def send(self, message: str, dedup_key: str) -> SendResult:
        self.keys.append(dedup_key)
        return SendResult(status=self.status, external_id="fixture-receipt" if self.status == SendStatus.SENT else None)

    def lookup_send(self, dedup_key: str) -> SendResult:
        self.lookup_keys.append(dedup_key)
        return SendResult(
            status=self.lookup_status,
            external_id="fixture-receipt" if self.lookup_status == SendStatus.SENT else None,
        )

    def check_ack(self, external_id: str, dedup_key: str) -> bool:
        return self.acknowledged


class WorkflowTests(DatabaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.briefs = BriefStore(self.database, clock=self.clock)
        self.review = ReviewService(self.database, clock=self.clock)

    def test_worker_cannot_skip_or_approve(self) -> None:
        created = self.briefs.create()
        with self.assertRaises(InvalidTransition):
            self.briefs.advance(created.id, BriefStatus.PROCESSING)
        brief = pending_brief(self.briefs, self.clock)
        with self.assertRaises(InvalidTransition):
            self.briefs.advance(brief.id, BriefStatus.APPROVED_BY_CLAUDE)
        with self.assertRaises(sqlite3.IntegrityError), self.database.transaction() as connection:
            connection.execute("UPDATE briefs SET status = 'APPROVED_BY_CLAUDE' WHERE id = ?", (brief.id,))
        self.assertEqual(self.briefs.progress(brief.id).status, BriefStatus.PENDING_CLAUDE_REVIEW)

    def test_approval_requires_reason_and_matching_version(self) -> None:
        brief = pending_brief(self.briefs, self.clock)
        with self.assertRaises(ValidationError):
            request = ReviewInput.model_construct(action=ReviewAction.APPROVE, reason=" \t ", expected_revision=0)
            self.review.decide(brief.id, request)
        with self.assertRaises(Conflict):
            self.review.decide(brief.id, ReviewInput(action="APPROVE", reason="Fixture", expected_revision=1))
        reasoned = ReviewInput(action="APPROVE", reason="  Fixture reason ", expected_revision=0)
        decision = self.review.decide(brief.id, reasoned)
        self.assertEqual(decision.reason, "Fixture reason")
        self.assertEqual(self.review.decide(brief.id, reasoned), decision)
        self.assertEqual(self.briefs.detail(brief.id).review_history, [decision])

    def test_two_revisions_survive_restarts_and_then_fail_review(self) -> None:
        brief = pending_brief(self.briefs, self.clock)
        for revision in range(3):
            reviewed = self.review.decide(brief.id, ReviewInput(
                action="REQUEST_REVISION", reason=f"Test fixture revision {revision}", expected_revision=revision,
            ))
            if revision < 2:
                self.assertEqual(reviewed.resulting_status, BriefStatus.REVISION_REQUIRED)
                self.briefs = BriefStore(self.database, clock=self.clock)
                self.review = ReviewService(self.database, clock=self.clock)
                self.assertEqual(self.briefs.advance(brief.id, BriefStatus.PROCESSING).revision_count, revision + 1)
                self.briefs.submit_draft(brief.id, fixture_draft(self.clock), expected_revision=revision + 1)
        self.assertEqual(reviewed.resulting_status, BriefStatus.REVIEW_FAILED)
        self.assertEqual(self.briefs.progress(brief.id).revision_count, 2)
        with self.assertRaises(InvalidTransition):
            self.briefs.advance(brief.id, BriefStatus.PROCESSING)

    def test_only_approved_content_in_inbox_even_for_p1(self) -> None:
        waiting = pending_brief(self.briefs, self.clock)
        rejected = pending_brief(self.briefs, self.clock)
        self.review.decide(rejected.id, ReviewInput(action="REJECT", reason="Fixture", expected_revision=0))
        approved = pending_brief(self.briefs, self.clock, priority="P2")
        approve(self.review, approved)
        monitor = MonitorService(self.database)
        monitor.record_ai_health(AIHealth(
            name="claude", status="QUOTA_EXHAUSTED", available=False, quota_exhausted=True, checked_at=self.clock(),
        ))
        with self.assertRaises(Conflict):
            approve(self.review, waiting)
        self.assertEqual([brief.id for brief in self.review.pending()], [waiting.id])
        inbox = InboxService(self.database)
        self.assertEqual([brief.id for brief in inbox.list(search="dữ liệu", discovered_after=self.clock())], [approved.id])
        self.assertEqual(inbox.list(priority="P1"), [])
        with self.assertRaises(NotFound):
            inbox.detail(waiting.id)

    def test_handoff_selection_delivery_retry_and_ack(self) -> None:
        brief = pending_brief(self.briefs, self.clock)
        handoffs = HandoffService(self.database, clock=self.clock)
        notifier = FixtureNotifier()
        with self.assertRaises(InvalidTransition):
            handoffs.select_by_admin(brief.id)
        approve(self.review, brief)
        handoff = handoffs.select_by_admin(brief.id)
        self.assertEqual(handoffs.select_by_admin(brief.id), handoff)
        with self.assertRaises(InvalidTransition):
            handoffs.check_ack(handoff.id, notifier)
        notifier.status = SendStatus.FAILED
        self.assertEqual(handoffs.send(handoff.id, "Fixture message", notifier).status, HandoffStatus.SEND_FAILED)
        notifier.status = SendStatus.SENT
        sent = handoffs.send(handoff.id, "Fixture message", notifier)
        self.assertEqual(sent.status, HandoffStatus.SENT)
        self.assertIsNone(sent.acknowledged_at)
        handoffs = HandoffService(self.database, clock=self.clock)
        self.assertEqual(handoffs.send(handoff.id, "Fixture message", notifier), sent)
        self.assertEqual(notifier.keys, [handoff.dedup_key, handoff.dedup_key])
        self.assertEqual(handoffs.check_ack(handoff.id, notifier), sent)
        notifier.acknowledged = True
        self.assertEqual(handoffs.check_ack(handoff.id, notifier).status, HandoffStatus.ACKNOWLEDGED)

    def test_concurrent_handoff_sends_are_serialized_and_paid_adapter_blocked(self) -> None:
        brief = pending_brief(self.briefs, self.clock)
        approve(self.review, brief)
        service = HandoffService(self.database, clock=self.clock)
        handoff = service.select_by_admin(brief.id)
        entered, release = Event(), Event()

        class BlockingFixtureNotifier(FixtureNotifier):
            def send(self, message: str, dedup_key: str) -> SendResult:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("Test fixture send timed out")
                return super().send(message, dedup_key)

        notifier = BlockingFixtureNotifier()
        notifier.incurs_cost = True
        with self.assertRaises(PaidAPIForbidden):
            service.send(handoff.id, "Fixture message", notifier)
        self.assertFalse(entered.is_set())
        notifier.incurs_cost = False
        with ThreadPoolExecutor(max_workers=1) as pool:
            sent = pool.submit(service.send, handoff.id, "Fixture message", notifier)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(Conflict):
                    service.send(handoff.id, "Fixture message", notifier)
            finally:
                release.set()
            self.assertEqual(sent.result().status, HandoffStatus.SENT)
        self.assertEqual(notifier.keys, [handoff.dedup_key])

    def test_uncertain_handoff_uses_lookup_after_restart_without_resending(self) -> None:
        brief = pending_brief(self.briefs, self.clock)
        approve(self.review, brief)
        service = HandoffService(self.database, clock=self.clock)
        handoff = service.select_by_admin(brief.id)
        notifier = FixtureNotifier()
        notifier.status = SendStatus.UNKNOWN
        self.assertEqual(service.send(handoff.id, "Fixture message", notifier).last_error, "UNKNOWN")
        service = HandoffService(self.database, clock=self.clock)
        self.assertEqual(service.send(handoff.id, "Fixture message", notifier).last_error, "UNKNOWN")
        notifier.lookup_status = SendStatus.SENT
        self.assertEqual(service.send(handoff.id, "Fixture message", notifier).status, HandoffStatus.SENT)
        self.assertEqual(notifier.keys, [handoff.dedup_key])
        self.assertEqual(notifier.lookup_keys, [handoff.dedup_key, handoff.dedup_key])

    def test_retention_uses_created_at_and_removes_associated_history(self) -> None:
        sources = OperationsService(self.database, clock=self.clock)
        source = sources.save_source(SourceInput(
            name="Fixture source", connector_id="test-fixture", platform="fixture",
            url="https://example.invalid/feed",
        ), reason="Test fixture")
        raw_id = sources.store_raw_item(RawItem(
            source_id=source.id, source_url="https://example.invalid/item", fetched_at=self.clock(),
        ))
        old = pending_brief(self.briefs, self.clock, raw_item_id=raw_id)
        approve(self.review, old)
        HandoffService(self.database, clock=self.clock).select_by_admin(old.id)
        self.clock.move(days=1)
        fresh = pending_brief(self.briefs, self.clock)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO fingerprints VALUES ('fixture', 'fixture-digest', ?, ?, ?)",
                (raw_id, old.id, utc_iso(self.clock())),
            )
        self.clock.move(days=89)
        retention = RetentionService(self.database, clock=self.clock)
        self.assertEqual(retention.purge(), RetentionResult(briefs=0, fingerprints=0, raw_items=0))
        self.clock.move(microseconds=1)
        self.assertEqual(retention.purge(), RetentionResult(briefs=1, fingerprints=1, raw_items=1))
        with self.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT id FROM briefs").fetchone()[0], fresh.id)
            self.assertEqual(connection.execute("SELECT count(*) FROM brief_revisions").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT count(*) FROM review_decisions").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM handoffs").fetchone()[0], 0)

    def test_audited_source_and_preference_changes_are_reversible(self) -> None:
        operations = OperationsService(self.database, clock=self.clock)
        source = operations.save_source(SourceInput(
            name="Fixture source", connector_id="test-fixture", platform="fixture",
            url="https://example.invalid/feed",
        ), reason="Fixture source addition")
        created = operations.audit()[0]
        removed = operations.remove_source(source.id, reason="Fixture removal")
        with self.assertRaises(NotFound):
            operations.get_source(source.id)
        operations.undo(removed.id, reason="Restore test fixture")
        self.assertEqual(operations.get_source(source.id), source)
        operations.undo(created.id, reason="Undo fixture creation")
        self.assertEqual(operations.list_sources(), [])
        edit = operations.set_preference(SettingKey.P1_THRESHOLD, 89, reason="Test setting")
        self.assertEqual(operations.preferences().p1_threshold, 89)
        operations.undo(edit.id, reason="Undo test setting")
        self.assertEqual(operations.preferences().p1_threshold, 85)
