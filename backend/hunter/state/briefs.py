from hunter.models import BriefStatus, ReviewAction

from . import InvalidTransition

MAX_REVISIONS = 2

_WORKER_TRANSITIONS = {
    BriefStatus.COLLECTED: BriefStatus.PREPROCESSED,
    BriefStatus.PREPROCESSED: BriefStatus.PROCESSING,
    BriefStatus.PROCESSING: BriefStatus.PENDING_CLAUDE_REVIEW,
    BriefStatus.REVISION_REQUIRED: BriefStatus.PROCESSING,
}


def worker_transition(current: BriefStatus, target: BriefStatus, revision_count: int) -> int:
    """Validate worker progress and return the current or newly opened revision number."""
    if _WORKER_TRANSITIONS.get(current) != target:
        raise InvalidTransition(f"Cannot move a brief from {current} to {target}")
    if current == BriefStatus.REVISION_REQUIRED:
        if revision_count >= MAX_REVISIONS:
            raise InvalidTransition("The brief has no remaining revisions")
        return revision_count + 1
    return revision_count


def review_transition(current: BriefStatus, action: ReviewAction, revision_count: int) -> BriefStatus:
    """Resolve a Claude decision for the pending revision."""
    if current != BriefStatus.PENDING_CLAUDE_REVIEW:
        raise InvalidTransition("Only a pending brief can be reviewed")
    if action == ReviewAction.REQUEST_REVISION:
        return (
            BriefStatus.REVIEW_FAILED if revision_count >= MAX_REVISIONS
            else BriefStatus.REVISION_REQUIRED
        )
    return {
        ReviewAction.APPROVE: BriefStatus.APPROVED_BY_CLAUDE,
        ReviewAction.REJECT: BriefStatus.REJECTED_BY_CLAUDE,
    }[action]
