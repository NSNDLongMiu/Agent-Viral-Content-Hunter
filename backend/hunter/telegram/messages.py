"""Plain-text Vietnamese messages with an intact Dashboard link after truncation."""

from urllib.parse import urlsplit

from hunter.models import ContentBrief

_MAX_LENGTH = 4096
_DASHBOARD_LABEL = "Dashboard: "


def is_http_url(value: object) -> bool:
    if value is None:
        return False
    url = str(value)
    if any(character.isspace() or ord(character) < 32 for character in url):
        return False
    try:
        parts = urlsplit(url)
        return parts.scheme in ("http", "https") and bool(parts.hostname) and parts.username is None
    except ValueError:
        return False


def limit_text(message: str) -> str:
    """Count UTF-16 code units conservatively and preserve the final Dashboard line."""
    if len(message.encode("utf-16-le")) <= _MAX_LENGTH * 2:
        return message
    lines = message.rstrip().splitlines()
    dashboard_index = next(
        (
            index for index in range(len(lines) - 1, -1, -1)
            if lines[index].startswith(_DASHBOARD_LABEL)
            and is_http_url(lines[index].removeprefix(_DASHBOARD_LABEL))
        ),
        None,
    )
    suffix = "…"
    if dashboard_index is not None:
        suffix += f"\n\n{lines.pop(dashboard_index)}"
    remaining = _MAX_LENGTH * 2 - len(suffix.encode("utf-16-le"))
    if remaining < 0:
        raise ValueError("The Dashboard link exceeds Telegram's message limit")
    body = "\n".join(lines).encode("utf-16-le")[:remaining].decode("utf-16-le", errors="ignore")
    return body.rstrip() + suffix


def format_handoff(brief: ContentBrief, dashboard_url: str) -> str:
    """Format the essential production brief and its Dashboard detail URL."""
    if not is_http_url(dashboard_url):
        raise ValueError("A valid Dashboard URL is required")
    lines = [
        "BÀN GIAO SẢN XUẤT",
        brief.title_vi,
        f"Tiêu đề gốc: {brief.original_title}",
        f"Nền tảng: {brief.platform} | Loại nội dung: {brief.content_type}",
        f"Mức ưu tiên: {brief.priority} | Lan truyền: {brief.virality_score:g}/100"
        f" | Phù hợp: {brief.relevance_score:g}/100 | Tin cậy: {brief.credibility:g}/100",
        f"Nguồn: {brief.original_url}",
        f"Xác minh: {brief.verification_level}",
    ]
    if brief.creator:
        lines.append(f"Tác giả: {brief.creator}")
    if brief.metadata_only:
        lines.append(f"Lưu ý: {brief.metadata_note_vi}")
    lines.extend((f"\nTóm tắt: {brief.summary_vi}", f"\nVì sao đáng chú ý: {brief.why_notable}"))
    if brief.suggested_formats:
        lines.append("Gợi ý định dạng: " + ", ".join(brief.suggested_formats))
    if brief.risks_and_notes:
        lines.append("Rủi ro và lưu ý: " + " | ".join(brief.risks_and_notes))
    lines.append(f"\n{_DASHBOARD_LABEL}{dashboard_url}")
    return limit_text("\n".join(lines))
