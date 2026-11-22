"""Rule-based scoring implementing the Scorer protocol."""

from collections.abc import Sequence
from dataclasses import dataclass, field
import math
import re

from hunter.interfaces.briefs import Scorer, ScoringResult
from hunter.models.briefs import FocusTag, Priority, Score
from hunter.models.common import utcnow
from hunter.models.sources import RawItem

from .keywords import FocusRules, KeywordMatcher


@dataclass(frozen=True)
class PlatformReference:
    """Configurable baseline metrics for normal engagement on a platform."""

    views: float = 100_000.0
    likes: float = 10_000.0
    shares: float = 2_000.0
    comments: float = 1_000.0
    custom_metric: float = 1_000.0


DEFAULT_PLATFORM_REFERENCES: dict[str, PlatformReference] = {
    "tiktok": PlatformReference(views=500_000.0, likes=50_000.0, shares=5_000.0, comments=2_000.0),
    "douyin": PlatformReference(views=500_000.0, likes=50_000.0, shares=5_000.0, comments=2_000.0),
    "youtube": PlatformReference(views=200_000.0, likes=15_000.0, shares=1_000.0, comments=1_000.0),
    "hackernews": PlatformReference(custom_metric=300.0, comments=100.0),
    "google_trends": PlatformReference(custom_metric=20_000.0),
    "wikimedia": PlatformReference(custom_metric=50_000.0),
    "default": PlatformReference(),
}

DEFAULT_SOURCE_RELIABILITY: dict[str, float] = {
    "wikimedia": 90.0,
    "google_trends": 85.0,
    "hackernews": 80.0,
    "tiktok": 70.0,
    "douyin": 70.0,
    "youtube": 75.0,
    "vn_news": 65.0,
    "official_api": 90.0,
    "aggregator": 60.0,
    "unknown": 35.0,
}


@dataclass(frozen=True)
class TopicRule:
    """Keyword tables for Vietnamese, English, and Chinese topic matching."""

    priority_topics: list[str] = field(
        default_factory=lambda: [
            # AI & Technology
            "ai", "trí tuệ nhân tạo", "chatgpt", "llm", "claude", "gemini", "deepseek",
            "công nghệ", "robot", "artificial intelligence", "technology", "人工智能", "科技",
            # Viral & Breaking
            "viral", "trend", "xu hướng", "hiện tượng", "đột phá", "bùng nổ", "热点",
            # Short drama / Micro-drama
            "phim ngắn", "phim nhiều tập", "micro-drama", "short drama", "短剧", "微短剧",
        ]
    )
    normal_topics: list[str] = field(
        default_factory=lambda: [
            "đời sống", "cuộc sống", "gia đình", "tình cảm", "life", "family", "生活", "情感", "家庭",
            "giải trí", "hài hước", "meme", "funny", "entertainment", "搞笑", "娱乐",
            "kiến thức", "khoa học", "khám phá", "education", "science", "科普",
        ]
    )
    excluded_topics: list[str] = field(
        default_factory=lambda: [
            "cờ bạc", "cá độ", "lừa đảo", "gambling", "betting", "scam",
            "nội dung khiêu dâm", "porn", "nsfw", "18+", "赌博", "色情",
        ]
    )


@dataclass(frozen=True)
class ScoringThresholds:
    """Configurable priority thresholds and gate criteria."""

    p1_threshold: float = 85.0
    p2_threshold: float = 60.0
    p1_max_age_hours: float = 48.0


@dataclass(frozen=True)
class ScoringConfig:
    """All named constants and configurable reference values for scoring."""

    platform_references: dict[str, PlatformReference] = field(
        default_factory=lambda: dict(DEFAULT_PLATFORM_REFERENCES)
    )
    source_reliability: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_SOURCE_RELIABILITY)
    )
    topic_rules: TopicRule = field(default_factory=TopicRule)
    thresholds: ScoringThresholds = field(default_factory=ScoringThresholds)

    # Weights for engagement sub-metrics
    virality_views_weight: float = 0.35
    virality_likes_weight: float = 0.25
    virality_shares_weight: float = 0.25
    virality_comments_weight: float = 0.15

    # Freshness half-life in hours
    relevance_half_life_hours: float = 48.0

    # Internal ranking weights used ONLY for priority sorting, never exposed as a score
    internal_weight_virality: float = 0.40
    internal_weight_relevance: float = 0.35
    internal_weight_credibility: float = 0.25

    focus_rules: FocusRules = field(default_factory=FocusRules)
    focus_relevance_half_life_hours: float = 120.0


