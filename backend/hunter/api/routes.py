"""Typed routes shared with the dashboard and the Claude leader."""

import sqlite3
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import JsonValue

from hunter.briefs.render import to_json, to_markdown
from hunter.config import BudgetSettings, QueueSettings, RetentionSettings
from hunter.interfaces import AIHealth, Notifier
from hunter.models import (
    BriefStatus, ConnectorHealth, ContentBrief, Feedback, FeedbackInput, Handoff, HandoffStatus,
    Job, JobAttempt, JobStatus, Priority, QueueName, ReviewDecision, ReviewInput, Source, SourceInput,
)
from hunter.models.briefs import AIFeasibility, FocusTag
from hunter.models.common import Model, NonEmpty, UtcDatetime
from hunter.services.brief_store import BriefDetail, BriefProgress
from hunter.services.operations import AuditRecord, DashboardSettings, SettingKey
from hunter.state import NotFound
from hunter.telegram.messages import format_handoff

from .auth import require_claude
from .dependencies import Backend, Page, Services

_RESPONSES = {
    404: {"description": "Resource not found"},
    409: {"description": "The operation conflicts with persisted state"},
}


def _dashboard_router(name: str) -> APIRouter:
    """Dashboard routes have no login; `local_guard` limits them to this machine."""
    return APIRouter(prefix=f"/{name}", tags=[name], responses=_RESPONSES)


health = APIRouter(tags=["health"])
briefs = _dashboard_router("briefs")
review = APIRouter(
    prefix="/review", tags=["review"], dependencies=[Depends(require_claude)],
    responses={**_RESPONSES, 401: {"description": "Valid Claude leader service token required"}},
)
jobs = _dashboard_router("jobs")
sources = _dashboard_router("sources")
handoffs = _dashboard_router("handoffs")
feedback = _dashboard_router("feedback")
settings = _dashboard_router("settings")
monitor = _dashboard_router("monitor")


class HealthResponse(Model):
    status: Literal["ok"] = "ok"


@health.get("/health", responses={503: {"description": "SQLite is unavailable"}})
def health_check(backend: Backend) -> HealthResponse:
    """Check that the migrated local database can be read."""
    try:
        with backend.database.connection() as connection:
            connection.execute("SELECT max(version) FROM schema_migrations").fetchone()
    except sqlite3.Error:
        raise HTTPException(503, "Database unavailable") from None
    return HealthResponse()


@briefs.get("/inbox")
def inbox(
    backend: Backend, page: Page, priority: Priority | None = None, platform: str | None = None,
    content_type: str | None = None, discovered_after: UtcDatetime | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    ai_feasibility: AIFeasibility | None = None, focus_tag: FocusTag | None = None,
) -> list[ContentBrief]:
    """List only Claude-approved briefs with optional discovery filters."""
    return backend.inbox.list(
        priority=priority, platform=platform, content_type=content_type,
        discovered_after=discovered_after, search=search, ai_feasibility=ai_feasibility,
        focus_tag=focus_tag, **page.model_dump(),
    )


@briefs.get("/{brief_id}")
def brief_detail(brief_id: str, backend: Backend) -> BriefDetail:
    """Get an approved brief and its review history."""
    return backend.inbox.detail(brief_id)


@briefs.get(
    "/{brief_id}/export/{format}", response_class=Response,
    responses={200: {"content": {
        "text/markdown": {"schema": {"type": "string"}},
        "application/json": {"schema": {"$ref": "#/components/schemas/ContentBrief"}},
    }}},
)
def export_brief(brief_id: str, format: Literal["md", "json"], backend: Backend) -> Response:
    """Render an approved brief as Markdown or JSON."""
    brief = backend.inbox.detail(brief_id).brief
    if format == "md":
        return Response(to_markdown(brief), media_type="text/markdown")
    return Response(to_json(brief), media_type="application/json")


@review.get("/pending")
def pending_reviews(backend: Backend, page: Page) -> list[ContentBrief]:
    """List pending drafts, oldest first, for Claude."""
    return backend.review.pending(**page.model_dump())


@review.get("/{brief_id}")
def pending_review(brief_id: str, backend: Backend) -> ContentBrief:
    """Read a single pending draft for Claude."""
    brief = backend.briefs.detail(brief_id).brief
    if brief.status != BriefStatus.PENDING_CLAUDE_REVIEW:
        raise NotFound("Pending brief not found")
    return brief


@review.post("/{brief_id}/decision")
def decide_review(brief_id: str, data: ReviewInput, backend: Backend) -> ReviewDecision:
    """Record a reasoned Claude decision on a specific revision."""
    return backend.review.decide(brief_id, data)


@jobs.get("")
def list_jobs(backend: Backend, page: Page, status: JobStatus | None = None) -> list[Job]:
    return backend.queue.list(status=status, **page.model_dump())


@jobs.get("/{job_id}")
def get_job(job_id: str, backend: Backend) -> Job:
    return backend.queue.get(job_id)


@jobs.get("/{job_id}/attempts")
def job_attempts(job_id: str, backend: Backend) -> list[JobAttempt]:
    return backend.queue.attempts(job_id)


class ReasonInput(Model):
    reason: NonEmpty


