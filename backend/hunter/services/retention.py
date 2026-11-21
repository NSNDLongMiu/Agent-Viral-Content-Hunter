from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from hunter.config import RetentionSettings
from hunter.db import Database
from hunter.models.common import utc_iso, utcnow


@dataclass(frozen=True)
class RetentionResult:
    briefs: int
    fingerprints: int
    raw_items: int


class RetentionService:
    def __init__(
        self, database: Database, settings: RetentionSettings | None = None,
        *, clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.database = database
        self.settings = settings or RetentionSettings()
        self.clock = clock

    def purge(self) -> RetentionResult:
        """Delete rows strictly older than the cutoff and cascade dependent history."""
        cutoff = utc_iso(self.clock() - timedelta(days=self.settings.days))
        with self.database.transaction() as connection:
            fingerprints = connection.execute(
                """DELETE FROM fingerprints WHERE created_at < ?
                   OR brief_id IN (SELECT id FROM briefs WHERE created_at < ?)
                   OR raw_item_id IN (SELECT id FROM raw_items WHERE created_at < ?)""",
                (cutoff, cutoff, cutoff),
            ).rowcount
            briefs = connection.execute("DELETE FROM briefs WHERE created_at < ?", (cutoff,)).rowcount
            raw_items = connection.execute("DELETE FROM raw_items WHERE created_at < ?", (cutoff,)).rowcount
        return RetentionResult(briefs=briefs, fingerprints=fingerprints, raw_items=raw_items)
