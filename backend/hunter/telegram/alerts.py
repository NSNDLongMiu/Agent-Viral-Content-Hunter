"""Eligibility and plain-text rendering for automatic P1 Telegram alerts."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import islice
from urllib.parse import quote

from hunter.models import BriefStatus, ContentBrief, Priority
from hunter.models.common import as_utc

from .messages import is_http_url, limit_text


@dataclass(frozen=True)
class AlertDecision:
    allowed: bool
    reasons: tuple[str, ...]


def should_alert(
    brief: ContentBrief, *, now: datetime, cluster_alerted: bool, duplicate_alert_key: bool,
    material_new_development: bool = False, backlogged: bool = False,
    signals_current: bool | None = None, max_age: timedelta = timedelta(hours=12),
    p1_threshold: float = 85, p1_score: float | None = None,
    verification_satisfied: bool | None = None,
) -> AlertDecision:
    """Evaluate current evidence and alert history supplied by the caller.

    A backlog requires an affirmative signal recheck. The caller may supply a
    P1 score and verification decision from current evidence. The brief's
    virality score and explicit verified labels are the defaults.
    """
    reasons: list[str] = []
    if brief.status != BriefStatus.APPROVED_BY_CLAUDE:
        reasons.append("brief_not_approved")
    if brief.priority != Priority.P1:
        reasons.append("priority_not_p1")
    score = brief.virality_score if p1_score is None else p1_score
    if not p1_threshold <= score <= 100:
        reasons.append("score_below_threshold_or_invalid")
    if not is_http_url(brief.original_url):
        reasons.append("source_url_not_traceable")
    if verification_satisfied is None:
        verification_satisfied = brief.verification_level.strip().casefold() in {
            "verified", "verified (cross-source)",
        }
    if not verification_satisfied:
        reasons.append("verification_not_satisfied")
    age = as_utc(now) - (brief.published_at or brief.discovered_at)
    if age > max_age:
        reasons.append("brief_too_old")
    elif age < timedelta(0):
        reasons.append("brief_timestamp_in_future")
    if signals_current is False or (backlogged and signals_current is not True):
        reasons.append("signals_not_current")
    if cluster_alerted and not material_new_development:
        reasons.append("cluster_already_alerted")
    if duplicate_alert_key:
        reasons.append("duplicate_alert_key")
    return AlertDecision(not reasons, tuple(reasons))


def format_alert(
    brief: ContentBrief, *, dashboard_base_url: str = "http://localhost:3000",
    p1_score: float | None = None,
) -> str:
    """Render the alert for an eligible brief, with a Dashboard detail link."""
    if not is_http_url(dashboard_base_url):
        raise ValueError("A valid Dashboard base URL is required")
    dashboard_url = f"{dashboard_base_url.rstrip('/')}/briefs/{quote(brief.id, safe='')}"
    first_lines = (line.strip() for line in brief.why_notable.splitlines() if line.strip())
    why_notable = "\n".join(islice(first_lines, 2))
    score = brief.virality_score if p1_score is None else p1_score
    return limit_text("\n".join((
        "CẢNH BÁO P1",
        brief.title_vi,
        f"Tóm tắt: {' '.join(brief.summary_vi.split())}",
        f"Điểm: {score:g}/100 | Mức ưu tiên: {brief.priority}",
        f"Nguồn: {brief.original_url}",
        f"Vì sao đáng chú ý: {why_notable}",
        f"\nDashboard: {dashboard_url}",
    )))