class SourceChange(ReasonInput):
    source: SourceInput


@sources.get("")
def list_sources(backend: Backend, page: Page) -> list[Source]:
    return backend.operations.list_sources(**page.model_dump())


@sources.post("", status_code=201)
def add_source(data: SourceChange, backend: Backend) -> Source:
    return backend.operations.save_source(data.source, reason=data.reason)


@sources.get("/health")
def connector_health(backend: Backend) -> list[ConnectorHealth]:
    return backend.operations.connector_health()


@sources.get("/{source_id}")
def get_source(source_id: str, backend: Backend) -> Source:
    return backend.operations.get_source(source_id)


@sources.put("/{source_id}")
def replace_source(source_id: str, data: SourceChange, backend: Backend) -> Source:
    return backend.operations.save_source(data.source, source_id=source_id, reason=data.reason)


@sources.post("/{source_id}/remove")
def remove_source(source_id: str, data: ReasonInput, backend: Backend) -> AuditRecord:
    return backend.operations.remove_source(source_id, reason=data.reason)


class HandoffSelection(Model):
    brief_id: NonEmpty


def _notifier(backend: Services) -> Notifier:
    notifier = backend.runtime_notifier() if backend.runtime_notifier else backend.notifier
    if notifier is None:
        raise HTTPException(501, "Telegram is unavailable. Enable runtime and Telegram and configure its credentials.")
    return notifier


@handoffs.get("")
def list_handoffs(
    backend: Backend, page: Page, status: HandoffStatus | None = None,
) -> list[Handoff]:
    return backend.handoffs.list(status=status, **page.model_dump())


@handoffs.post("")
def select_handoff(data: HandoffSelection, backend: Backend) -> Handoff:
    """Record admin selection for an approved brief and return its durable handoff."""
    return backend.handoffs.select_by_admin(data.brief_id)


@handoffs.get("/{handoff_id}")
def get_handoff(handoff_id: str, backend: Backend) -> Handoff:
    return backend.handoffs.get(handoff_id)


@handoffs.post("/{handoff_id}/send", responses={501: {"description": "Telegram is unavailable"}})
def send_handoff(handoff_id: str, backend: Backend) -> Handoff:
    """Send or reconcile a selected handoff using its stable deduplication key."""
    notifier = _notifier(backend)
    handoff = backend.handoffs.get(handoff_id)
    brief = backend.inbox.detail(handoff.brief_id).brief
    url = f"{backend.settings.runtime.dashboard_url}/briefs/{quote(brief.id, safe='')}"
    return backend.handoffs.send(handoff_id, format_handoff(brief, url), notifier)


@handoffs.post(
    "/{handoff_id}/check-ack",
    responses={501: {"description": "Telegram is unavailable"}},
)
def check_ack(handoff_id: str, backend: Backend) -> Handoff:
    """Read the acknowledgement state recorded by the Telegram poller."""
    _notifier(backend)
    return backend.handoffs.get(handoff_id)


@feedback.get("")
def list_feedback(backend: Backend, page: Page, brief_id: str | None = None) -> list[Feedback]:
    return backend.feedback.list(brief_id=brief_id, **page.model_dump())


@feedback.post("", status_code=201)
def add_feedback(data: FeedbackInput, backend: Backend) -> Feedback:
    return backend.feedback.add(data)


class PublicSettings(Model):
    preferences: DashboardSettings
    budget: BudgetSettings
    queue: QueueSettings
    retention: RetentionSettings


class SettingChange(ReasonInput):
    value: JsonValue


@settings.get("")
def get_settings(backend: Backend) -> PublicSettings:
    """Read dashboard preferences and the effective startup policy."""
    return PublicSettings(
        preferences=backend.operations.preferences(), budget=backend.settings.budget,
        queue=backend.settings.queue, retention=backend.settings.retention,
    )


@settings.get("/audit")
def audit_log(backend: Backend, page: Page) -> list[AuditRecord]:
    return backend.operations.audit(**page.model_dump())


@settings.post("/audit/{record_id}/undo")
def undo_change(record_id: int, data: ReasonInput, backend: Backend) -> AuditRecord:
    return backend.operations.undo(record_id, reason=data.reason)


@settings.put("/{key}")
def set_preference(key: SettingKey, data: SettingChange, backend: Backend) -> AuditRecord:
    return backend.operations.set_preference(key, data.value, reason=data.reason)


@monitor.get("/ai")
def monitor_ai(backend: Backend) -> list[AIHealth]:
    return backend.monitor.ai()


@monitor.get("/queues")
def monitor_queues(backend: Backend) -> dict[QueueName, dict[JobStatus, int]]:
    return backend.monitor.queues()


@monitor.get("/errors")
def monitor_errors(backend: Backend, page: Page) -> list[JobAttempt]:
    return backend.monitor.errors(**page.model_dump())


@monitor.get("/briefs")
def monitor_briefs(backend: Backend, page: Page, status: BriefStatus | None = None) -> list[BriefProgress]:
    return backend.monitor.briefs(status=status, **page.model_dump())


@monitor.get("/briefs/{brief_id}")
def monitor_brief(brief_id: str, backend: Backend) -> BriefDetail:
    return backend.briefs.detail(brief_id)
