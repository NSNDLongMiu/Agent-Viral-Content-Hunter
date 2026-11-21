from hunter.db import Database
from hunter.interfaces import AIHealth
from hunter.models import BriefStatus, JobAttempt, JobStatus, QueueName
from hunter.models.common import utc_iso

from .brief_store import BriefProgress


class MonitorService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def record_ai_health(self, health: AIHealth) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO ai_status (name, status, available, last_error, quota_exhausted, checked_at)
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET status = excluded.status,
                       available = excluded.available, last_error = excluded.last_error,
                       quota_exhausted = CASE WHEN ai_status.quota_exhausted = 1
                           AND (excluded.status <> 'OK' OR excluded.available = 0) THEN 1
                           ELSE excluded.quota_exhausted END,
                       checked_at = excluded.checked_at
                   WHERE excluded.checked_at >= ai_status.checked_at""",
                (
                    health.name, health.status, health.available, health.last_error,
                    health.quota_exhausted, utc_iso(health.checked_at),
                ),
            )

    def ai(self) -> list[AIHealth]:
        with self.database.connection() as connection:
            return [AIHealth.model_validate(dict(row)) for row in connection.execute(
                "SELECT * FROM ai_status ORDER BY name"
            )]

    def queues(self) -> dict[QueueName, dict[JobStatus, int]]:
        counts = {queue: dict.fromkeys(JobStatus, 0) for queue in QueueName}
        with self.database.connection() as connection:
            for row in connection.execute("SELECT queue, status, count(*) AS count FROM jobs GROUP BY queue, status"):
                counts[QueueName(row["queue"])][JobStatus(row["status"])] = row["count"]
        return counts

    def errors(self, *, limit: int = 50, offset: int = 0) -> list[JobAttempt]:
        with self.database.connection() as connection:
            return [JobAttempt.model_validate(dict(row)) for row in connection.execute(
                """SELECT * FROM job_attempts WHERE error_code IS NOT NULL
                   ORDER BY finished_at DESC, job_id, number DESC LIMIT ? OFFSET ?""", (limit, offset)
            )]

    def briefs(
        self, *, status: BriefStatus | None = None, limit: int = 50, offset: int = 0,
    ) -> list[BriefProgress]:
        with self.database.connection() as connection:
            return [BriefProgress.model_validate(dict(row)) for row in connection.execute(
                """SELECT id, status, revision_count FROM briefs WHERE (? IS NULL OR status = ?)
                   ORDER BY updated_at DESC, id LIMIT ? OFFSET ?""", (status, status, limit, offset)
            )]
