from collections.abc import Callable
from datetime import datetime, timedelta
from sqlite3 import Connection

from hunter.config import BudgetSettings
from hunter.db import Database
from hunter.interfaces import Notifier, SendResult, SendStatus
from hunter.models import BriefStatus, Handoff, HandoffStatus
from hunter.models.common import new_id, utc_iso, utcnow
from hunter.state import Conflict, IntegrationUnavailable, InvalidTransition, NotFound
from hunter.state.handoffs import validate_handoff_transition

from .brief_store import read_brief

_FIELDS = """id, brief_id, dedup_key, status, external_id, last_error,
             selected_at, sent_at, acknowledged_at, created_at, updated_at"""
_DISPATCH_WINDOW = timedelta(minutes=2)


class HandoffService:
    def __init__(
        self, database: Database, *, clock: Callable[[], datetime] = utcnow,
        budget: BudgetSettings | None = None,
    ) -> None:
        self.database = database
        self.clock = clock
        self.budget = budget or BudgetSettings()

    def select_by_admin(self, brief_id: str) -> Handoff:
        """Record an authenticated admin's selection of an approved brief once."""
        with self.database.transaction() as connection:
            if read_brief(connection, brief_id)["status"] != BriefStatus.APPROVED_BY_CLAUDE:
                raise InvalidTransition("Handoff requires a Claude-approved brief")
            validate_handoff_transition(HandoffStatus.NOT_HANDED_OFF, HandoffStatus.SELECTED)
            now = utc_iso(self.clock())
            handoff_id = new_id()
            connection.execute(
                """INSERT INTO handoffs (id, brief_id, dedup_key, status, selected_at, created_at, updated_at)
                   VALUES (?, ?, ?, 'SELECTED', ?, ?, ?) ON CONFLICT(brief_id) DO NOTHING""",
                (handoff_id, brief_id, f"handoff:{handoff_id}", now, now, now),
            )
            row = connection.execute(
                f"SELECT {_FIELDS} FROM handoffs WHERE brief_id = ?", (brief_id,)
            ).fetchone()
            return Handoff.model_validate(dict(row))

    @staticmethod
    def _get(connection: Connection, handoff_id: str) -> Handoff:
        row = connection.execute(f"SELECT {_FIELDS} FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
        if row is None:
            raise NotFound("Handoff not found")
        return Handoff.model_validate(dict(row))

    def get(self, handoff_id: str) -> Handoff:
        with self.database.connection() as connection:
            return self._get(connection, handoff_id)

    def list(
        self, *, status: HandoffStatus | None = None, limit: int = 50, offset: int = 0,
    ) -> list[Handoff]:
        with self.database.connection() as connection:
            return [Handoff.model_validate(dict(row)) for row in connection.execute(
                f"""SELECT {_FIELDS} FROM handoffs WHERE (? IS NULL OR status = ?)
                    ORDER BY selected_at DESC, id LIMIT ? OFFSET ?""", (status, status, limit, offset)
            )]

    def send(self, handoff_id: str, message: str, notifier: Notifier) -> Handoff:
        """Dispatch a selected handoff under a durable lease and a stable notification key."""
        if not message.strip():
            raise ValueError("A handoff message is required")
        with self.database.transaction() as connection:
            handoff = self._get(connection, handoff_id)
            if handoff.status in (HandoffStatus.SENT, HandoffStatus.ACKNOWLEDGED):
                return handoff
            self.budget.require_allowed(incurs_cost=getattr(notifier, "incurs_cost", None))
            instant = self.clock()
            now = utc_iso(instant)
            token = new_id()
            previous = connection.execute(
                "SELECT dispatch_token FROM handoffs WHERE id = ?", (handoff_id,)
            ).fetchone()
            reconcile = previous["dispatch_token"] is not None or handoff.last_error == SendStatus.UNKNOWN
            claimed = connection.execute(
                """UPDATE handoffs SET dispatch_token = ?, dispatch_expires_at = ?
                   WHERE id = ? AND (dispatch_token IS NULL OR dispatch_expires_at <= ?)""",
                (token, utc_iso(instant + _DISPATCH_WINDOW), handoff_id, now),
            )
            if not claimed.rowcount:
                raise Conflict("Handoff dispatch is already in progress")

        try:
            reported = (
                notifier.lookup_send(handoff.dedup_key) if reconcile
                else notifier.send(message, handoff.dedup_key)
            )
            result = SendResult.model_validate(reported.model_dump())
        except Exception:
            # A raised adapter exception leaves remote delivery uncertain. Persist a
            # safe code and use the same dedup key if the caller tries to reconcile it.
            result = SendResult(status=SendStatus.UNKNOWN)
        with self.database.transaction() as connection:
            now = utc_iso(self.clock())
            target = HandoffStatus.SENT if result.status == SendStatus.SENT else HandoffStatus.SEND_FAILED
            validate_handoff_transition(handoff.status, target)
            sent_at = now if target == HandoffStatus.SENT else None
            error = None if target == HandoffStatus.SENT else result.status
            applied = connection.execute(
                """UPDATE handoffs SET status = ?, external_id = ?, sent_at = ?, last_error = ?,
                   dispatch_token = NULL, dispatch_expires_at = NULL, updated_at = ?
                   WHERE id = ? AND dispatch_token = ?""",
                (target, result.external_id, sent_at, error, now, handoff_id, token),
            )
            if not applied.rowcount:
                raise Conflict("The dispatch lease was superseded")
            return self._get(connection, handoff_id)

    def check_ack(self, handoff_id: str, notifier: Notifier) -> Handoff:
        """Record acknowledgement only when the adapter confirms recipient action."""
        handoff = self.get(handoff_id)
        if handoff.status == HandoffStatus.ACKNOWLEDGED:
            return handoff
        validate_handoff_transition(handoff.status, HandoffStatus.ACKNOWLEDGED)
        if handoff.external_id is None:
            raise InvalidTransition("The handoff has no delivery receipt")
        self.budget.require_allowed(incurs_cost=getattr(notifier, "incurs_cost", None))
        try:
            acknowledged = notifier.check_ack(handoff.external_id, handoff.dedup_key)
        except Exception:
            raise IntegrationUnavailable("Acknowledgement check unavailable") from None
        if acknowledged is True:
            with self.database.transaction() as connection:
                now = utc_iso(self.clock())
                connection.execute(
                    """UPDATE handoffs SET status = 'ACKNOWLEDGED', acknowledged_at = ?, updated_at = ?
                       WHERE id = ? AND status = 'SENT' AND external_id = ?""",
                    (now, now, handoff_id, handoff.external_id),
                )
                return self._get(connection, handoff_id)
        return handoff
