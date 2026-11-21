"""Validate observations and persist each item with its deduplication keys."""

import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import datetime

from hunter.db import Database
from hunter.interfaces import Connector, ConnectorError, FetchLimits
from hunter.models import RawItem, Source
from hunter.models.common import new_id, utc_iso, utcnow
from hunter.services.operations import OperationsService
from hunter.state import NotFound

from .contracts import IngestPort, IngestResult
from .fingerprint import exact_fingerprints
from .normalize import canonical_url, detect_language, normalize_title

_CONTENT_TYPES = {
    "hacker_news": "tin công nghệ / thảo luận",
    "google_trends_vn": "xu hướng tìm kiếm",
    "wikimedia_top": "bài viết bách khoa",
}


def _raw_item(row: sqlite3.Row) -> RawItem:
    return RawItem(
        source_id=row["source_id"], source_url=row["source_url"], external_id=row["external_id"],
        title=row["title"], creator=row["creator"], published_at=row["published_at"],
        fetched_at=row["fetched_at"], metrics_snapshot_at=row["metrics_snapshot_at"],
        metrics=json.loads(row["metrics_json"]) if row["metrics_json"] is not None else None,
        metadata=json.loads(row["metadata_json"]),
    )


def _load_item(connection: sqlite3.Connection, raw_item_id: str) -> RawItem:
    row = connection.execute("SELECT * FROM raw_items WHERE id = ?", (raw_item_id,)).fetchone()
    if row is None:
        raise NotFound("Raw item not found")
    return _raw_item(row)


class Ingestor(IngestPort):
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.clock = clock

    def ingest(self, source: Source, items: Sequence[RawItem]) -> IngestResult:
        result = IngestResult()
        for item in items:
            try:
                with self.database.transaction() as connection:
                    item_id = self._ingest_item(connection, source, item)
            except ValueError:
                result.rejected_count += 1
            else:
                if item_id is None:
                    result.duplicate_count += 1
                else:
                    result.new_item_ids.append(item_id)
        return result

    def _ingest_item(self, connection: sqlite3.Connection, source: Source, item: RawItem) -> str | None:
        if not isinstance(item, RawItem):
            raise ValueError("Expected a raw item")
        # Revalidate a fresh copy, including fields mutated since the connector constructed it.
        item = RawItem.model_validate(item.model_dump(warnings=False))
        if item.source_id != source.id or connection.execute(
            "SELECT 1 FROM sources WHERE id = ? AND removed_at IS NULL", (source.id,),
        ).fetchone() is None:
            raise ValueError("Raw item must belong to the active collection source")

        url = canonical_url(str(item.source_url))
        if item.title is not None:
            item.title = normalize_title(item.title)
        item.metadata.setdefault("platform", source.platform)
        item.metadata.setdefault("language", detect_language(item.title or ""))
        if source.connector_id in _CONTENT_TYPES:
            item.metadata.setdefault("content_type", _CONTENT_TYPES[source.connector_id])
        item.metadata.setdefault("canonical_url", url)
        metadata_json = json.dumps(item.metadata, ensure_ascii=False, allow_nan=False)

        fingerprints = exact_fingerprints(item, url)
        if any(connection.execute(
            "SELECT 1 FROM fingerprints WHERE kind = ? AND digest = ?", fingerprint,
        ).fetchone() for fingerprint in fingerprints):
            return None

        item_id = new_id()
        now = utc_iso(self.clock())
        connection.execute(
            """INSERT INTO raw_items (
                   id, source_id, source_url, external_id, title, creator, published_at, fetched_at,
                   metrics_snapshot_at, metrics_json, metadata_json, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id, item.source_id, str(item.source_url), item.external_id, item.title, item.creator,
                utc_iso(item.published_at) if item.published_at is not None else None, utc_iso(item.fetched_at),
                utc_iso(item.metrics_snapshot_at) if item.metrics_snapshot_at is not None else None,
                item.metrics.model_dump_json() if item.metrics is not None else None, metadata_json, now,
            ),
        )
        connection.executemany(
            "INSERT INTO fingerprints (kind, digest, raw_item_id, created_at) VALUES (?, ?, ?, ?)",
            ((kind, digest, item_id, now) for kind, digest in fingerprints),
        )
        return item_id

    def get_item(self, raw_item_id: str) -> RawItem:
        with self.database.connection() as connection:
            return _load_item(connection, raw_item_id)


async def collect(
    connector: Connector, source: Source, ingestor: IngestPort, operations: OperationsService,
    *, since: datetime | None, limits: FetchLimits,
) -> IngestResult:
    try:
        items = await connector.fetch(since, limits)
    except ConnectorError:
        operations.record_connector_health(connector.health())
        raise
    operations.record_connector_health(connector.health())
    return ingestor.ingest(source, items)
