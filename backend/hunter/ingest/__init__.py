"""Public entry points for ingestion and trend clustering."""

from .cluster import ClusterService
from .contracts import ClusterPort, IngestPort, IngestResult
from .service import Ingestor, collect

__all__ = ["ClusterPort", "ClusterService", "IngestPort", "IngestResult", "Ingestor", "collect"]
