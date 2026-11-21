"""Allowed state transitions for the persistence services."""


class InvalidTransition(ValueError):
    """The requested state change is not allowed."""


class LeaseLost(InvalidTransition):
    """The caller does not hold a live lease for this job."""


class NotFound(LookupError):
    """A requested record does not exist."""


class Conflict(ValueError):
    """The operation conflicts with current persisted state."""


class IntegrationUnavailable(RuntimeError):
    """The configured integration could not perform the requested operation."""
