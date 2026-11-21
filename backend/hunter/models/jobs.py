from enum import StrEnum

from pydantic import Field, JsonValue

from .common import Model, NonEmpty, UtcDatetime


class AIName(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    LOCAL = "local"


class WorkerKind(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    GEMINI = "gemini"
    LOCAL = "local"
    COLLECTOR = "collector"


class QueueName(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEAD = "dead"


class JobError(StrEnum):
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_LOST = "AUTH_LOST"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class JobInput(Model):
    idempotency_key: NonEmpty
    kind: NonEmpty
    worker: WorkerKind
    queue: QueueName = QueueName.NORMAL
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class Job(JobInput):
    id: NonEmpty
    status: JobStatus
    attempt_count: int = Field(ge=0)
    available_at: UtcDatetime
    lease_expires_at: UtcDatetime | None
    last_error: JobError | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class JobLease(Model):
    job: Job
    token: NonEmpty = Field(repr=False)


class AttemptOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class JobAttempt(Model):
    job_id: NonEmpty
    number: int = Field(ge=1)
    worker_id: NonEmpty
    created_at: UtcDatetime
    finished_at: UtcDatetime | None
    outcome: AttemptOutcome | None
    error_code: JobError | None
