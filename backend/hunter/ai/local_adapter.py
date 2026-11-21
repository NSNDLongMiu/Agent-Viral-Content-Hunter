"""Availability stub for the host without a local AI runtime."""

from hunter.interfaces import AIResult, AIStatus, AITask
from hunter.models import AIName

from ._adapter import ObservedAdapter, failure

_NO_RUNTIME = "No local AI runtime is installed."


class LocalAdapter(ObservedAdapter):
    name = AIName.LOCAL

    def __init__(self) -> None:
        super().__init__(_NO_RUNTIME)

    async def run(self, task: AITask) -> AIResult:
        return self._observe(failure(AIStatus.UNAVAILABLE, _NO_RUNTIME))
