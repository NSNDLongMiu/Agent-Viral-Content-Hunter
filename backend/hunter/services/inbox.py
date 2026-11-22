from hunter.db import Database
from hunter.models import BriefStatus, ContentBrief, Priority
from hunter.models.briefs import AIFeasibility, FocusTag
from hunter.models.common import UtcDatetime, utc_iso
from hunter.state import NotFound

from .brief_store import BRIEF_SELECT, BriefDetail, BriefStore, brief_model


class InboxService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(
        self, *, priority: Priority | None = None, platform: str | None = None,
        content_type: str | None = None, discovered_after: UtcDatetime | None = None,
        search: str | None = None, ai_feasibility: AIFeasibility | None = None,
        focus_tag: FocusTag | None = None, limit: int = 50, offset: int = 0,
    ) -> list[ContentBrief]:
        """Return only briefs with a persisted Claude approval."""
        cutoff = utc_iso(discovered_after) if discovered_after else None
        with self.database.connection() as connection:
            connection.create_function("casefold", 1, lambda value: (value or "").casefold(), deterministic=True)
            return [brief_model(row) for row in connection.execute(
                f"""{BRIEF_SELECT} WHERE b.status = 'APPROVED_BY_CLAUDE'
                    AND (? IS NULL OR json_extract(b.content_json, '$.priority') = ?)
                    AND (? IS NULL OR json_extract(b.content_json, '$.platform') = ?)
                    AND (? IS NULL OR json_extract(b.content_json, '$.content_type') = ?)
                    AND (? IS NULL OR json_extract(b.content_json, '$.ai_production.feasibility') = ?)
                    AND (? IS NULL OR EXISTS (
                        SELECT 1 FROM json_each(b.content_json, '$.focus_tags') AS tag WHERE tag.value = ?
                    ))
                    AND (? IS NULL OR julianday(json_extract(b.content_json, '$.discovered_at')) >= julianday(?))
                    AND (? IS NULL OR instr(casefold(json_extract(b.content_json, '$.title_vi')), casefold(?)) > 0
                        OR instr(casefold(json_extract(b.content_json, '$.summary_vi')), casefold(?)) > 0)
                    ORDER BY b.updated_at DESC, b.id LIMIT ? OFFSET ?""",
                (priority, priority, platform, platform, content_type, content_type,
                 ai_feasibility, ai_feasibility, focus_tag, focus_tag,
                 cutoff, cutoff, search, search, search, limit, offset),
            )]

    def detail(self, brief_id: str) -> BriefDetail:
        detail = BriefStore(self.database).detail(brief_id)
        if detail.brief.status != BriefStatus.APPROVED_BY_CLAUDE:
            raise NotFound("Approved brief not found")
        return detail
