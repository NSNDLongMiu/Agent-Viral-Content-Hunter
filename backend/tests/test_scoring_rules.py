"""Unit tests for RuleScorer."""

from datetime import UTC, datetime, timedelta
import pytest
from pydantic import HttpUrl

from hunter.models.briefs import Priority
from hunter.models.sources import MetricSnapshot, RawItem
from hunter.scoring.rules import (
    DEFAULT_PLATFORM_REFERENCES,
    PlatformReference,
    RuleScorer,
    ScoringConfig,
    ScoringThresholds,
    TopicRule,
    parse_search_traffic,
)


def make_raw_item(
    *,
    source_id: str = "tiktok",
    source_url: str = "https://example.com/item/1",
    external_id: str | None = "ext-1",
    title: str = "Trí tuệ nhân tạo AI đột phá mới tại Việt Nam",
    creator: str | None = "AI Creator",
    published_at: datetime | None = None,
    fetched_at: datetime | None = None,
    metrics: MetricSnapshot | None = None,
    metrics_snapshot_at: datetime | None = None,
    metadata: dict | None = None,
) -> RawItem:
    now = datetime.now(UTC)
    pub = published_at if published_at is not None else (now - timedelta(hours=2))
    fet = fetched_at or now
    snap = metrics_snapshot_at or (fet if metrics else None)
    return RawItem(
        source_id=source_id,
        source_url=HttpUrl(source_url),
        external_id=external_id,
        title=title,
        creator=creator,
        published_at=pub,
        fetched_at=fet,
        metrics=metrics,
        metrics_snapshot_at=snap,
        metadata=metadata or {},
    )


def make_strong_p1_evidence(now: datetime | None = None) -> list[RawItem]:
    """Helper creating realistic multi-source evidence that genuinely satisfies P1."""
    if now is None:
        now = datetime.now(UTC)
    primary = make_raw_item(
        source_id="google_trends",
        source_url="https://trends.google.com/story/viral-ai",
        external_id="p1-primary",
        title="Trí tuệ nhân tạo AI bùng nổ xu hướng công nghệ tại Việt Nam",
        creator="@techtok_creator",
        published_at=now - timedelta(minutes=15),
        fetched_at=now,
        metrics=MetricSnapshot(
            views=4_000_000,
            likes=400_000,
            shares=60_000,
            comments=25_000,
        ),
        metadata={
            "platform": "tiktok",
            "risk_check_passed": True,
            "high_risk": False,
            "is_duplicate": False,
        },
    )
    corroborating = make_raw_item(
        source_id="wikimedia",
        source_url="https://en.wikipedia.org/wiki/Artificial_intelligence_in_Vietnam",
        external_id="p1-corrob",
        title="Trí tuệ nhân tạo AI xu hướng công nghệ",
        published_at=now - timedelta(minutes=15),
        fetched_at=now,
        metadata={"platform": "wikimedia", "pageviews": 100_000},
    )
    return [primary, corroborating]


def test_parse_search_traffic():
    assert parse_search_traffic("+50K") == 50_000.0
    assert parse_search_traffic("10,000+") == 10_000.0
    assert parse_search_traffic("2M+") == 2_000_000.0
    assert parse_search_traffic("5000") == 5_000.0
    assert parse_search_traffic(None) is None
    assert parse_search_traffic("invalid") is None


def test_no_metrics_case_flagged_and_never_invents_numbers():
    scorer = RuleScorer()
    item = make_raw_item(
        source_id="tiktok",
        title="Video không có dữ liệu tương tác",
        metrics=None,
        metadata={"platform": "tiktok"},
    )

    res = scorer.score([item])

    assert res.virality <= 20.0
    assert "no engagement metrics were available" in res.explanation
    assert "single snapshot: no growth rate" in res.explanation
    assert 0 <= res.virality <= 100
    assert 0 <= res.relevance <= 100
    assert 0 <= res.credibility <= 100
    assert res.priority in (Priority.P1, Priority.P2, Priority.P3)


