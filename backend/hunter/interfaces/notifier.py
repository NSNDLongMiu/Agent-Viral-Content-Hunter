from enum import StrEnum
from typing import Protocol

from pydantic import model_validator

from hunter.models.common import Model, NonEmpty


class SendStatus(StrEnum):
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class SendResult(Model):
    status: SendStatus
    external_id: NonEmpty | None = None

    @model_validator(mode="after")
    def check_receipt(self) -> "SendResult":
        if (self.status == SendStatus.SENT) != (self.external_id is not None):
            raise ValueError("An external receipt is required for SENT and reserved for SENT")
        return self


class Notifier(Protocol):
    """Durable, idempotent delivery and explicit receipt acknowledgement."""

    @property
    def incurs_cost(self) -> bool | None:
        """Report False only for a verified zero-incremental-cost delivery method."""
        ...

    def send(self, message: str, dedup_key: str) -> SendResult:
        """Reuse a successful receipt by key. Return UNKNOWN if delivery cannot be determined.

        A repeated key must never dispatch again after success or ambiguous delivery.
        Only a definitive failure permits sending with the same key again.
        """
        ...

    def lookup_send(self, dedup_key: str) -> SendResult:
        """Look up an uncertain send without dispatching. Missing evidence means UNKNOWN."""
        ...

    def check_ack(self, external_id: str, dedup_key: str) -> bool:
        """Return whether a recipient explicitly acknowledged the specified delivery."""
        ...
