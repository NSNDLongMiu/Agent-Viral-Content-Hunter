from hunter.models import JobStatus

from . import InvalidTransition

MAX_RETRIES = 3
MAX_ATTEMPTS = 1 + MAX_RETRIES

_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.RUNNING},
    JobStatus.RUNNING: {JobStatus.QUEUED, JobStatus.SUCCEEDED, JobStatus.DEAD},
}


def validate_job_transition(current: JobStatus, target: JobStatus) -> None:
    if target not in _TRANSITIONS.get(current, ()):
        raise InvalidTransition(f"Cannot move a job from {current} to {target}")


def failed_job_status(attempt_count: int) -> JobStatus:
    return JobStatus.DEAD if attempt_count >= MAX_ATTEMPTS else JobStatus.QUEUED
