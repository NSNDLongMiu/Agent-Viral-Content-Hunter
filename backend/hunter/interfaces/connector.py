from collections.abc import Collection
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from hunter.models import ConnectorHealth, RawItem
from hunter.models.common import Model


class ConnectorCapability(StrEnum):
    BROAD_DISCOVERY = "broad_discovery"
    TARGETED_MONITORING = "targeted_monitoring"
    EMERGING_VIRAL = "emerging_viral"
    CROSS_MARKET = "cross_market"
    ACTIVE_RESEARCH = "active_research"


class FetchLimits(Model):
    max_items: int = Field(default=50, gt=0)
    timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)


class ConnectorError(RuntimeError):
    """A real fetch failure. Use a credential-free message and report degraded health."""


class Connector(Protocol):
    """Collects genuine content using authorized, zero-cost access."""

    @property
    def id(self) -> str:
        """Stable identifier shared with Source.connector_id."""
        ...

    @property
    def capabilities(self) -> Collection[ConnectorCapability]:
        """Discovery modes supported by this connector."""
        ...

    async def fetch(self, since: datetime | None, limits: FetchLimits) -> list[RawItem]:
        """Fetch within the given limits. Raise ConnectorError on a failed fetch."""
        ...

    def health(self) -> ConnectorHealth:
        """Report actual connector health and its most recent safe diagnostic."""
        ...