def parse_search_traffic(label: object) -> float | None:
    """Parse approximate search traffic labels like '+50K', '10,000+', '50K+'."""
    if not isinstance(label, str):
        if isinstance(label, (int, float)):
            return float(label)
        return None
    clean = label.replace("+", "").replace(",", "").replace(" ", "").strip().upper()
    match = re.match(r"^([0-9.]+)([KM]?)$", clean)
    if not match:
        return None
    val_str, unit = match.groups()
    try:
        val = float(val_str)
        if unit == "K":
            val *= 1_000.0
        elif unit == "M":
            val *= 1_000_000.0
        return val
    except ValueError:
        return None


def extract_platform_key(item: RawItem) -> str:
    """Resolve normalized platform name from metadata, source_id, or source_url."""
    meta_platform = item.metadata.get("platform")
    if isinstance(meta_platform, str) and meta_platform.strip():
        plat = meta_platform.strip().lower()
        if "tiktok" in plat:
            return "tiktok"
        if "douyin" in plat:
            return "douyin"
        if "youtube" in plat:
            return "youtube"
        if plat == "hacker_news" or "hackernews" in plat or "hn" in plat:
            return "hackernews"
        if "google" in plat or "trends" in plat:
            return "google_trends"
        if "wikimedia" in plat or "wiki" in plat:
            return "wikimedia"
        return plat

    sid = item.source_id.lower()
    for key in ("tiktok", "douyin", "youtube", "hackernews", "google_trends", "wikimedia"):
        if key in sid:
            return key

    url_str = str(item.source_url).lower()
    for key in ("tiktok", "douyin", "youtube", "hackernews", "google", "wikipedia", "wikimedia"):
        if key in url_str:
            if key == "google":
                return "google_trends"
            if key in ("wikipedia", "wikimedia"):
                return "wikimedia"
            return key

    return "default"


def is_news_or_event_claim(items: Sequence[RawItem]) -> bool:
    """Determine whether the evidence asserts a factual news or event claim needing verification."""
    claim_types = {"news", "event", "breaking", "factual_claim"}
    for it in items:
        ct = it.metadata.get("claim_type") or it.metadata.get("content_type")
        if isinstance(ct, str) and ct.strip().lower() in claim_types:
            return True
        if it.metadata.get("is_claim") is True or it.metadata.get("needs_verification") is True:
            return True
        title = (it.title or "").lower()
        if any(
            kw in title
            for kw in (
                "tin nóng", "breaking", "vừa xảy ra", "bắt giữ", "khởi tố",
                "tai nạn", "phát hiện", "công bố chính thức", "đột ngột qua đời",
            )
        ):
            return True
    return False


