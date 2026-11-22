"""Unit tests for RuleScorer."""

from datetime import UTC, datetime, timedelta
import pytest
from pydantic import HttpUrl

from hunter.models import FocusTag
from hunter.models.briefs import Priority
from hunter.models.sources import MetricSnapshot, RawItem
from hunter.scoring import FocusRules
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
        source_id="b22e54f4-94ac-4ed2-8078-0d08d986bf11",
        source_url="https://news.ycombinator.com/item?id=123",
        external_id="hn-123",
        title="Open source AI model released",
        metadata={"hn_score": 350, "platform": "hacker_news"},
        fetched_at=now,
    )
    res1 = scorer.score([item1])

    item2 = make_raw_item(
        source_id="e43f314c-0f1a-48a4-90fd-b0c909351be9",
        source_url="https://trends.google.com/story/456",
        external_id="gt-456",
        title="Open source AI model trending query",
        metadata={"search_traffic_label": "+50K", "platform": "google_trends"},
        fetched_at=now,
    )
    res_multi = scorer.score([item1, item2])

    assert res_multi.virality > res1.virality
    assert res1.credibility == 80.0
    assert res_multi.credibility == 92.5
    assert "xác nhận độc lập từ nhiều nguồn (+10.0)" in res_multi.explanation

    repeated_snapshot = item1.model_copy(update={"fetched_at": now + timedelta(minutes=5)})
    assert scorer.score([item1, item2, repeated_snapshot]).credibility == res_multi.credibility

    same_platform = item2.model_copy(update={"metadata": {"platform": "hacker_news"}})
    assert scorer.score([item1, same_platform]).credibility == 90.0


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


@pytest.mark.parametrize("title", [
    "The Traitors: New Blood", "said", "mail", "Ai cũng biết", "ai", "trainer",
    "a.i.", "đAI", "AI_2",
])
def test_bare_ai_rejects_substrings_and_vietnamese_pronoun(title: str) -> None:
    result = RuleScorer().score([make_raw_item(title=title)])
    assert "chủ đề ưu tiên" not in result.explanation
    assert result.focus_tags == []


@pytest.mark.parametrize(("title", "keyword"), [
    ("AI video", "ai"),
    ("the AI boom", "ai"),
    ("New A.I. models", "ai"),
    ("trí tuệ nhân tạo", "trí tuệ nhân tạo"),
    ("新的人工智能模型", "人工智能"),
])
def test_priority_keyword_matches_whole_tokens_or_embedded_cjk(title: str, keyword: str) -> None:
    result = RuleScorer().score([make_raw_item(title=title)])
    assert f"chủ đề ưu tiên: {keyword} (+25)" in result.explanation


@pytest.mark.parametrize(("title", "relevance"), [
    ("family", 55.0),
    ("lifetime and familytree", 45.0),
    ("Scam", 0.0),
    ("scamper", 45.0),
    ("Rated 18+", 0.0),
    ("Rated 118+", 45.0),
    ("这是赌博新闻", 0.0),
])
def test_normal_and_excluded_keywords_use_token_boundaries(title: str, relevance: float) -> None:
    result = RuleScorer().score([make_raw_item(title=title, published_at=datetime.now(UTC))])
    assert result.relevance == relevance


