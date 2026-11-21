from pydantic import Field

from .common import Model, NonEmpty, PublicUrl, UtcDatetime


class TrendCluster(Model):
    id: NonEmpty
    topic: NonEmpty
    source_ids: list[NonEmpty] = Field(default_factory=list)
    detected_at: UtcDatetime
    viral_signals: list[NonEmpty] = Field(default_factory=list)
    trusted_source_ids: list[NonEmpty] = Field(default_factory=list)
    trend_status: NonEmpty
    representative_brief_id: NonEmpty | None = None
    created_at: UtcDatetime


class SeriesEpisode(Model):
    url: PublicUrl
    episode_number: int | None = Field(default=None, ge=1)
    raw_item_id: NonEmpty | None = None


class SeriesGroup(Model):
    id: NonEmpty
    original_title: NonEmpty
    title_vi: NonEmpty | None = None
    genre: NonEmpty | None = None
    plot_summary: NonEmpty | None = None
    creator_or_publisher: NonEmpty | None = None
    episodes: list[SeriesEpisode] = Field(default_factory=list)
    complete: bool | None = None
    usage_rights: NonEmpty | None = None
    created_at: UtcDatetime
