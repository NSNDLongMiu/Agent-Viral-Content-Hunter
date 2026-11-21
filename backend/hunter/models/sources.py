from enum import StrEnum

from pydantic import Field, JsonValue, model_validator

from .common import Model, NonEmpty, PublicUrl, UtcDatetime


class SourceInput(Model):
    connector_id: NonEmpty
    name: NonEmpty
    url: PublicUrl
    platform: NonEmpty
    enabled: bool = True
    blocked: bool = False
    priority: int = Field(default=0, ge=0)
    reliability: int | None = Field(default=None, ge=0, le=100)
    activity: int | None = Field(default=None, ge=0, le=100)
    content_value: int | None = Field(default=None, ge=0, le=100)


class Source(SourceInput):
    id: NonEmpty
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ConnectorState(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"


class ConnectorHealth(Model):
    connector_id: NonEmpty
    status: ConnectorState
    checked_at: UtcDatetime
    last_success_at: UtcDatetime | None = None
    last_error: NonEmpty | None = None


class MetricSnapshot(Model):
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)


class RawItem(Model):
    source_id: NonEmpty
    source_url: PublicUrl
    external_id: NonEmpty | None = None
    title: NonEmpty | None = None
    creator: NonEmpty | None = None
    published_at: UtcDatetime | None = None
    fetched_at: UtcDatetime
    metrics_snapshot_at: UtcDatetime | None = None
    metrics: MetricSnapshot | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "RawItem":
        if self.metrics and self.metrics.model_dump(exclude_none=True) and self.metrics_snapshot_at is None:
            raise ValueError("Collected metrics require a snapshot timestamp")
        return self
