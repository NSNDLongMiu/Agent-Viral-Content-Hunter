"""Unit tests for briefs Markdown and JSON rendering."""

from datetime import UTC, datetime, timedelta
import json

import pytest
from pydantic import HttpUrl

from hunter.models.briefs import AIFeasibility, AIProduction, BriefStatus, ContentBrief, HandoffStatus, Priority
from hunter.models.sources import MetricSnapshot
from hunter.briefs.render import to_json, to_markdown


def make_vietnamese_summary(n_words: int = 60) -> str:
    words = [
        "Đây", "là", "bản", "tóm", "tắt", "nội", "dung", "video", "viral", "rất",
        "hấp", "dẫn", "về", "công", "nghệ", "trí", "tuệ", "nhân", "tạo", "đang",
        "thu", "hút", "sự", "quan", "tâm", "lớn", "từ", "cộng", "đồng", "mạng",
        "xã", "hội", "tại", "Việt", "Nam", "nhờ", "vào", "cách", "tiếp", "cận",
        "sáng", "tạo", "và", "hình", "ảnh", "minh", "họa", "sinh", "động", "giúp",
        "người", "xem", "dễ", "dàng", "nắm", "bắt", "thông", "tin", "hữu", "ích",
    ]
    repeated = (words * ((n_words // len(words)) + 2))[:n_words]
    return " ".join(repeated)


SAMPLE_WHY_NOTABLE = (
    "Hook: Giữ chân người xem trong 3 giây đầu bằng hiệu ứng bất ngờ.\n"
    "Định dạng: Video ngắn nhịp độ nhanh kèm phụ đề nổi bật.\n"
    "Cảm xúc / động lực chia sẻ: Tò mò và ngạc nhiên trước công nghệ mới.\n"
    "Nhóm người xem: Giới trẻ và người làm sáng tạo nội dung.\n"
    "Thời điểm: Bắt đúng làn sóng AI đang thịnh hành.\n"
    "Khả năng khai thác ở Việt Nam: Rất cao, khán giả Việt Nam yêu thích công nghệ.\n"
    "Bài học áp dụng (không sao chép): Tập trung vào giải quyết vấn đề thực tế."
)


def make_sample_content_brief(*, metadata_only: bool = False) -> ContentBrief:
    now = datetime.now(UTC)
    pub = now - timedelta(hours=6)
    disc = now - timedelta(hours=5)
    snap = now - timedelta(hours=5)

    meta_note = (
        "Tóm tắt được tạo dựa trên siêu dữ liệu (metadata), chưa xem đầy đủ nội dung gốc."
        if metadata_only
        else None
    )

    return ContentBrief(
        id="brief-2026-xyz",
        title_vi="Mô hình AI mới đạt kỷ lục người dùng tại Việt Nam",
        original_title="New open source AI breaks records in adoption",
        content_type="video",
        platform="tiktok",
        original_language="en",
        published_at=pub,
        discovered_at=disc,
        creator="@techtok_creator",
        summary_vi=make_vietnamese_summary(60),
        why_notable=SAMPLE_WHY_NOTABLE,
        virality_score=92.5,
        relevance_score=88.0,
        credibility=85.0,
        priority=Priority.P1,
        original_url=HttpUrl("https://example.com/video/original-123"),
        related_urls=[HttpUrl("https://example.com/video/related-456")],
        engagement_metrics=MetricSnapshot(
            views=1_500_000,
            likes=120_000,
            shares=15_000,
            comments=4_500,
        ),
        metrics_snapshot_at=snap,
        verification_level="corroborated by 2 sources (not independently fact-checked)",
        risks_and_notes=[
            "Cần kiểm tra kỹ bản quyền âm nhạc nền",
            "Nội dung chứa tuyên bố hiệu năng cần xác minh với tài liệu gốc",
        ],
        suggested_formats=[
            "Video phân tích dạng reaction 60s",
            "Video hướng dẫn thử nghiệm thực tế",
        ],
        metadata_only=metadata_only,
        metadata_note_vi=meta_note,
        score_explanation="Chỉ số lan truyền rất cao, chủ đề công nghệ ưu tiên, nguồn tin cậy",
        status=BriefStatus.APPROVED_BY_CLAUDE,
        handoff_status=HandoffStatus.SELECTED,
        revision_count=1,
        created_at=disc,
        updated_at=now,
    )


def test_markdown_contains_all_24_fields():
    brief = make_sample_content_brief(metadata_only=False)
    md = to_markdown(brief)

    # 1. ID hồ sơ
    assert brief.id in md
    # 2. Tiêu đề tiếng Việt
    assert brief.title_vi in md
    # 3. Tiêu đề gốc
    assert brief.original_title in md
    # 4. Loại nội dung
    assert brief.content_type in md
    # 5. Nền tảng
    assert brief.platform in md
    # 6. Ngôn ngữ gốc
    assert brief.original_language in md
    # 7. Thời gian đăng
    assert brief.published_at.isoformat() in md
    # 8. Thời gian phát hiện
    assert brief.discovered_at.isoformat() in md
    # 9. Creator/tác giả
    assert brief.creator in md
    # 10. Tóm tắt 50-100 từ
    assert brief.summary_vi in md
    # 11. Lý do nội dung đáng chú ý
    assert brief.why_notable in md
    # 12. Virality Score
    assert f"{brief.virality_score:.1f}" in md
    # 13. Relevance Score
    assert f"{brief.relevance_score:.1f}" in md
    # 14. Credibility
    assert f"{brief.credibility:.1f}" in md
    # 15. Priority
    assert brief.priority.value in md
    # 16. URL nguồn gốc
    assert str(brief.original_url) in md
    # 17. URL nguồn liên quan
    assert str(brief.related_urls[0]) in md
    # 18. Chỉ số tương tác (views, likes, shares, comments)
    assert "1,500,000" in md
    assert "120,000" in md
    assert "15,000" in md
    assert "4,500" in md
    # 19. Thời điểm ghi nhận chỉ số
    assert brief.metrics_snapshot_at.isoformat() in md
    # 20. Mức độ xác minh
    assert brief.verification_level in md
    # 21. Rủi ro và lưu ý
    for r in brief.risks_and_notes:
        assert r in md
    # 22. Gợi ý định dạng khai thác
    for f in brief.suggested_formats:
        assert f in md
    # 23. Trạng thái kiểm duyệt
    assert brief.status.value in md
    # 24. Trạng thái bàn giao
    assert brief.handoff_status.value in md


def test_markdown_renders_metadata_only_notice():
    brief = make_sample_content_brief(metadata_only=True)
    md = to_markdown(brief)

    assert "METADATA-ONLY" in md
    assert brief.metadata_note_vi in md


@pytest.mark.parametrize("feasibility, label", [
    (AIFeasibility.HIGH, "Cao"),
    (AIFeasibility.MEDIUM, "Trung bình"),
    (AIFeasibility.LOW, "Thấp"),
])
def test_markdown_renders_ai_production_and_focus_labels(feasibility: AIFeasibility, label: str) -> None:
    brief = make_sample_content_brief()
    brief.focus_tags = ["phim_ngan", "micro_drama", "giai_tri", "ai_san_xuat"]
    brief.ai_production = AIProduction(
        feasibility=feasibility,
        approach_vi="Tạo một video hoạt hình kể chuyện hư cấu bằng ảnh minh họa và giọng đọc AI.",
        constraints_vi=["Kiểm tra nhãn AI.", "Dùng nhân vật tự sáng tạo."],
    )
    markdown = to_markdown(brief)

    assert "**Nhãn trọng tâm:** Phim ngắn, Micro-drama, Giải trí, Sản xuất bằng AI" in markdown
    assert "## Khả năng làm bằng AI\n" in markdown
    assert f"**Mức khả thi:** {label}\n" in markdown
    assert brief.ai_production.approach_vi in markdown
    for constraint in brief.ai_production.constraints_vi:
        assert f"- {constraint}\n" in markdown


def test_markdown_renders_legacy_assessment_fallback() -> None:
    markdown = to_markdown(make_sample_content_brief())

    assert "## Khả năng làm bằng AI\n\nChưa đánh giá khả năng làm bằng AI." in markdown


def test_json_round_trips_to_content_brief():
    brief = make_sample_content_brief(metadata_only=False)
    brief.focus_tags = ["phim_ngan", "giai_tri"]
    brief.ai_production = AIProduction(
        feasibility=AIFeasibility.MEDIUM,
        approach_vi="Tạo hình minh họa bằng AI và kiểm tra các chi tiết thực tế trước khi dựng video.",
        constraints_vi=["Xác minh nguồn."],
    )
    json_str = to_json(brief)

    # Valid JSON
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)
    assert parsed["id"] == brief.id
    assert parsed["focus_tags"] == ["phim_ngan", "giai_tri"]
    assert parsed["ai_production"] == brief.ai_production.model_dump(mode="json")

    # Round trip
    restored = ContentBrief.model_validate_json(json_str)
    assert restored == brief


def test_json_utf8_ensure_ascii_false():
    brief = make_sample_content_brief(metadata_only=False)
    json_str = to_json(brief)

    # Must contain unescaped Vietnamese characters
    assert "kỷ lục" in json_str
    assert "Việt Nam" in json_str
    assert "\\u" not in json_str  # ensure_ascii=False verified
