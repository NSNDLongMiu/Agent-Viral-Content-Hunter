from collections.abc import Sequence
from typing import Protocol

from hunter.models import BriefContent, ContentBrief, Priority, RawItem, ReviewInput
from hunter.models.briefs import Score
from hunter.models.common import Model, NonEmpty


class ScoringResult(Model):
    virality: Score
    relevance: Score
    credibility: Score
    priority: Priority
    explanation: NonEmpty


class Scorer(Protocol):
    """Computes distinct scores and a priority using observed signals."""

    def score(self, items: Sequence[RawItem]) -> ScoringResult:
        """Score the supplied evidence and explain priority and verification requirements."""
        ...


class BriefDrafter(Protocol):
    """Produces validated Vietnamese content for the review workflow."""

    async def draft(
        self, items: Sequence[RawItem], scores: ScoringResult, *, feedback: str | None = None,
    ) -> BriefContent:
        """Draft or revise a brief with evidence and disclose any metadata-only summary."""
        ...


class BriefReviewer(Protocol):
    """Obtains a structured decision from the Claude leader."""

    async def review(self, brief: ContentBrief) -> ReviewInput:
        """Return an action, non-empty reason and the exact revision that was reviewed."""
        ...
