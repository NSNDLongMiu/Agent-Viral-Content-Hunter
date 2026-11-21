"""Read-only lookups for pipeline effects and persisted collect history."""

from collections.abc import Generator
from datetime import datetime

from hunter.db import Database
from hunter.models import JobStatus
from hunter.models.common import Model, UtcDatetime, utc_iso
from hunter.services.brief_store import BriefProgress


class CollectScan(Model):
    idempotency_key: str
    status: JobStatus
    created_at: UtcDatetime
    updated_at: UtcDatetime

    @property
    def slot(self) -> int:
        return int(self.idempotency_key.rsplit(":", 1)[-1])


class RevisionCandidate(BriefProgress):
    raw_item_id: str


def brief_for_item(database: Database, raw_item_id: str) -> BriefProgress | None:
    with database.connection() as connection:
        row = connection.execute(
            """SELECT id, status, revision_count FROM briefs
               WHERE raw_item_id = ? ORDER BY created_at, id LIMIT 1""",
            (raw_item_id,),
        ).fetchone()
        return BriefProgress.model_validate(dict(row)) if row else None


def revision_candidates(database: Database) -> list[RevisionCandidate]:
    with database.connection() as connection:
        return [
            RevisionCandidate.model_validate(dict(row))
            for row in connection.execute(
                """SELECT b.id, b.raw_item_id, b.status, b.revision_count FROM briefs AS b
                   WHERE b.raw_item_id IS NOT NULL AND (
                       b.status = 'REVISION_REQUIRED' OR
                       (b.status = 'PROCESSING' AND b.revision_count > 0)
                   ) AND NOT EXISTS (
                       SELECT 1 FROM jobs AS j
                       WHERE j.idempotency_key = 'draft:' || b.id || ':rev' ||
                           (b.revision_count + (b.status = 'REVISION_REQUIRED'))
                   ) ORDER BY b.created_at, b.id"""
            )
        ]


def items_missing_process_job(
    database: Database, source_id: str, *, since: datetime | None = None,
) -> list[str]:
    with database.connection() as connection:
        return [
            row["id"]
            for row in connection.execute(
                """SELECT r.id FROM raw_items AS r WHERE r.source_id = ? AND NOT EXISTS (
                       SELECT 1 FROM jobs WHERE idempotency_key = 'process:' || r.id
                   ) AND NOT EXISTS (
                       SELECT 1 FROM briefs WHERE raw_item_id = r.id
                   ) AND (? IS NULL OR r.created_at > ?)
                   ORDER BY r.fetched_at, r.id""",
                (source_id, utc_iso(since) if since else None, utc_iso(since) if since else None),
            )
        ]


def collect_history(
    database: Database, source_id: str, *, status: JobStatus | None = None,
) -> Generator[CollectScan, None, None]:
    # The key range uses the queue's unique index. The payload check also handles
    # source IDs that happen to share a prefix.
    prefix = f"collect:{source_id}"
    with database.connection() as connection:
        for row in connection.execute(
            """SELECT idempotency_key, status, created_at, updated_at FROM jobs
               WHERE idempotency_key >= ? AND idempotency_key < ? AND kind = 'collect'
                 AND json_extract(payload_json, '$.source_id') = ?
                 AND (? IS NULL OR status = ?)
               ORDER BY created_at DESC, rowid DESC""",
            (f"{prefix}:", f"{prefix};", source_id, status, status),
        ):
            yield CollectScan.model_validate(dict(row))


def scan_items(database: Database, source_id: str, start: datetime, end: datetime) -> list[str]:
    with database.connection() as connection:
        return [
            row["id"]
            for row in connection.execute(
                """SELECT id FROM raw_items WHERE source_id = ? AND created_at BETWEEN ? AND ?""",
                (source_id, utc_iso(start), utc_iso(end)),
            )
        ]


def has_rising_cluster(database: Database, raw_item_ids: list[str]) -> bool:
    with database.connection() as connection:
        return any(
            connection.execute(
                """SELECT 1 FROM trend_cluster_members AS m
                   JOIN trend_clusters AS c ON c.id = m.cluster_id
                   WHERE m.raw_item_id = ? AND c.trend_status = 'rising' LIMIT 1""",
                (raw_item_id,),
            ).fetchone()
            for raw_item_id in raw_item_ids
        )
