"""Markdown and JSON rendering for ContentBrief objects."""

import json

from hunter.models.briefs import AIFeasibility, ContentBrief, FocusTag

AI_FEASIBILITY_LABELS = {
    AIFeasibility.HIGH: "Cao",
    AIFeasibility.MEDIUM: "Trung bình",
    AIFeasibility.LOW: "Thấp",
}
FOCUS_TAG_LABELS: dict[FocusTag, str] = {
    "phim_ngan": "Phim ngắn",
    "micro_drama": "Micro-drama",
    "giai_tri": "Giải trí",
    "ai_san_xuat": "Sản xuất bằng AI",
}


def to_markdown(brief: ContentBrief) -> str:
    """Render a ContentBrief as a readable Vietnamese Markdown document."""
    lines: list[str] = [
        f"# [Hồ sơ #{brief.id}] {brief.title_vi}",
        "",
        "## 1. Thông tin chung",
        f"- **ID hồ sơ:** {brief.id}",
        f"- **Tiêu đề tiếng Việt:** {brief.title_vi}",
        f"- **Tiêu đề gốc:** {brief.original_title}",
        f"- **Loại nội dung:** {brief.content_type}",
        f"- **Nền tảng:** {brief.platform}",
        f"- **Ngôn ngữ gốc:** {brief.original_language}",
        f"- **Tác giả / Kênh:** {brief.creator or 'Không rõ'}",
        f"- **Thời gian đăng:** {brief.published_at.isoformat() if brief.published_at else 'Không có dữ liệu'}",
        f"- **Thời gian phát hiện:** {brief.discovered_at.isoformat()}",
        f"- **URL nguồn gốc:** [{brief.original_url}]({brief.original_url})",
    ]
    focus_labels = ", ".join(FOCUS_TAG_LABELS[tag] for tag in brief.focus_tags)
    lines.append(f"- **Nhãn trọng tâm:** {focus_labels or 'Không có'}")

    if brief.related_urls:
        lines.append("- **URL nguồn liên quan:**")
        for u in brief.related_urls:
            lines.append(f"  - [{u}]({u})")
    else:
        lines.append("- **URL nguồn liên quan:** Không có")

    lines.extend([
        "",
        "## 2. Điểm số & Đánh giá",
        f"- **Virality Score:** {brief.virality_score:.1f}/100",
        f"- **Relevance Score:** {brief.relevance_score:.1f}/100",
        f"- **Credibility:** {brief.credibility:.1f}/100",
        f"- **Mức ưu tiên (Priority):** {brief.priority.value}",
        f"- **Mức độ xác minh:** {brief.verification_level}",
    ])

    if brief.score_explanation:
        lines.extend([
            "- **Giải thích chấm điểm:**",
            f"  {brief.score_explanation}",
        ])

    lines.extend([
        "",
        "## 3. Tóm tắt nội dung (50–100 từ)",
    ])

    if brief.metadata_only:
        note = brief.metadata_note_vi or "Tóm tắt từ metadata, chưa xem nội dung đầy đủ."
        lines.extend([
            f"> ⚠️ **LƯU Ý MINH BẠCH (METADATA-ONLY):** {note}",
            "",
        ])

    word_count = len(brief.summary_vi.split())
    lines.extend([
        brief.summary_vi,
        "",
        f"*(Độ dài: {word_count} từ)*",
        "",
        "## 4. Lý do nội dung đáng chú ý (Reverse-engineer the niche)",
        brief.why_notable,
        "",
        "## 5. Chỉ số tương tác & Dữ liệu quan sát",
    ])

    if brief.engagement_metrics:
        m = brief.engagement_metrics
        lines.extend([
            f"- **Lượt xem (Views):** {f'{m.views:,}' if m.views is not None else 'N/A'}",
            f"- **Lượt thích (Likes):** {f'{m.likes:,}' if m.likes is not None else 'N/A'}",
            f"- **Lượt chia sẻ (Shares):** {f'{m.shares:,}' if m.shares is not None else 'N/A'}",
            f"- **Lượt bình luận (Comments):** {f'{m.comments:,}' if m.comments is not None else 'N/A'}",
        ])
    else:
        lines.append("- **Chỉ số tương tác:** Không thu thập được số liệu (metadata-only)")

    lines.append(
        f"- **Thời điểm ghi nhận chỉ số:** "
        f"{brief.metrics_snapshot_at.isoformat() if brief.metrics_snapshot_at else 'N/A'}"
    )

    lines.extend([
        "",
        "## 6. Rủi ro & Lưu ý",
    ])
    for r in brief.risks_and_notes:
        lines.append(f"- {r}")

    lines.extend([
        "",
        "## 7. Gợi ý định dạng khai thác (Original Content)",
    ])
    for f in brief.suggested_formats:
        lines.append(f"- {f}")

    lines.extend(["", "## Khả năng làm bằng AI", ""])
    production = brief.ai_production
    if production is None:
        lines.append("Chưa đánh giá khả năng làm bằng AI.")
    else:
        lines.extend([
            f"**Mức khả thi:** {AI_FEASIBILITY_LABELS[production.feasibility]}",
            "",
            production.approach_vi,
            "",
            "**Ràng buộc**",
            "",
        ])
        lines.extend(f"- {constraint}" for constraint in production.constraints_vi)

    lines.extend([
        "",
        "## 8. Trạng thái kiểm duyệt & Bàn giao",
        f"- **Trạng thái kiểm duyệt:** {brief.status.value} (Số vòng sửa: {brief.revision_count}/2)",
        f"- **Trạng thái bàn giao:** {brief.handoff_status.value}",
        f"- **Khởi tạo lúc:** {brief.created_at.isoformat()}",
        f"- **Cập nhật lúc:** {brief.updated_at.isoformat()}",
    ])

    return "\n".join(lines)


def to_json(brief: ContentBrief) -> str:
    """Serialize ContentBrief to stable, pretty-printed UTF-8 JSON."""
    data = brief.model_dump(mode="json")
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
