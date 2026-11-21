"""Draft gate: filter and cap collected items before drafting with AI."""

from collections.abc import Sequence
from dataclasses import dataclass
import math

from hunter.interfaces.briefs import ScoringResult
from hunter.models.briefs import Priority

_PRIORITY_ORDER = {
    Priority.P1: 0,
    Priority.P2: 1,
    Priority.P3: 2,
    "P1": 0,
    "P2": 1,
    "P3": 2,
}


@dataclass(frozen=True)
class DraftGate:
    """Filter and rank candidates to prevent spending AI quota on weak items."""

    min_virality: float = 60.0
    min_relevance: float = 45.0
    max_per_scan: int = 8

    def __post_init__(self) -> None:
        for name, value in (("min_virality", self.min_virality), ("min_relevance", self.min_relevance)):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if not (0.0 <= value <= 100.0):
                raise ValueError(f"{name} must be between 0.0 and 100.0")

        if not isinstance(self.max_per_scan, int) or isinstance(self.max_per_scan, bool):
            raise ValueError("max_per_scan must be an integer")
        if self.max_per_scan < 1:
            raise ValueError("max_per_scan must be >= 1")

    def is_eligible(self, result: ScoringResult) -> bool:
        """A scored item is eligible if priority is P1 or P2, or scores meet the threshold."""
        return (
            result.priority in (Priority.P1, Priority.P2)
            or (result.virality >= self.min_virality and result.relevance >= self.min_relevance)
        )

    def select(self, candidates: Sequence[tuple[str, ScoringResult]]) -> list[str]:
        """Return the chosen ids: eligible only, ranked deterministically and capped."""
        eligible = [(item_id, result) for item_id, result in candidates if self.is_eligible(result)]

        def sort_key(candidate: tuple[str, ScoringResult]) -> tuple[int, float, str]:
            item_id, result = candidate
            priority_rank = _PRIORITY_ORDER.get(result.priority, 3)
            score_sum = -(result.virality + result.relevance)
            return (priority_rank, score_sum, item_id)

        ranked = sorted(eligible, key=sort_key)
        return [item_id for item_id, _ in ranked[: self.max_per_scan]]
