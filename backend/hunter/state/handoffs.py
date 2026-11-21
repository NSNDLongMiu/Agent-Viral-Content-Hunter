from hunter.models import HandoffStatus

from . import InvalidTransition

_TRANSITIONS = {
    HandoffStatus.NOT_HANDED_OFF: {HandoffStatus.SELECTED},
    HandoffStatus.SELECTED: {HandoffStatus.SENT, HandoffStatus.SEND_FAILED},
    HandoffStatus.SEND_FAILED: {HandoffStatus.SENT, HandoffStatus.SEND_FAILED},
    HandoffStatus.SENT: {HandoffStatus.ACKNOWLEDGED},
}


def validate_handoff_transition(current: HandoffStatus, target: HandoffStatus) -> None:
    if target not in _TRANSITIONS.get(current, ()):
        raise InvalidTransition(f"Cannot move a handoff from {current} to {target}")