def test_single_snapshot_vs_two_snapshots_growth():
    scorer = RuleScorer()
    now = datetime.now(UTC)

    # Single snapshot
    item_single = make_raw_item(
        source_id="tiktok",
        source_url="https://example.com/video/100",
        external_id="vid-100",
        metrics=MetricSnapshot(views=50_000, likes=5_000, comments=200, shares=100),
        fetched_at=now,
    )
    res_single = scorer.score([item_single])
    assert "single snapshot: no growth rate" in res_single.explanation

    # Two snapshots of same item over 2 hours
    snap1 = make_raw_item(
        source_id="tiktok",
        source_url="https://example.com/video/100",
        external_id="vid-100",
        metrics=MetricSnapshot(views=50_000, likes=5_000, comments=200, shares=100),
        fetched_at=now - timedelta(hours=2),
        metrics_snapshot_at=now - timedelta(hours=2),
    )
    snap2 = make_raw_item(
        source_id="tiktok",
        source_url="https://example.com/video/100",
        external_id="vid-100",
        metrics=MetricSnapshot(views=120_000, likes=15_000, comments=800, shares=500),
        fetched_at=now,
        metrics_snapshot_at=now,
    )
    res_multi = scorer.score([snap1, snap2])
    assert "tăng trưởng +" in res_multi.explanation
    assert res_multi.virality > res_single.virality


def test_cross_source_corroboration_raises_virality_and_credibility():
    scorer = RuleScorer()
    now = datetime.now(UTC)

    item1 = make_raw_item(
        source_id="hackernews",
        source_url="https://news.ycombinator.com/item?id=123",
        external_id="hn-123",
        title="Open source AI model released",
        metadata={"hn_score": 350, "platform": "hackernews"},
        fetched_at=now,
    )
    res1 = scorer.score([item1])

    item2 = make_raw_item(
        source_id="google_trends",
        source_url="https://trends.google.com/story/456",
        external_id="gt-456",
        title="Open source AI model trending query",
        metadata={"search_traffic_label": "+50K", "platform": "google_trends"},
        fetched_at=now,
    )
    res_multi = scorer.score([item1, item2])

    assert res_multi.virality > res1.virality
    assert res_multi.credibility > res1.credibility
    assert "xác nhận" in res_multi.explanation


def test_priority_p1_only_when_all_conditions_hold():
    scorer = RuleScorer()
    now = datetime.now(UTC)
    evidence = make_strong_p1_evidence(now)

    res = scorer.score(evidence)
    assert res.priority == Priority.P1
    assert "toàn bộ 7 điều kiện" in res.explanation


def test_priority_caps_at_p2_with_missing_conditions():
    scorer = RuleScorer()
    now = datetime.now(UTC)

    # 1. Negative condition: Stale published_at (> 48h)
    stale_items = [
        make_raw_item(
            source_id="google_trends",
            source_url="https://trends.google.com/story/viral-ai",
            external_id="p1-primary",
            title="Trí tuệ nhân tạo AI bùng nổ xu hướng công nghệ tại Việt Nam",
            creator="@techtok_creator",
            published_at=now - timedelta(hours=72),
            fetched_at=now,
            metrics=MetricSnapshot(
                views=4_000_000,
                likes=400_000,
                shares=60_000,
                comments=25_000,
            ),
            metadata={
                "platform": "tiktok",
                "risk_check_passed": True,
                "high_risk": False,
                "is_duplicate": False,
            },
        ),
        make_raw_item(
            source_id="wikimedia",
            source_url="https://en.wikipedia.org/wiki/Artificial_intelligence_in_Vietnam",
            external_id="p1-corrob",
            title="Trí tuệ nhân tạo AI xu hướng công nghệ",
            published_at=now - timedelta(hours=72),
            fetched_at=now,
            metadata={"platform": "wikimedia", "pageviews": 100_000},
        ),
    ]
    res_stale = scorer.score(stale_items)
    assert res_stale.priority == Priority.P2
    assert "quá hạn" in res_stale.explanation

    # 2. Negative condition: Untraceable source URL
    url_items = make_strong_p1_evidence(now)
    url_items[0] = make_raw_item(
        source_id="google_trends",
        source_url="https://trends.google.com/story/viral-ai",
        external_id="p1-primary",
        title="Trí tuệ nhân tạo AI bùng nổ xu hướng công nghệ tại Việt Nam",
        creator="@techtok_creator",
        published_at=now - timedelta(minutes=15),
        fetched_at=now,
        metrics=MetricSnapshot(
            views=4_000_000,
            likes=400_000,
            shares=60_000,
            comments=25_000,
        ),
        metadata={
            "platform": "tiktok",
            "risk_check_passed": True,
            "untraceable_url": True,
        },
    )
    res_url = scorer.score(url_items)
    assert res_url.priority == Priority.P2
    assert "URL" in res_url.explanation or "truy xuất" in res_url.explanation

    # 3. Negative condition: Flagged duplicate
    dup_items = make_strong_p1_evidence(now)
    dup_items[0] = make_raw_item(
        source_id="google_trends",
        source_url="https://trends.google.com/story/viral-ai",
        external_id="p1-primary",
        title="Trí tuệ nhân tạo AI bùng nổ xu hướng công nghệ tại Việt Nam",
        creator="@techtok_creator",
        published_at=now - timedelta(minutes=15),
        fetched_at=now,
        metrics=MetricSnapshot(
            views=4_000_000,
            likes=400_000,
            shares=60_000,
            comments=25_000,
        ),
        metadata={
            "platform": "tiktok",
            "is_duplicate": True,
            "risk_check_passed": True,
        },
    )
    res_dup = scorer.score(dup_items)
    assert res_dup.priority == Priority.P2
    assert "trùng lặp" in res_dup.explanation

    # 4. Negative condition: Risk check failed
    risk_items = make_strong_p1_evidence(now)
    risk_items[0] = make_raw_item(
        source_id="google_trends",
        source_url="https://trends.google.com/story/viral-ai",
        external_id="p1-primary",
        title="Trí tuệ nhân tạo AI bùng nổ xu hướng công nghệ tại Việt Nam",
        creator="@techtok_creator",
        published_at=now - timedelta(minutes=15),
        fetched_at=now,
        metrics=MetricSnapshot(
            views=4_000_000,
            likes=400_000,
            shares=60_000,
            comments=25_000,
        ),
        metadata={
            "platform": "tiktok",
            "risk_check_passed": False,
        },
    )
    res_risk = scorer.score(risk_items)
    assert res_risk.priority == Priority.P2
    assert "rủi ro" in res_risk.explanation

    # 5. Negative condition: News/event claim with single source (< 2 sources)
    news_single = make_raw_item(
        source_id="google_trends",
        source_url="https://trends.google.com/story/viral-ai",
        external_id="p1-primary",
        title="Tin nóng: Vừa xảy ra tai nạn giao thông nghiêm trọng",
        creator="@techtok_creator",
        published_at=now - timedelta(minutes=15),
        fetched_at=now,
        metrics=MetricSnapshot(
            views=4_000_000,
            likes=400_000,
            shares=60_000,
            comments=25_000,
        ),
        metadata={
            "platform": "tiktok",
            "claim_type": "news",
            "risk_check_passed": True,
        },
    )
    res_news = scorer.score([news_single])
    assert res_news.priority == Priority.P2
    assert res_news.credibility <= 45.0
    assert "chưa xác minh" in res_news.explanation or "≥2 nguồn" in res_news.explanation


