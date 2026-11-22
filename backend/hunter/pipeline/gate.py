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
    max_per_scan: int = 4
    min_focus_relevance: float = 50.0
    max_focus_per_scan: int = 10

    def __post_init__(self) -> None:
        for name, value in (
            ("min_virality", self.min_virality),
            ("min_relevance", self.min_relevance),
            ("min_focus_relevance", self.min_focus_relevance),
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            if not (0.0 <= value <= 100.0):
                raise ValueError(f"{name} must be between 0.0 and 100.0")

        for name, limit in (
            ("max_per_scan", self.max_per_scan),
            ("max_focus_per_scan", self.max_focus_per_scan),
        ):
            if not isinstance(limit, int) or isinstance(limit, bool):
                raise ValueError(f"{name} must be an integer")
            if limit < 1:
                raise ValueError(f"{name} must be >= 1")

    def is_eligible(self, result: ScoringResult) -> bool:
        """Apply the priority, general score, and focus relevance criteria."""
        return (
            result.priority in (Priority.P1, Priority.P2)
            or (result.virality >= self.min_virality and result.relevance >= self.min_relevance)
            or (bool(result.focus_tags) and result.relevance >= self.min_focus_relevance)
        )

    def select(self, candidates: Sequence[tuple[str, ScoringResult]]) -> list[str]:
        """Rank and cap eligible candidates in each pool, returning focus items first."""
        eligible = [(item_id, result) for item_id, result in candidates if self.is_eligible(result)]

        def sort_key(candidate: tuple[str, ScoringResult]) -> tuple[int, float, str]:
            item_id, result = candidate
            priority_rank = _PRIORITY_ORDER.get(result.priority, 3)
            score_sum = -(result.virality + result.relevance)
            return (priority_rank, score_sum, item_id)

        ranked = sorted(eligible, key=sort_key)
        focus_ids = [item_id for item_id, result in ranked if result.focus_tags]
        other_ids = [item_id for item_id, result in ranked if not result.focus_tags]
        return focus_ids[: self.max_focus_per_scan] + other_ids[: self.max_per_scan]
