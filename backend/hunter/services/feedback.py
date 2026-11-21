from hunter.db import Database
from hunter.models import BriefStatus, Feedback, FeedbackInput
from hunter.models.common import utc_iso, utcnow
from hunter.state import InvalidTransition

from .brief_store import read_brief


class FeedbackService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def add(self, feedback: FeedbackInput) -> Feedback:
        with self.database.transaction() as connection:
            if read_brief(connection, feedback.brief_id)["status"] != BriefStatus.APPROVED_BY_CLAUDE:
                raise InvalidTransition("Feedback requires an approved brief")
            row = connection.execute(
                "INSERT INTO feedback (brief_id, action, created_at) VALUES (?, ?, ?) RETURNING *",
                (feedback.brief_id, feedback.action, utc_iso(utcnow())),
            ).fetchone()
            return Feedback.model_validate(dict(row))

    def list(
        self, *, brief_id: str | None = None, limit: int = 50, offset: int = 0,
    ) -> list[Feedback]:
        with self.database.connection() as connection:
            return [Feedback.model_validate(dict(row)) for row in connection.execute(
                """SELECT * FROM feedback WHERE (? IS NULL OR brief_id = ?)
                   ORDER BY id DESC LIMIT ? OFFSET ?""", (brief_id, brief_id, limit, offset)
            )]
