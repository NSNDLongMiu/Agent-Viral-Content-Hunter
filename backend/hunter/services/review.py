"""The privileged Claude review write path."""

from collections.abc import Callable
from datetime import datetime

from hunter.db import Database
from hunter.interfaces import AIStatus
from hunter.models import ContentBrief, BriefStatus, ReviewDecision, ReviewInput
from hunter.models.common import utc_iso, utcnow
from hunter.state import Conflict
from hunter.state.briefs import review_transition

from .brief_store import BRIEF_SELECT, brief_model, read_brief


class ReviewService:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.clock = clock

    def pending(self, *, limit: int = 50, offset: int = 0) -> list[ContentBrief]:
        with self.database.connection() as connection:
            return [brief_model(row) for row in connection.execute(
                f"""{BRIEF_SELECT} WHERE b.status = 'PENDING_CLAUDE_REVIEW'
                    ORDER BY b.updated_at, b.id LIMIT ? OFFSET ?""", (limit, offset)
            )]

    def decide(self, brief_id: str, request: ReviewInput) -> ReviewDecision:
        """Apply a Claude decision to the exact draft reviewed and persist its reason."""
        request = ReviewInput.model_validate(request.model_dump())
        with self.database.transaction() as connection:
            current = read_brief(connection, brief_id)
            previous = connection.execute(
                "SELECT * FROM review_decisions WHERE brief_id = ? AND expected_revision = ?",
                (brief_id, request.expected_revision),
            ).fetchone()
            if previous is not None:
                if previous["action"] == request.action and previous["reason"] == request.reason:
                    return ReviewDecision.model_validate(dict(previous))
                raise Conflict("A different decision already exists for this revision")
            if current["revision_count"] != request.expected_revision:
                raise Conflict("The decision targets an obsolete revision")
            resulting_status = review_transition(
                BriefStatus(current["status"]), request.action, current["revision_count"]
            )
            health = connection.execute(
                "SELECT status, available, quota_exhausted FROM ai_status WHERE name = 'claude'"
            ).fetchone()
            if health and (health["status"] != AIStatus.OK or not health["available"] or health["quota_exhausted"]):
                raise Conflict("Claude is unavailable. The brief remains pending")
            now = utc_iso(self.clock())
            decision = connection.execute(
                """INSERT INTO review_decisions (
                    brief_id, expected_revision, action, reason, resulting_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?) RETURNING *""",
                (brief_id, request.expected_revision, request.action, request.reason, resulting_status, now),
            ).fetchone()
            connection.execute(
                "UPDATE briefs SET status = ?, updated_at = ? WHERE id = ?", (resulting_status, now, brief_id)
            )
            return ReviewDecision.model_validate(dict(decision))
