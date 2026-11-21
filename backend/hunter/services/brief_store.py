"""Draft persistence and worker progress. Review decisions use ReviewService."""

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime

from hunter.db import Database
from hunter.models import BriefContent, BriefStatus, ContentBrief, HandoffStatus, ReviewDecision
from hunter.models.common import Model, new_id, utc_iso, utcnow
from hunter.state import InvalidTransition, NotFound
from hunter.state.briefs import worker_transition


class BriefProgress(Model):
    id: str
    status: BriefStatus
    revision_count: int


class BriefDetail(Model):
    brief: ContentBrief
    review_history: list[ReviewDecision]


BRIEF_SELECT = """SELECT b.*, h.status AS handoff_status FROM briefs AS b
                  LEFT JOIN handoffs AS h ON h.brief_id = b.id"""


def read_brief(connection: sqlite3.Connection, brief_id: str) -> sqlite3.Row:
    row = connection.execute(f"{BRIEF_SELECT} WHERE b.id = ?", (brief_id,)).fetchone()
    if row is None:
        raise NotFound("Brief not found")
    return row


def brief_model(row: sqlite3.Row) -> ContentBrief:
    if row["content_json"] is None:
        raise NotFound("The brief has no submitted draft")
    return ContentBrief.model_validate({
        **json.loads(row["content_json"]),
        "id": row["id"],
        "status": row["status"],
        "revision_count": row["revision_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "handoff_status": row["handoff_status"] or HandoffStatus.NOT_HANDED_OFF,
    })


class BriefStore:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.clock = clock

    def create(self, *, raw_item_id: str | None = None) -> BriefProgress:
        with self.database.transaction() as connection:
            now = utc_iso(self.clock())
            brief_id = new_id()
            connection.execute(
                "INSERT INTO briefs (id, raw_item_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (brief_id, raw_item_id, now, now),
            )
            return BriefProgress(id=brief_id, status=BriefStatus.COLLECTED, revision_count=0)

    def advance(self, brief_id: str, target: BriefStatus) -> BriefProgress:
        """Advance worker progress. Use submit_draft to enter pending review."""
        if target == BriefStatus.PENDING_CLAUDE_REVIEW:
            raise InvalidTransition("A complete draft is required to enter pending review")
        with self.database.transaction() as connection:
            row = read_brief(connection, brief_id)
            count = worker_transition(BriefStatus(row["status"]), target, row["revision_count"])
            connection.execute(
                "UPDATE briefs SET status = ?, revision_count = ?, updated_at = ? WHERE id = ?",
                (target, count, utc_iso(self.clock()), brief_id),
            )
            return BriefProgress(id=brief_id, status=target, revision_count=count)

    def submit_draft(self, brief_id: str, draft: BriefContent, *, expected_revision: int) -> ContentBrief:
        """Persist an immutable version and make it available to the Claude review service."""
        with self.database.transaction() as connection:
            row = read_brief(connection, brief_id)
            count = row["revision_count"]
            if count != expected_revision:
                raise InvalidTransition("This draft targets an obsolete revision")
            target = BriefStatus.PENDING_CLAUDE_REVIEW
            worker_transition(BriefStatus(row["status"]), target, count)
            now = utc_iso(self.clock())
            payload = BriefContent.model_validate(draft.model_dump()).model_dump_json()
            connection.execute(
                "INSERT INTO brief_revisions (brief_id, revision, content_json, created_at) VALUES (?, ?, ?, ?)",
                (brief_id, count, payload, now),
            )
            connection.execute(
                "UPDATE briefs SET status = ?, content_json = ?, updated_at = ? WHERE id = ?",
                (target, payload, now, brief_id),
            )
            return brief_model(read_brief(connection, brief_id))

    def progress(self, brief_id: str) -> BriefProgress:
        with self.database.connection() as connection:
            row = read_brief(connection, brief_id)
            return BriefProgress(id=row["id"], status=row["status"], revision_count=row["revision_count"])

    def detail(self, brief_id: str) -> BriefDetail:
        with self.database.transaction(write=False) as connection:
            return BriefDetail(
                brief=brief_model(read_brief(connection, brief_id)),
                review_history=[ReviewDecision.model_validate(dict(row)) for row in connection.execute(
                    "SELECT * FROM review_decisions WHERE brief_id = ? ORDER BY expected_revision", (brief_id,)
                )],
            )