@pytest.mark.parametrize(("keywords", "expected_tags"), [
    (("short films", "shortfilm", "新短片上线"), ["phim_ngan"]),
    (("phim ngắn", "short film", "新微电影上线"), ["phim_ngan", "giai_tri"]),
    ((
        "micro-drama", "microdrama", "microdramas", "micro drama", "short drama", "short dramas",
        "vertical drama", "mini drama", "新短剧上线", "新微短剧上线", "reelshort", "dramabox",
    ), ["micro_drama"]),
    (("phim nhiều tập",), ["micro_drama", "giai_tri"]),
    (("phim ngắn nhiều tập",), ["phim_ngan", "micro_drama", "giai_tri"]),
    ((
        "giải trí", "phim", "điện ảnh", "phim truyền hình", "diễn viên", "ca sĩ", "nghệ sĩ",
        "concert", "album", "gameshow", "game show", "talk show", "hài", "meme", "hoạt hình",
        "anime", "animation", "film", "movie", "tv series", "web series", "celebrity", "trailer",
        "娱乐", "电影", "综艺", "动画", "搞笑",
    ), ["giai_tri"]),
    ((
        "ai video", "ai short", "ai actor", "ai actors", "text-to-video", "text to video",
        "image-to-video", "image to video", "video generation", "video generator",
        "generative video", "aigc", "video do ai", "ai生成", "人工智能生成",
    ), ["ai_san_xuat"]),
    (("ai film", "ai movie", "ai animation", "làm phim bằng ai", "phim ai"), ["giai_tri", "ai_san_xuat"]),
    (("ai microdrama", "ai短剧"), ["micro_drama", "ai_san_xuat"]),
    (("Show HN", "Series A funding", "AI sell-off", "Sora, Veo, and Runway", "microdramatic", "filmstrip"), []),
    (("ai-generated", "ai generated", "ai-made", "ai voice", "ai music", "ai avatar"), []),
])
def test_focus_keywords_and_overlaps(keywords: tuple[str, ...], expected_tags: list[FocusTag]) -> None:
    scorer = RuleScorer()
    for keyword in keywords:
        assert scorer.score([make_raw_item(title=keyword)]).focus_tags == expected_tags, keyword


def test_focus_tags_follow_group_order_across_the_evidence_corpus() -> None:
    result = RuleScorer().score([
        make_raw_item(title="AI video tools", metadata={"description": "A new Vertical Drama"}),
        make_raw_item(title="Another AI video tool", metadata={"description": "Short Film"}),
    ])
    assert result.focus_tags == ["phim_ngan", "micro_drama", "giai_tri", "ai_san_xuat"]
    assert "nhóm trọng tâm: phim_ngan, micro_drama, giai_tri, ai_san_xuat" in result.explanation


def test_focus_tags_exclude_feed_category_and_topic() -> None:
    scorer = RuleScorer()
    labels = {"category": "giải trí", "topic": "short film"}
    fashion = scorer.score([make_raw_item(title="Mốt trench coat siêu ngắn", metadata=labels)])
    assert fashion.focus_tags == []
    assert "chủ đề phổ biến: giải trí (+10)" in fashion.explanation

    singer = scorer.score([make_raw_item(title="Ca sĩ mặt nạ: Ngọc Sơn bị loại", metadata=labels)])
    assert singer.focus_tags == ["giai_tri"]


@pytest.mark.parametrize("title", [
    "Zeus – Claude Code for AI voice agents",
    "Stop applying to jobs using AI-generated resume",
    "AquarIum – pick your favorite (AI-generated) fish tank",
    "ArkViz – AI generated software architecture diagrams",
    "AI-generated filmstrip",
])
def test_ai_production_weak_terms_need_media_context(title: str) -> None:
    result = RuleScorer().score([make_raw_item(title=title)])
    assert "ai_san_xuat" not in result.focus_tags


@pytest.mark.parametrize("title", [
    "HappyWan – text-to-video creation",
    "AI-generated short film wins prize",
    "AI voice for animated series",
])
def test_ai_production_matches_strong_terms_or_weak_terms_with_media(title: str) -> None:
    result = RuleScorer().score([make_raw_item(title=title)])
    assert "ai_san_xuat" in result.focus_tags


def test_ai_production_media_context_comes_from_the_same_item() -> None:
    scorer = RuleScorer()
    ai_item = make_raw_item(title="AI voice agents", metadata={"topic": "film", "category": "video"})
    media_item = make_raw_item(title="An animated series")
    assert "ai_san_xuat" not in scorer.score([ai_item, media_item]).focus_tags

    with_description = ai_item.model_copy(update={"metadata": {"description": "For an animated series"}})
    assert "ai_san_xuat" in scorer.score([with_description]).focus_tags


