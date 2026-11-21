"""Persist server retry hints with the connector health observation."""

import re
from datetime import datetime
from math import isfinite

from hunter.interfaces import ConnectorError
from hunter.models import ConnectorHealth

_RETRY_AFTER_LABEL = "\nRetry-After seconds: "
_RETRY_AFTER = re.compile(r"\nRetry-After seconds: ([0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?)$")


def failure_message(error: ConnectorError) -> str:
    # ConnectorError's interface guarantees the message is credential-free.
    message = str(error).strip() or "Connector fetch failed."
    for attribute in ("retry_after_seconds", "retry_after"):
        seconds = getattr(error, attribute, None)
        if type(seconds) is int and 0 <= seconds:
            # Preserve any representable deadline. Larger delays outlast datetime.
            return f"{message}{_RETRY_AFTER_LABEL}{min(seconds, 10**15)}"
        if type(seconds) is float and isfinite(seconds) and 0 <= seconds:
            return f"{message}{_RETRY_AFTER_LABEL}{seconds}"
    return message


def server_wait_remaining(health: ConnectorHealth | None, now: datetime) -> float:
    if health is None or health.last_error is None:
        return 0.0
    match = _RETRY_AFTER.search(health.last_error)
    if match is None:
        return 0.0
    return max(0.0, float(match[1]) - (now - health.checked_at).total_seconds())
