from enum import StrEnum
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from .common import Model, NonEmpty, PublicUrl, UtcDatetime
from .sources import MetricSnapshot

Score = Annotated[float, Field(ge=0, le=100)]


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class BriefStatus(StrEnum):
    COLLECTED = "COLLECTED"
    PREPROCESSED = "PREPROCESSED"
    PROCESSING = "PROCESSING"
    PENDING_CLAUDE_REVIEW = "PENDING_CLAUDE_REVIEW"
    APPROVED_BY_CLAUDE = "APPROVED_BY_CLAUDE"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    REJECTED_BY_CLAUDE = "REJECTED_BY_CLAUDE"
    REVIEW_FAILED = "REVIEW_FAILED"


class HandoffStatus(StrEnum):
    NOT_HANDED_OFF = "NOT_HANDED_OFF"
    SELECTED = "SELECTED"
    SENT = "SENT"
    SEND_FAILED = "SEND_FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class BriefContent(Model):
    """Draftable product fields, with optional provenance and scoring detail."""

    title_vi: NonEmpty
    original_title: NonEmpty
    content_type: NonEmpty
    platform: NonEmpty
    original_language: NonEmpty
    published_at: UtcDatetime | None
    discovered_at: UtcDatetime
    creator: NonEmpty | None
    summary_vi: NonEmpty
    why_notable: NonEmpty
    virality_score: Score
    relevance_score: Score
    credibility: Score
    priority: Priority
    original_url: PublicUrl
    related_urls: list[PublicUrl]
    engagement_metrics: MetricSnapshot | None
    metrics_snapshot_at: UtcDatetime | None
    verification_level: NonEmpty
    risks_and_notes: list[NonEmpty]
    suggested_formats: list[NonEmpty]
    metadata_only: bool = False
    metadata_note_vi: NonEmpty | None = None
    score_explanation: NonEmpty | None = None

    @field_validator("summary_vi")
    @classmethod
    def validate_summary_length(cls, summary: str) -> str:
        if not 50 <= len(summary.split()) <= 100:
            raise ValueError("The Vietnamese summary must contain 50–100 whitespace-delimited words")
        return summary

    @model_validator(mode="after")
    def validate_provenance(self) -> "BriefContent":
        if self.metadata_only and self.metadata_note_vi is None:
            raise ValueError("A Vietnamese disclosure is required for a metadata-only summary")
        if (
            self.engagement_metrics and self.engagement_metrics.model_dump(exclude_none=True)
            and self.metrics_snapshot_at is None
        ):
            raise ValueError("Collected metrics require a snapshot timestamp")
        return self


class ContentBrief(BriefContent):
    """All 24 product fields plus revision, provenance and persistence metadata."""

    id: NonEmpty
    status: BriefStatus
    handoff_status: HandoffStatus
    revision_count: int = Field(ge=0, le=2)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ReviewAction(StrEnum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class ReviewInput(Model):
    action: ReviewAction
    reason: NonEmpty
    expected_revision: int = Field(ge=0, le=2)


class ReviewDecision(ReviewInput):
    id: int
    brief_id: NonEmpty
    resulting_status: BriefStatus
    created_at: UtcDatetime


class Handoff(Model):
    id: NonEmpty
    brief_id: NonEmpty
    dedup_key: NonEmpty
    status: HandoffStatus
    external_id: NonEmpty | None
    last_error: NonEmpty | None
    selected_at: UtcDatetime
    sent_at: UtcDatetime | None
    acknowledged_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class FeedbackAction(StrEnum):
    GOOD = "good"
    IRRELEVANT = "irrelevant"
    DUPLICATE = "duplicate"
    BAD_SOURCE = "bad-source"


class FeedbackInput(Model):
    brief_id: NonEmpty
    action: FeedbackAction


class Feedback(FeedbackInput):
    id: int
    created_at: UtcDatetime
