"""Contracts shared by the ingest implementation (T7a) and the pipeline (T7b).

Written by the orchestrator so both tasks can be built in parallel. Neither task may change them;
request a change in the final report instead.
"""

from collections.abc import Sequence
from typing import Protocol

from pydantic import Field

from hunter.models.common import Model, NonEmpty
from hunter.models.sources import RawItem, Source


class IngestResult(Model):
    new_item_ids: list[NonEmpty] = Field(default_factory=list)
    duplicate_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)


class IngestPort(Protocol):
    """Normalizes, deduplicates and persists collected items."""

    def ingest(self, source: Source, items: Sequence[RawItem]) -> IngestResult:
        """Store only items that are not duplicates; never raise for a single bad item."""
        ...

    def get_item(self, raw_item_id: str) -> RawItem:
        """Load a stored item, including the metadata added at ingest time."""
        ...


class ClusterPort(Protocol):
    """Groups raw items that talk about the same event or topic."""

    def assign(self, raw_item_id: str) -> str | None:
        """Add the item to a Trend Cluster. Return its cluster id, or None while it stands alone."""
        ...

    def related_items(self, raw_item_id: str, *, limit: int = 10) -> list[RawItem]:
        """The item itself first, then other members of its cluster (evidence for drafting)."""
        ...