class RuleScorer:
    """Rule-based scorer computing four independent signals and explainable priority."""

    def __init__(self, config: ScoringConfig | None = None) -> None:
        self.config = config or ScoringConfig()
        topics = self.config.topic_rules
        self._excluded_topics = KeywordMatcher(topics.excluded_topics)
        self._priority_topics = KeywordMatcher(topics.priority_topics)
        self._normal_topics = KeywordMatcher(topics.normal_topics)
        focus = self.config.focus_rules
        self._focus_groups: tuple[tuple[FocusTag, KeywordMatcher], ...] = (
            ("phim_ngan", KeywordMatcher(focus.phim_ngan)),
            ("micro_drama", KeywordMatcher(focus.micro_drama)),
            ("giai_tri", KeywordMatcher(focus.giai_tri)),
        )
        self._ai_production = KeywordMatcher(focus.ai_san_xuat)
        self._weak_ai_production = KeywordMatcher(focus.ai_san_xuat_weak)
        self._media_context = KeywordMatcher(focus.ai_san_xuat_media)

    def score(self, items: Sequence[RawItem]) -> ScoringResult:
        """Score the supplied evidence and explain priority and verification requirements."""
        if not items:
            raise ValueError("At least one RawItem is required for scoring")

        primary = items[0]
        distinct_source_ids = {it.source_id for it in items if it.source_id}

        # 1. Virality Score
        virality, virality_exp = self._score_virality(items, primary, distinct_source_ids)

        # 2. Relevance Score
        relevance, relevance_exp, focus_tags = self._score_relevance(items, primary)

        # 3. Credibility Score
        credibility, credibility_exp, claim_verified = self._score_credibility(
            items, distinct_source_ids
        )

        # 4. Priority and missing conditions
        priority, priority_exp = self._determine_priority(
            items=items,
            primary=primary,
            virality=virality,
            relevance=relevance,
            credibility=credibility,
            distinct_source_ids=distinct_source_ids,
            claim_verified=claim_verified,
        )

        full_explanation = (
            f"[Ưu tiên]: {priority_exp}\n"
            f"[Độ lan truyền ({virality:.1f}/100)]: {virality_exp}\n"
            f"[Độ phù hợp ({relevance:.1f}/100)]: {relevance_exp}\n"
            f"[Độ tin cậy ({credibility:.1f}/100)]: {credibility_exp}"
        )

        return ScoringResult(
            virality=virality,
            relevance=relevance,
            credibility=credibility,
            priority=priority,
            explanation=full_explanation,
            focus_tags=focus_tags,
        )

    def _score_virality(
        self,
        items: Sequence[RawItem],
        primary: RawItem,
        distinct_source_ids: set[str],
    ) -> tuple[Score, str]:
        platform_key = extract_platform_key(primary)
        ref = self.config.platform_references.get(
            platform_key, self.config.platform_references["default"]
        )

        # Collect primary metrics
        metrics = primary.metrics
        views = metrics.views if metrics else None
        likes = metrics.likes if metrics else None
        shares = metrics.shares if metrics else None
        comments = metrics.comments if metrics else None

        # Check metadata signals
        hn_score = primary.metadata.get("hn_score") or primary.metadata.get("score")
        if not isinstance(hn_score, (int, float)):
            hn_score = None

        search_traffic = parse_search_traffic(primary.metadata.get("search_traffic_label"))

        pageviews = primary.metadata.get("pageviews")
        if not isinstance(pageviews, (int, float)):
            pageviews = None

        has_metrics = any(
            v is not None and v > 0
            for v in (views, likes, shares, comments, hn_score, search_traffic, pageviews)
        )

        # Growth rate check (two snapshots of same item)
        same_item_snapshots = [
            it
            for it in items
            if (it.external_id and it.external_id == primary.external_id)
            or str(it.source_url) == str(primary.source_url)
        ]

        growth_boost = 0.0
        growth_exp = "single snapshot: no growth rate"

        if len(same_item_snapshots) >= 2:
            sorted_snapshots = sorted(
                same_item_snapshots,
                key=lambda x: x.metrics_snapshot_at or x.fetched_at,
            )
            first_snap, last_snap = sorted_snapshots[0], sorted_snapshots[-1]
            t1 = first_snap.metrics_snapshot_at or first_snap.fetched_at
            t2 = last_snap.metrics_snapshot_at or last_snap.fetched_at
            dt_seconds = (t2 - t1).total_seconds()
            if dt_seconds >= 60:
                dt_hours = dt_seconds / 3600.0
                v1 = first_snap.metrics.views if first_snap.metrics else None
                v2 = last_snap.metrics.views if last_snap.metrics else None
                if v1 is not None and v2 is not None and v2 >= v1:
                    d_views = v2 - v1
                    rate_per_hour = d_views / dt_hours
                    growth_boost = min(25.0, math.log10(1.0 + rate_per_hour) * 4.0)
                    growth_exp = (
                        f"tăng trưởng +{d_views:,} lượt xem trong {dt_hours:.1f}h "
                        f"(+{rate_per_hour:.1f}/h, +{growth_boost:.1f} điểm)"
                    )
                else:
                    growth_exp = f"hai snapshot cách nhau {dt_hours:.1f}h nhưng không phát hiện tăng trưởng số liệu"
            else:
                growth_exp = "hai snapshot quá gần nhau: không tính tốc độ tăng trưởng"

        # Corroboration boost
        corrob_boost = 0.0
        if len(distinct_source_ids) >= 2:
            corrob_boost = min(15.0, (len(distinct_source_ids) - 1) * 7.5)

        if not has_metrics:
            # Low confidence baseline, never invent numbers
            base_score = 10.0 + corrob_boost
            virality = max(0.0, min(100.0, round(base_score, 1)))
            explanation = (
                "no engagement metrics were available; điểm lan truyền thấp dựa trên tín hiệu cơ bản; "
                f"{growth_exp}"
            )
            if corrob_boost > 0:
                explanation += f"; xác nhận chéo từ {len(distinct_source_ids)} nguồn (+{corrob_boost:.1f} điểm)"
            return virality, explanation

        # Calculate log-scaled metric score
        def log_ratio(val: float, ref_val: float) -> float:
            return min(1.5, math.log10(1.0 + max(0.0, val)) / math.log10(1.0 + max(1.0, ref_val)))

        metric_points = 0.0
        weight_sum = 0.0

        if views is not None:
            metric_points += log_ratio(views, ref.views) * self.config.virality_views_weight
            weight_sum += self.config.virality_views_weight
        if likes is not None:
            metric_points += log_ratio(likes, ref.likes) * self.config.virality_likes_weight
            weight_sum += self.config.virality_likes_weight
        if shares is not None:
            metric_points += log_ratio(shares, ref.shares) * self.config.virality_shares_weight
            weight_sum += self.config.virality_shares_weight
        if comments is not None:
            metric_points += log_ratio(comments, ref.comments) * self.config.virality_comments_weight
            weight_sum += self.config.virality_comments_weight

        # Custom metrics (HN score, Google Trends, Wikimedia pageviews)
        if hn_score is not None:
            metric_points += log_ratio(float(hn_score), ref.custom_metric) * 0.50
            weight_sum += 0.50
        if search_traffic is not None:
            metric_points += log_ratio(search_traffic, ref.custom_metric) * 0.50
            weight_sum += 0.50
        if pageviews is not None:
            metric_points += log_ratio(float(pageviews), ref.custom_metric) * 0.50
            weight_sum += 0.50

        scaled_score = (metric_points / weight_sum) * 70.0 if weight_sum > 0 else 10.0
        total_virality = scaled_score + growth_boost + corrob_boost
        virality = max(0.0, min(100.0, round(total_virality, 1)))

        details: list[str] = [f"nền tảng: {platform_key}"]
        if views is not None:
            details.append(f"views: {views:,}")
        if likes is not None:
            details.append(f"likes: {likes:,}")
        if shares is not None:
            details.append(f"shares: {shares:,}")
        if comments is not None:
            details.append(f"comments: {comments:,}")
        if hn_score is not None:
            details.append(f"hn_score: {hn_score}")
        if search_traffic is not None:
            details.append(f"search_traffic: {search_traffic:,}")
        if pageviews is not None:
            details.append(f"pageviews: {pageviews:,}")
        details.append(growth_exp)
        if corrob_boost > 0:
            details.append(f"xác nhận chéo từ {len(distinct_source_ids)} nguồn (+{corrob_boost:.1f} điểm)")

        explanation = "; ".join(details)
        return virality, explanation

    def _match_focus_tags(self, items: Sequence[RawItem]) -> list[FocusTag]:
        content: list[tuple[str, str]] = []
        for item in items:
            description = item.metadata.get("description")
            text = " ".join(part for part in (item.title, description) if isinstance(part, str))
            content.append((text, text.lower()))

        tags = [
            tag
            for tag, matcher in self._focus_groups
            if any(matcher.matches(text, lowercase) for text, lowercase in content)
        ]
        if any(
            self._ai_production.matches(text, lowercase)
            or (
                self._weak_ai_production.matches(text, lowercase)
                and self._media_context.matches(text, lowercase)
            )
            for text, lowercase in content
        ):
            tags.append("ai_san_xuat")
        return tags

    def _score_relevance(
        self,
        items: Sequence[RawItem],
        primary: RawItem,
    ) -> tuple[Score, str, list[FocusTag]]:
        original_text = " ".join(
            filter(
                None,
                [it.title or "" for it in items]
                + [str(it.metadata.get("description", "")) for it in items]
                + [str(it.metadata.get("topic", "")) for it in items]
                + [str(it.metadata.get("category", "")) for it in items],
            )
        )
        text_corpus = original_text.lower()

        # Vietnamese language / diacritics detection
        has_vn_diacritics = bool(
            re.search(
                r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệđìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ]",
                text_corpus,
                re.IGNORECASE,
            )
        )
        lang = str(primary.metadata.get("language") or primary.metadata.get("original_language") or "").lower()
        is_vietnamese = has_vn_diacritics or lang in ("vi", "vie", "vietnamese") or "việt nam" in text_corpus

        # Topic matching
        matched_excluded = list(self._excluded_topics.find(original_text, text_corpus))
        matched_priority = list(self._priority_topics.find(original_text, text_corpus))
        matched_normal = list(self._normal_topics.find(original_text, text_corpus))
        focus_tags = self._match_focus_tags(items)

        base_relevance = 45.0
        details: list[str] = []

        if is_vietnamese:
            base_relevance += 20.0
            details.append("người xem Việt Nam phù hợp (tiếng Việt / bối cảnh VN, +20)")

        if matched_priority:
            base_relevance += 25.0
            details.append(f"chủ đề ưu tiên: {', '.join(matched_priority[:3])} (+25)")
        elif matched_normal:
            base_relevance += 10.0
            details.append(f"chủ đề phổ biến: {', '.join(matched_normal[:3])} (+10)")

        if focus_tags:
            tags = ", ".join(focus_tags)
            if matched_priority:
                details.append(f"nhóm trọng tâm: {tags} (+0 do đã cộng điểm chủ đề ưu tiên)")
            else:
                base_relevance += 25.0
                details.append(f"nhóm trọng tâm: {tags} (+25)")
            if "ai_san_xuat" in focus_tags and len(focus_tags) > 1:
                base_relevance += 10.0
                details.append("giao điểm AI × phim/giải trí (+10)")

        if matched_excluded:
            base_relevance -= 50.0
            details.append(f"chủ đề bị loại trừ: {', '.join(matched_excluded[:2])} (-50)")

        # Freshness decay
        ref_time = primary.published_at or primary.fetched_at
        now = utcnow()
        age_hours = max(0.0, (now - ref_time).total_seconds() / 3600.0)
        half_life = (
            self.config.focus_relevance_half_life_hours
            if focus_tags else self.config.relevance_half_life_hours
        )
        freshness_decay = 0.5 ** (age_hours / half_life)
        final_relevance = max(0.0, min(100.0, base_relevance * freshness_decay))

        details.append(
            f"độ tuổi {age_hours:.1f}h (chu kỳ bán rã {half_life:g}h, hệ số thời gian: {freshness_decay:.2f})"
        )
        relevance = max(0.0, min(100.0, round(final_relevance, 1)))
        explanation = "; ".join(details)
        return relevance, explanation, focus_tags

    def _score_credibility(
        self,
        items: Sequence[RawItem],
        distinct_source_ids: set[str],
    ) -> tuple[Score, str, bool]:
        # Use the first evidence from each source so repeated snapshots carry the same weight.
        reliability_table = self.config.source_reliability
        unknown_reliability = reliability_table.get("unknown", 35.0)
        reliabilities: dict[str, float] = {}
        for item in items:
            if item.source_id in distinct_source_ids and item.source_id not in reliabilities:
                reliabilities[item.source_id] = reliability_table.get(
                    extract_platform_key(item), unknown_reliability
                )

        base_reliability = sum(reliabilities.values()) / len(reliabilities) if reliabilities else 35.0

        # Multi-source corroboration boost
        num_sources = len(distinct_source_ids)
        corrob_boost = min(20.0, (num_sources - 1) * 10.0) if num_sources >= 2 else 0.0

        total_credibility = base_reliability + corrob_boost
        details: list[str] = [
            f"độ tin cậy nguồn: {base_reliability:.1f} (từ {num_sources} nguồn)"
        ]

        if corrob_boost > 0:
            details.append(f"xác nhận độc lập từ nhiều nguồn (+{corrob_boost:.1f})")

        # Claim type verification check
        is_claim = is_news_or_event_claim(items)
        claim_verified = True

        if is_claim:
            if num_sources < 2:
                claim_verified = False
                total_credibility = min(total_credibility, 45.0)
                details.append("tin tức/sự kiện chỉ có 1 nguồn, bị gắn cờ chưa xác minh (cần ≥2 nguồn độc lập)")
            else:
                claim_verified = True
                details.append(f"tin tức/sự kiện đã xác minh qua {num_sources} nguồn độc lập")
        else:
            details.append("nội dung đời sống/sáng tạo/công nghệ, không yêu cầu xác minh sự kiện đa nguồn")

        credibility = max(0.0, min(100.0, round(total_credibility, 1)))
        explanation = "; ".join(details)
        return credibility, explanation, claim_verified

    def _determine_priority(
        self,
        items: Sequence[RawItem],
        primary: RawItem,
        virality: float,
        relevance: float,
        credibility: float,
        distinct_source_ids: set[str],
        claim_verified: bool,
    ) -> tuple[Priority, str]:
        # Internal ranking number used ONLY as a sort key, never exposed as a score
        internal_score = (
            self.config.internal_weight_virality * virality
            + self.config.internal_weight_relevance * relevance
            + self.config.internal_weight_credibility * credibility
        )

        thresholds = self.config.thresholds

        if internal_score < thresholds.p2_threshold:
            return Priority.P3, f"P3 (điểm nội bộ {internal_score:.1f} < ngưỡng P2 {thresholds.p2_threshold})"

        # Candidate for P1 or P2: evaluate ALL 7 mandatory conditions
        ref_time = primary.published_at or primary.fetched_at
        age_hours = max(0.0, (utcnow() - ref_time).total_seconds() / 3600.0)

        has_traceable_url = bool(primary.source_url) and primary.metadata.get("untraceable_url") is not True
        has_notable_signal = (
            virality >= 65.0
            or len(distinct_source_ids) >= 2
            or any(
                it.metadata.get("hn_score") or it.metadata.get("search_traffic_label") or it.metadata.get("pageviews")
                for it in items
            )
        )
        is_fresh = age_hours <= thresholds.p1_max_age_hours
        is_not_duplicate = not any(
            it.metadata.get("is_duplicate") is True or it.metadata.get("duplicate_of") is not None
            for it in items
        )
        risk_passed = not any(
            it.metadata.get("risk_check_passed") is False or it.metadata.get("high_risk") is True
            for it in items
        )
        verification_satisfied = claim_verified

        missing_conditions: list[str] = []
        if not has_traceable_url:
            missing_conditions.append("thiếu URL nguồn truy xuất được (untraceable source URL)")
        if not has_notable_signal:
            missing_conditions.append("thiếu tín hiệu nổi bật (notable signal)")
        if not is_fresh:
            missing_conditions.append(
                f"nội dung đã quá hạn xét P1 ({age_hours:.1f}h > {thresholds.p1_max_age_hours}h)"
            )
        if not is_not_duplicate:
            missing_conditions.append("bị gắn cờ trùng lặp (flagged duplicate)")
        if not risk_passed:
            missing_conditions.append("không vượt qua kiểm tra rủi ro (risk check failed)")
        if not verification_satisfied:
            missing_conditions.append("tin tức/sự kiện chưa đủ ≥2 nguồn độc lập xác minh")

        if internal_score >= thresholds.p1_threshold:
            if missing_conditions:
                reason = (
                    f"P2 (đủ điểm P1 {internal_score:.1f} nhưng bị giới hạn xuống P2 do thiếu điều kiện: "
                    f"{'; '.join(missing_conditions)})"
                )
                return Priority.P2, reason
            return Priority.P1, f"P1 (đủ điểm {internal_score:.1f} ≥ {thresholds.p1_threshold} và thỏa mãn toàn bộ 7 điều kiện xét P1)"

        # internal_score is between p2_threshold and p1_threshold
        if missing_conditions:
            reason = (
                f"P2 (điểm nội bộ {internal_score:.1f} đạt ngưỡng P2 nhưng không đạt P1 do thiếu điều kiện: "
                f"{'; '.join(missing_conditions)})"
            )
            return Priority.P2, reason

        return Priority.P2, f"P2 (điểm nội bộ {internal_score:.1f} đạt ngưỡng P2 nhưng chưa đạt ngưỡng P1 {thresholds.p1_threshold})"
