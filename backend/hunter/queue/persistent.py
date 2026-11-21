"""A fenced SQLite queue shared by all worker processes."""

from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from hunter.config import QueueSettings
from hunter.db import Database
from hunter.models import (
    AttemptOutcome, Job, JobAttempt, JobError, JobInput, JobLease, JobStatus, WorkerKind,
)
from hunter.models.common import new_id, utc_iso, utcnow
from hunter.state import LeaseLost, NotFound
from hunter.state.jobs import MAX_ATTEMPTS, failed_job_status, validate_job_transition


def _job(row: sqlite3.Row) -> Job:
    values = dict(row)
    values.pop("lease_token")
    values["payload"] = json.loads(values.pop("payload_json"))
    return Job.model_validate(values)


class PersistentQueue:
    def __init__(
        self,
        database: Database,
        settings: QueueSettings | None = None,
        *,
        clock: Callable[[], datetime] = utcnow,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.database = database
        self.settings = settings or QueueSettings()
        self.clock = clock
        self.jitter = jitter

    def enqueue(self, job: JobInput, *, available_at: datetime | None = None) -> Job:
        """Persist a job. The first submission for an idempotency key owns that key."""
        with self.database.transaction() as connection:
            now = utc_iso(self.clock())
            connection.execute(
                """INSERT INTO jobs (
                    id, idempotency_key, kind, worker, queue, payload_json, status,
                    available_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING""",
                (
                    new_id(), job.idempotency_key, job.kind, job.worker, job.queue,
                    json.dumps(job.payload, allow_nan=False),
                    utc_iso(available_at) if available_at is not None else now, now, now,
                ),
            )
            return _job(connection.execute(
                "SELECT * FROM jobs WHERE idempotency_key = ?", (job.idempotency_key,)
            ).fetchone())

    def reclaim_expired(self) -> int:
        """Close expired attempts and release or dead-letter their jobs, preserving counts."""
        with self.database.transaction() as connection:
            return self._reclaim(connection, utc_iso(self.clock()))

    @staticmethod
    def _reclaim(connection: sqlite3.Connection, now: str) -> int:
        expired = connection.execute(
            "SELECT * FROM jobs WHERE status = 'running' AND lease_expires_at <= ?", (now,)
        ).fetchall()
        for row in expired:
            connection.execute(
                """UPDATE job_attempts SET outcome = ?, error_code = ?, finished_at = ?
                   WHERE job_id = ? AND number = ?""",
                (AttemptOutcome.EXPIRED, JobError.LEASE_EXPIRED, now, row["id"], row["attempt_count"]),
            )
            connection.execute(
                """UPDATE jobs SET status = ?, last_error = ?, available_at = ?, updated_at = ?,
                   lease_token = NULL, lease_expires_at = NULL WHERE id = ?""",
                (failed_job_status(row["attempt_count"]), JobError.LEASE_EXPIRED, now, now, row["id"]),
            )
        return len(expired)

    def claim(self, worker: WorkerKind, worker_id: str) -> JobLease | None:
        """Claim the first eligible urgent/normal job within the worker-kind capacity."""
        worker = WorkerKind(worker)
        if not (worker_id := worker_id.strip()):
            raise ValueError("A worker instance identifier is required")
        with self.database.transaction() as connection:
            instant = self.clock()
            now = utc_iso(instant)
            self._reclaim(connection, now)
            quota_blocked = connection.execute(
                """SELECT 1 FROM ai_status WHERE name = ?
                   AND (quota_exhausted = 1 OR status = 'QUOTA_EXHAUSTED')""", (worker,)
            ).fetchone()
            if quota_blocked is not None:
                return None
            running = connection.execute(
                "SELECT count(*) FROM jobs WHERE worker = ? AND status = 'running'", (worker,)
            ).fetchone()[0]
            if running >= getattr(self.settings, worker.value):
                return None
            row = connection.execute(
                """SELECT id, status, attempt_count FROM jobs
                   WHERE worker = ? AND status = 'queued' AND available_at <= ?
                       AND attempt_count < ?
                   ORDER BY CASE queue WHEN 'urgent' THEN 0 ELSE 1 END, available_at, created_at, rowid
                   LIMIT 1""",
                (worker, now, MAX_ATTEMPTS),
            ).fetchone()
            if row is None:
                return None
            validate_job_transition(JobStatus(row["status"]), JobStatus.RUNNING)
            token = new_id()
            expiry = utc_iso(instant + timedelta(seconds=self.settings.lease_seconds))
            claimed = connection.execute(
                """UPDATE jobs SET status = 'running', attempt_count = attempt_count + 1,
                   lease_token = ?, lease_expires_at = ?, updated_at = ?
                   WHERE id = ? RETURNING *""",
                (token, expiry, now, row["id"]),
            ).fetchone()
            connection.execute(
                "INSERT INTO job_attempts (job_id, number, worker_id, created_at) VALUES (?, ?, ?, ?)",
                (row["id"], row["attempt_count"] + 1, worker_id, now),
            )
            return JobLease(job=_job(claimed), token=token)

    @staticmethod
    def _require_lease(
        connection: sqlite3.Connection, job_id: str, token: str, now: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """SELECT * FROM jobs WHERE id = ? AND status = 'running'
               AND lease_token = ? AND lease_expires_at > ?""", (job_id, token, now)
        ).fetchone()
        if row is None:
            raise LeaseLost("The job lease expired or belongs to another claim")
        return row

    def heartbeat(self, job_id: str, token: str) -> Job:
        """Extend a live lease. Expired and superseded tokens cannot mutate the job."""
        with self.database.transaction() as connection:
            instant = self.clock()
            now = utc_iso(instant)
            self._require_lease(connection, job_id, token, now)
            expiry = utc_iso(instant + timedelta(seconds=self.settings.lease_seconds))
            return _job(connection.execute(
                """UPDATE jobs SET lease_expires_at = ?, updated_at = ?
                   WHERE id = ? RETURNING *""", (expiry, now, job_id)
            ).fetchone())

    def complete(self, job_id: str, token: str) -> Job:
        return self._finish(job_id, token, None)

    def fail(self, job_id: str, token: str, error: JobError) -> Job:
        """Record a safe error code and schedule the next attempt or mark the job dead."""
        return self._finish(job_id, token, JobError(error))

    def _finish(self, job_id: str, token: str, error: JobError | None) -> Job:
        with self.database.transaction() as connection:
            instant = self.clock()
            now = utc_iso(instant)
            row = self._require_lease(connection, job_id, token, now)
            attempt = row["attempt_count"]
            status = failed_job_status(attempt) if error else JobStatus.SUCCEEDED
            if error == JobError.POLICY_BLOCKED:
                status = JobStatus.DEAD
            if error == JobError.QUOTA_EXHAUSTED and row["worker"] != WorkerKind.COLLECTOR:
                connection.execute(
                    """INSERT INTO ai_status (name, status, available, quota_exhausted, last_error, checked_at)
                       VALUES (?, 'QUOTA_EXHAUSTED', 0, 1, 'BLOCKED (quota)', ?)
                       ON CONFLICT(name) DO UPDATE SET status = excluded.status, available = 0,
                           quota_exhausted = 1, last_error = excluded.last_error, checked_at = excluded.checked_at
                       WHERE excluded.checked_at >= ai_status.checked_at""", (row["worker"], now)
                )
            validate_job_transition(JobStatus(row["status"]), status)
            available_at = now
            if status == JobStatus.QUEUED:
                delay = self.settings.retry_base_seconds * 2 ** (attempt - 1)
                available_at = utc_iso(instant + timedelta(seconds=delay * (1 + 0.25 * self.jitter())))
            connection.execute(
                """UPDATE job_attempts SET outcome = ?, error_code = ?, finished_at = ?
                   WHERE job_id = ? AND number = ?""",
                (AttemptOutcome.FAILED if error else AttemptOutcome.SUCCEEDED, error, now, job_id, attempt),
            )
            return _job(connection.execute(
                """UPDATE jobs SET status = ?, last_error = ?, available_at = ?, updated_at = ?,
                   lease_token = NULL, lease_expires_at = NULL WHERE id = ? RETURNING *""",
                (status, error, available_at, now, job_id),
            ).fetchone())

    def get(self, job_id: str) -> Job:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise NotFound("Job not found")
            return _job(row)

    def list(self, *, status: JobStatus | None = None, limit: int = 50, offset: int = 0) -> list[Job]:
        with self.database.connection() as connection:
            return [_job(row) for row in connection.execute(
                """SELECT * FROM jobs WHERE (? IS NULL OR status = ?)
                   ORDER BY created_at DESC, id LIMIT ? OFFSET ?""", (status, status, limit, offset)
            )]

    def attempts(self, job_id: str) -> list[JobAttempt]:
        with self.database.transaction(write=False) as connection:
            if connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
                raise NotFound("Job not found")
            return [JobAttempt.model_validate(dict(row)) for row in connection.execute(
                "SELECT * FROM job_attempts WHERE job_id = ? ORDER BY number", (job_id,)
            )]
