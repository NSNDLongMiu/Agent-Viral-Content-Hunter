"""Pure scheduling policy with configurable initial intervals and factors."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum


class SourceClass(StrEnum):
    HOT_NEWS = "hot_news"
    TRENDING = "trending"
    PRIORITY_CREATOR = "priority_creator"
    NORMAL = "normal"
    LOW_ACTIVITY = "low_activity"


DEFAULT_INTERVAL_MINUTES: Mapping[SourceClass, int] = {
    SourceClass.HOT_NEWS: 10,
    SourceClass.TRENDING: 30,
    SourceClass.PRIORITY_CREATOR: 60,
    SourceClass.NORMAL: 180,
    SourceClass.LOW_ACTIVITY: 720,
}


def source_class(priority: int) -> SourceClass:
    for minimum, tier in (
        (90, SourceClass.HOT_NEWS),
        (70, SourceClass.TRENDING),
        (50, SourceClass.PRIORITY_CREATOR),
        (20, SourceClass.NORMAL),
    ):
        if priority >= minimum:
            return tier
    return SourceClass.LOW_ACTIVITY


class ScanOutcome(StrEnum):
    EMPTY = "empty"
    NORMAL = "normal"
    STRONG = "strong"


@dataclass(frozen=True)
class ScanPolicy:
    """Initial factors are relative to the configured source class baseline."""

    strong_multiplier: float = 0.5
    minimum_factor: float = 0.5
    empty_multiplier: float = 1.5
    maximum_factor: float = 4.0
    backoff_multiplier: float = 2.0
    maximum_backoff_factor: float = 16.0
    jitter_fraction: float = 0.1
    strong_virality: float = 65.0

    def base_seconds(self, priority: int, preferences: Mapping[str, int]) -> int:
        tier = source_class(priority)
        return 60 * preferences.get(tier, DEFAULT_INTERVAL_MINUTES[tier])

    def _adapted_factor(self, outcomes: Iterable[ScanOutcome]) -> float:
        lower, upper = self.minimum_factor, self.maximum_factor
        multiplier = 1.0
        for outcome in outcomes:
            if outcome == ScanOutcome.NORMAL:
                break
            # Compose the latest steps first. Each step multiplies and clamps.
            # Stop reading old scans as soon as their outcomes cannot change the result.
            multiplier *= self.empty_multiplier if outcome == ScanOutcome.EMPTY else self.strong_multiplier
            lower, upper = (
                max(lower, min(upper, multiplier * self.minimum_factor)),
                max(lower, min(upper, multiplier * self.maximum_factor)),
            )
            if lower == upper:
                return lower
        return max(lower, min(upper, multiplier))

    def delay_seconds(
        self, base_seconds: int, outcomes: Iterable[ScanOutcome] = (), *, failures: int = 0, jitter: float = 0.5,
    ) -> float:
        """Apply successful scan outcomes newest first and jitter with a sample in [0, 1]."""
        if not 0 <= jitter <= 1:
            raise ValueError("Jitter sample must be between 0 and 1")
        factor = self._adapted_factor(outcomes)
        maximum = self.maximum_factor
        if failures:
            factor = max(1.0, factor)
            maximum = self.maximum_backoff_factor
            for _ in range(failures):
                factor *= self.backoff_multiplier
                if factor >= maximum:
                    factor = maximum
                    break
        factor *= 1 + (2 * jitter - 1) * self.jitter_fraction
        return base_seconds * max(self.minimum_factor, min(maximum, factor))
