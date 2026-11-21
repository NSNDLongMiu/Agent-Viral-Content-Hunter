"""Scoring module exports."""

from .rules import (
    DEFAULT_PLATFORM_REFERENCES,
    DEFAULT_SOURCE_RELIABILITY,
    PlatformReference,
    RuleScorer,
    ScoringConfig,
    ScoringThresholds,
    TopicRule,
    extract_platform_key,
    is_news_or_event_claim,
    parse_search_traffic,
)

__all__ = [
    "DEFAULT_PLATFORM_REFERENCES",
    "DEFAULT_SOURCE_RELIABILITY",
    "PlatformReference",
    "RuleScorer",
    "ScoringConfig",
    "ScoringThresholds",
    "TopicRule",
    "extract_platform_key",
    "is_news_or_event_claim",
    "parse_search_traffic",
]