def test_focus_keywords_are_configurable() -> None:
    scorer = RuleScorer(ScoringConfig(focus_rules=FocusRules(phim_ngan=("ONE REEL",))))
    assert scorer.score([make_raw_item(title="One Reel")]).focus_tags == ["phim_ngan"]
    assert scorer.score([make_raw_item(title="Short film")]).focus_tags == ["giai_tri"]


@pytest.mark.parametrize(("title", "expected", "focus_points", "intersection"), [
    ("Short films", 70.0, 25, False),
    ("AI video", 70.0, 0, False),
    ("AI movie", 80.0, 0, True),
    ("ai movie", 80.0, 25, True),
    ("Entertainment concert", 80.0, 25, False),
    ("AI movie scam", 30.0, 0, True),
    ("Phim ngắn làm phim bằng ai", 100.0, 0, True),
])
def test_focus_relevance_weights(title: str, expected: float, focus_points: int, intersection: bool) -> None:
    result = RuleScorer().score([make_raw_item(title=title, published_at=datetime.now(UTC))])
    assert result.relevance == expected
    assert f"nhóm trọng tâm: {', '.join(result.focus_tags)} (+{focus_points}" in result.explanation
    assert ("giao điểm AI × phim/giải trí (+10)" in result.explanation) == intersection


def test_focus_relevance_keeps_freshness_decay_and_cap() -> None:
    scorer = RuleScorer()
    title = "ai movie và giải trí"
    now = datetime.now(UTC)
    assert scorer.score([make_raw_item(title=title, published_at=now)]).relevance == 100.0
    assert scorer.score([make_raw_item(
        title=title, published_at=now - timedelta(hours=48),
    )]).relevance == 83.4


def test_focus_relevance_half_life_applies_only_to_tagged_items(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 11, 22, tzinfo=UTC)
    monkeypatch.setattr("hunter.scoring.rules.utcnow", lambda: now)
    general = make_raw_item(title="Technology", published_at=now - timedelta(hours=96), fetched_at=now)
    focus = general.model_copy(update={"metadata": {"description": "Text-to-video creation"}})

    scorer = RuleScorer()
    general_result = scorer.score([general])
    focus_result = scorer.score([focus])

    assert general_result.focus_tags == []
    assert focus_result.focus_tags == ["ai_san_xuat"]
    assert general_result.relevance == round(70.0 * 0.5 ** (96 / 48), 1)
    assert focus_result.relevance == round(70.0 * 0.5 ** (96 / 120), 1)
    assert "chu kỳ bán rã 48h" in general_result.explanation
    assert "chu kỳ bán rã 120h" in focus_result.explanation


@pytest.mark.parametrize(("platform", "expected"), [
    ("wikipedia", 90.0),
    ("google_trends", 85.0),
    ("hacker_news", 80.0),
    ("vn_news", 65.0),
    ("unlisted_platform", 35.0),
])
def test_credibility_looks_up_platform_for_uuid_source_id(platform: str, expected: float) -> None:
    item = make_raw_item(
        source_id="8d321891-7334-4e0a-b4ea-8c8ad8a8e8ea", metadata={"platform": platform},
    )
    assert RuleScorer().score([item]).credibility == expected


def test_vn_news_reliability_keeps_single_source_claim_cap() -> None:
    scorer = RuleScorer()
    item = make_raw_item(
        source_id="8d321891-7334-4e0a-b4ea-8c8ad8a8e8ea", title="Short film",
        metadata={"platform": "vn_news", "claim_type": "news"},
    )
    result = scorer.score([item])
    assert result.credibility == 45.0
    assert "chưa xác minh" in result.explanation
