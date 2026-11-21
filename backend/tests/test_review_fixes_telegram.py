import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hunter.api.app import create_app
from hunter.briefs.drafter import GeminiBriefDrafter, determine_verification_level
from hunter.config import Settings
from hunter.interfaces import ScoringResult, SendStatus
from hunter.models import BriefStatus, ContentBrief, HandoffStatus, RawItem
from hunter.models.common import utcnow
from hunter.runtime.telegram import TelegramRuntime
from hunter.telegram import should_alert

from .support import FixtureClock, approve, fixture_draft, pending_brief
from .test_briefs_drafter import (
    VALID_WHY_NOTABLE, FakeAIWorker, make_test_item, make_test_scores, make_vietnamese_text,
)
from .test_telegram_notifier import _FAKE_ENV, FakeTransport, button_data, fake_callback, fake_ok, fake_sent

_DRAFT_CASES = [
    pytest.param(1, 80.0, True, id="single_source"),
    pytest.param(1, 45.0, False, id="unverified"),
    pytest.param(3, 80.0, True, id="corroborated"),
]


def _evidence(count: int, credibility: float) -> tuple[list[RawItem], ScoringResult]:
    items = [make_test_item().model_copy(update={"source_id": f"fixture-source-{i}"}) for i in range(count)]
    return items, make_test_scores().model_copy(update={"credibility": credibility})


def _approved_brief(label: str) -> ContentBrief:
    clock = FixtureClock()
    return ContentBrief(
        **fixture_draft(clock).model_copy(update={"verification_level": label}).model_dump(),
        id="fixture-brief", status=BriefStatus.APPROVED_BY_CLAUDE, handoff_status=HandoffStatus.NOT_HANDED_OFF,
        revision_count=1, created_at=clock(), updated_at=clock(),
    )


@pytest.mark.parametrize(("count", "credibility", "allowed"), _DRAFT_CASES)
def test_alert_gate_accepts_real_drafter_labels(count: int, credibility: float, allowed: bool) -> None:
    label = determine_verification_level(*_evidence(count, credibility))
    brief = _approved_brief(label)
    decision = should_alert(brief, now=brief.updated_at, cluster_alerted=False, duplicate_alert_key=False)
    assert decision.allowed is allowed
    assert decision.reasons == (() if allowed else ("verification_not_satisfied",))


@pytest.mark.parametrize(("label", "allowed"), [
    ("verified", True), ("verified (cross-source)", True), ("UNVeRIFIED (legacy)", False),
])
def test_alert_verification_is_case_insensitive_and_accepts_legacy_verified(label: str, allowed: bool) -> None:
    brief = _approved_brief(label)
    decision = should_alert(brief, now=brief.updated_at, cluster_alerted=False, duplicate_alert_key=False)
    assert decision.allowed is allowed


@pytest.mark.parametrize(("count", "credibility", "allowed"), _DRAFT_CASES)
def test_approved_draft_reaches_telegram_alert_watcher(
    tmp_path: Path, count: int, credibility: float, allowed: bool,
) -> None:
    fake_worker = FakeAIWorker([{
        "title_vi": "Tiêu đề tiếng Việt dùng để kiểm thử",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Nội dung kiểm thử"],
        "suggested_formats": ["Video ngắn"],
        "metadata_note_vi": "Tóm tắt từ metadata",
    }])
    items, scores = _evidence(count, credibility)
    draft = asyncio.run(GeminiBriefDrafter(fake_worker).draft(items, scores))
    assert draft.verification_level == determine_verification_level(items, scores)
    transport = FakeTransport(fake_sent())
    with TestClient(create_app(Settings(database_path=tmp_path / "hunter.sqlite3"))) as client:
        services = client.app.state.services
        services.operations.set_preference("telegram_enabled", True, reason="Test fixture")
        entry = services.briefs.create()
        services.briefs.advance(entry.id, BriefStatus.PREPROCESSED)
        services.briefs.advance(entry.id, BriefStatus.PROCESSING)
        pending = services.briefs.submit_draft(entry.id, draft, expected_revision=0)
        approve(services.review, pending)
        TelegramRuntime(services, transport=transport, environ=_FAKE_ENV).alert()
        assert [method for method, _ in transport.calls] == (["sendMessage"] if allowed else [])


def test_lost_telegram_response_recovers_from_callback_without_resending(tmp_path: Path) -> None:
    transport = FakeTransport(TimeoutError("Fixture lost send response"))
    with TestClient(create_app(Settings(database_path=tmp_path / "hunter.sqlite3"))) as client:
        services = client.app.state.services
        services.operations.set_preference("telegram_enabled", True, reason="Test fixture")
        runtime = TelegramRuntime(services, transport=transport, environ=_FAKE_ENV)
        notifier = runtime.notifier()
        assert notifier is not None
        clock = FixtureClock()
        clock.now = utcnow()
        brief = pending_brief(services.briefs, clock)
        approve(services.review, brief)
        handoff = services.handoffs.select_by_admin(brief.id)
        failed = services.handoffs.send(handoff.id, "Fixture handoff", notifier)
        assert failed.status == HandoffStatus.SEND_FAILED and failed.last_error == SendStatus.UNKNOWN
        assert notifier.lookup_send(handoff.dedup_key).status == SendStatus.UNKNOWN
        assert not notifier.check_ack("1234", handoff.dedup_key)
        assert services.handoffs.send(handoff.id, "Fixture retry", notifier).status == HandoffStatus.SEND_FAILED

        data = button_data(transport)
        transport.responses.append(fake_ok([
            fake_callback(20, data, chat_id=-7),
            fake_callback(21, "h:" + "0" * 48),
        ]))
        runtime.poll()
        assert services.handoffs.get(handoff.id).status == HandoffStatus.SEND_FAILED
        assert notifier.lookup_send(handoff.dedup_key).status == SendStatus.UNKNOWN
        assert not notifier.check_ack("1234", handoff.dedup_key)

        transport.responses.extend((fake_ok([fake_callback(22, data)]), fake_ok(True), fake_ok(True)))
        # Reopen the ledger to exercise reconciliation from durable state.
        restarted = TelegramRuntime(services, transport=transport, environ=_FAKE_ENV)
        restarted.poll()
        assert transport.calls[2] == ("getUpdates", {
            "offset": 22, "limit": 20, "timeout": 0, "allowed_updates": ["callback_query", "message"],
        })
        assert notifier.lookup_send(handoff.dedup_key).status == SendStatus.SENT
        assert notifier.check_ack("1234", handoff.dedup_key)
        recovered = services.handoffs.get(handoff.id)
        assert recovered.status == HandoffStatus.ACKNOWLEDGED and recovered.external_id == "1234"
        assert recovered.sent_at is not None and recovered.acknowledged_at is not None
        assert [method for method, _ in transport.calls] == [
            "sendMessage", "getUpdates", "getUpdates", "answerCallbackQuery", "editMessageReplyMarkup",
        ]