def test_independence_of_four_scores():
    scorer = RuleScorer()
    now = datetime.now(UTC)

    # Case A: Massive engagement on excluded gambling topic
    item_gambling = make_raw_item(
        source_id="tiktok",
        title="Hướng dẫn cờ bạc cá độ kiếm tiền siêu khủng nổ hũ",
        metrics=MetricSnapshot(views=2_000_000, likes=200_000, shares=30_000, comments=10_000),
        metadata={"platform": "tiktok", "topic": "cờ bạc cá độ"},
        published_at=now - timedelta(hours=1),
    )
    res_a = scorer.score([item_gambling])
    assert res_a.virality > 70.0
    assert res_a.relevance < 30.0

    # Case B: High relevance AI topic with zero engagement metrics
    item_ai_no_metrics = make_raw_item(
        source_id="wikimedia",
        title="Trí tuệ nhân tạo AI và ứng dụng tại Việt Nam",
        metrics=None,
        metadata={"platform": "wikimedia", "language": "vi"},
        published_at=now - timedelta(hours=1),
    )
    res_b = scorer.score([item_ai_no_metrics])
    assert res_b.virality <= 20.0
    assert res_b.relevance > 60.0
    assert res_b.credibility >= 80.0


def test_thresholds_are_adjustable():
    now = datetime.now(UTC)
    evidence = make_strong_p1_evidence(now)

    # Default config: satisfies default P1 (>= 85.0)
    scorer_default = RuleScorer()
    res_default = scorer_default.score(evidence)
    assert res_default.priority == Priority.P1

    # Stricter threshold: P1 >= 98.0 -> becomes P2
    strict_config = ScoringConfig(thresholds=ScoringThresholds(p1_threshold=98.0, p2_threshold=70.0))
    scorer_strict = RuleScorer(config=strict_config)
    res_strict = scorer_strict.score(evidence)
    assert res_strict.priority == Priority.P2

    # Very strict P2 threshold: P2 >= 95.0 -> becomes P3
    very_strict_config = ScoringConfig(thresholds=ScoringThresholds(p1_threshold=99.0, p2_threshold=95.0))
    scorer_p3 = RuleScorer(config=very_strict_config)
    res_p3 = scorer_p3.score(evidence)
    assert res_p3.priority == Priority.P3
