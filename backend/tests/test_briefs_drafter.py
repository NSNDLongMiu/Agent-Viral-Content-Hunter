"""Unit tests for GeminiBriefDrafter."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import HttpUrl, JsonValue

from hunter.ai import GeminiAdapter
from hunter.ai.cli_runner import RunResult
from hunter.interfaces.ai import AIHealth, AIResult, AIStatus, AITask
from hunter.interfaces.briefs import ScoringResult
from hunter.models.briefs import Priority
from hunter.models.jobs import AIName
from hunter.models.sources import MetricSnapshot, RawItem
from hunter.briefs.drafter import GeminiBriefDrafter, determine_verification_level, has_body_content
from hunter.briefs.prompts import (
    DRAFT_OUTPUT_SCHEMA,
    REQUIRED_WHY_NOTABLE_LABELS,
    build_draft_instructions,
)

from .test_ai_adapters import FakeRunner


def make_vietnamese_text(n_words: int) -> str:
    """Generate a Vietnamese string with exact word count."""
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


VALID_WHY_NOTABLE = (
    "Hook: Giữ chân người xem trong 3 giây đầu bằng hiệu ứng bất ngờ.\n"
    "Định dạng: Video ngắn nhịp độ nhanh kèm phụ đề nổi bật.\n"
    "Cảm xúc / động lực chia sẻ: Tò mò và ngạc nhiên trước công nghệ mới.\n"
    "Nhóm người xem: Giới trẻ và người làm sáng tạo nội dung.\n"
    "Thời điểm: Bắt đúng làn sóng AI đang thịnh hành.\n"
    "Khả năng khai thác ở Việt Nam: Rất cao, khán giả Việt Nam yêu thích công nghệ.\n"
    "Bài học áp dụng (không sao chép): Tập trung vào giải quyết vấn đề thực tế."
)
VALID_AI_PRODUCTION: dict[str, JsonValue] = {
    "feasibility": "CAO",
    "approach_vi": (
        "Tạo ảnh minh họa cho một câu chuyện hư cấu rồi chuyển thành video ngắn có giọng đọc AI."
    ),
    "constraints_vi": ["Kiểm tra quy định gắn nhãn nội dung tạo bởi AI."],
}


class FakeAIWorker:
    """Configurable fake AIWorker for unit tests."""

    def __init__(
        self,
        responses: list[dict[str, JsonValue] | AIResult] | None = None,
        *,
        validate_schema: bool = True,
    ) -> None:
        self.responses = list(responses or [])
        self.recorded_tasks: list[AITask] = []
        self.validate_schema = validate_schema

    @property
    def name(self) -> AIName:
        return AIName.GEMINI

    async def run(self, task: AITask) -> AIResult:
        self.recorded_tasks.append(task)
        if not self.responses:
            raise RuntimeError("No remaining responses in FakeAIWorker")
        resp = self.responses.pop(0)
        if isinstance(resp, AIResult):
            return resp
        if self.validate_schema:
            return AIResult.success(task, resp)
        return AIResult(status=AIStatus.OK, output=resp)

    def health(self) -> AIHealth:
        return AIHealth(
            name=AIName.GEMINI,
            status=AIStatus.OK,
            available=True,
            quota_exhausted=False,
            checked_at=datetime.now(UTC),
        )


def make_test_item(*, has_body: bool = False, metadata: dict | None = None) -> RawItem:
    now = datetime.now(UTC)
    meta = {
        "platform": "tiktok",
        "language": "vi",
        "content_type": "video",
    }
    if has_body:
        meta["body"] = "Nội dung bài viết chi tiết đầy đủ..."
    if metadata:
        meta.update(metadata)
    return RawItem(
        source_id="tiktok",
        source_url=HttpUrl("https://example.com/item/100"),
        external_id="item-100",
        title="Tiêu đề gốc tiếng Anh Original Video",
        creator="Original Creator",
        published_at=now - timedelta(hours=2),
        fetched_at=now,
        metrics=MetricSnapshot(views=200_000, likes=20_000, shares=2_000, comments=1_000),
        metrics_snapshot_at=now,
        metadata=meta,
    )


def make_test_scores() -> ScoringResult:
    return ScoringResult(
        virality=88.5,
        relevance=82.0,
        credibility=80.0,
        priority=Priority.P1,
        explanation="Điểm cao, thỏa mãn điều kiện P1",
        focus_tags=["ai_san_xuat", "micro_drama"],
    )


def test_code_owned_fields_cannot_be_overridden_by_ai():
    item = make_test_item(has_body=False)
    scores = make_test_scores()

    task = AITask(
        id="schema-test",
        instructions="Draft brief",
        input={},
        output_schema=DRAFT_OUTPUT_SCHEMA,
    )

    # (a) Verify an AIResult containing code-owned fields is rejected by schema validation
    malicious_output = {
        "title_vi": "Tiêu đề tiếng Việt chuẩn",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Lưu ý bản quyền"],
        "suggested_formats": ["Video ngắn 60s"],
        "ai_production": VALID_AI_PRODUCTION,
        "focus_tags": ["giai_tri"],
        "original_url": "https://malicious.com",
        "priority": "P3",
        "platform": "fake_platform",
        "virality_score": 10.0,
    }
    with pytest.raises(ValueError, match="AI output failed task schema validation"):
        AIResult.success(task, malicious_output)

    # (b) Even if a worker skips schema validation, AI-authored tags cannot replace score tags.
    valid_output = {
        "title_vi": "Tiêu đề tiếng Việt chuẩn",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Lưu ý bản quyền nhạc nền"],
        "suggested_formats": ["Video ngắn 60s"],
        "metadata_note_vi": "Tóm tắt từ metadata",
        "ai_production": VALID_AI_PRODUCTION,
        "focus_tags": ["giai_tri"],
    }
    fake_worker = FakeAIWorker([valid_output], validate_schema=False)
    drafter = GeminiBriefDrafter(fake_worker)
    brief = asyncio.run(drafter.draft([item], scores))

    assert brief.original_title == item.title
    assert brief.original_url == item.source_url
    assert brief.platform == item.metadata["platform"]
    assert brief.creator == item.creator
    assert brief.published_at == item.published_at
    assert brief.discovered_at == item.fetched_at
    assert brief.virality_score == scores.virality
    assert brief.relevance_score == scores.relevance
    assert brief.credibility == scores.credibility
    assert brief.priority == scores.priority
    assert brief.score_explanation == scores.explanation
    assert brief.focus_tags == scores.focus_tags
    assert brief.engagement_metrics == item.metrics
    assert brief.metrics_snapshot_at == item.metrics_snapshot_at


def test_summary_word_count_50_to_100_passes():
    item = make_test_item()
    scores = make_test_scores()

    valid_output = {
        "title_vi": "Tiêu đề tiếng Việt",
        "summary_vi": make_vietnamese_text(65),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Không có rủi ro"],
        "suggested_formats": ["Shorts"],
        "metadata_note_vi": "Tóm tắt từ metadata",
        "ai_production": VALID_AI_PRODUCTION,
    }

    fake_worker = FakeAIWorker([valid_output])
    drafter = GeminiBriefDrafter(fake_worker)

    brief = asyncio.run(drafter.draft([item], scores))
    assert len(brief.summary_vi.split()) == 65
    assert brief.ai_production is not None
    assert brief.ai_production.model_dump(mode="json") == VALID_AI_PRODUCTION
    assert len(fake_worker.recorded_tasks) == 1
    assert fake_worker.recorded_tasks[0].timeout_seconds == 180.0


def test_summary_word_count_out_of_range_single_retry_success():
    item = make_test_item()
    scores = make_test_scores()

    # Attempt 1: Too short (20 words)
    too_short_output = {
        "title_vi": "Tiêu đề tiếng Việt",
        "summary_vi": make_vietnamese_text(20),
        "ai_production": VALID_AI_PRODUCTION,
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Không có"],
        "suggested_formats": ["Shorts"],
        "metadata_note_vi": "Tóm tắt từ metadata",
    }

    # Attempt 2: Fixed length (70 words)
    valid_retry_output = {
        "title_vi": "Tiêu đề tiếng Việt đã sửa",
        "summary_vi": make_vietnamese_text(70),
        "ai_production": VALID_AI_PRODUCTION,
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Không có"],
        "suggested_formats": ["Shorts"],
        "metadata_note_vi": "Tóm tắt từ metadata",
    }

    fake_worker = FakeAIWorker([too_short_output, valid_retry_output])
    timeout_seconds = 90.5
    drafter = GeminiBriefDrafter(fake_worker, timeout_seconds=timeout_seconds)

    brief = asyncio.run(drafter.draft([item], scores))
    assert len(brief.summary_vi.split()) == 70
    assert [task.timeout_seconds for task in fake_worker.recorded_tasks] == [timeout_seconds] * 2
    assert "CẢNH BÁO SỬA LỖI" in fake_worker.recorded_tasks[1].instructions


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0, float("inf"), float("-inf"), float("nan")])
def test_invalid_draft_timeout_is_rejected(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="positive and finite"):
        GeminiBriefDrafter(FakeAIWorker(), timeout_seconds=timeout_seconds)


def test_summary_word_count_still_invalid_after_retry_raises_error():
    item = make_test_item()
    scores = make_test_scores()

    output1 = {
        "title_vi": "Tiêu đề 1",
        "summary_vi": make_vietnamese_text(25),
        "ai_production": VALID_AI_PRODUCTION,
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["K"],
        "suggested_formats": ["S"],
        "metadata_note_vi": "M",
    }
    output2 = {
        "title_vi": "Tiêu đề 2",
        "summary_vi": make_vietnamese_text(30),  # Still too short!
        "ai_production": VALID_AI_PRODUCTION,
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["K"],
        "suggested_formats": ["S"],
        "metadata_note_vi": "M",
    }

    fake_worker = FakeAIWorker([output1, output2])
    drafter = GeminiBriefDrafter(fake_worker)

    with pytest.raises(ValueError, match="Summary word count out of range"):
        asyncio.run(drafter.draft([item], scores))


def test_why_notable_missing_labels_triggers_retry():
    item = make_test_item()
    scores = make_test_scores()

    # Attempt 1: Missing "Bài học áp dụng (không sao chép):"
    incomplete_why_notable = (
        "Hook: Giữ chân trong 3s.\n"
        "Định dạng: Video ngắn.\n"
        "Cảm xúc / động lực chia sẻ: Tò mò.\n"
        "Nhóm người xem: Giới trẻ.\n"
        "Thời điểm: Đúng xu hướng.\n"
        "Khả năng khai thác ở Việt Nam: Tiềm năng cao."
    )
    output1 = {
        "title_vi": "Tiêu đề",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": incomplete_why_notable,
        "ai_production": VALID_AI_PRODUCTION,
        "risks_and_notes": ["K"],
        "suggested_formats": ["S"],
        "metadata_note_vi": "M",
    }

    output2 = {
        "title_vi": "Tiêu đề sửa",
        "ai_production": VALID_AI_PRODUCTION,
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["K"],
        "suggested_formats": ["S"],
        "metadata_note_vi": "M",
    }

    fake_worker = FakeAIWorker([output1, output2])
    drafter = GeminiBriefDrafter(fake_worker)

    brief = asyncio.run(drafter.draft([item], scores))
    assert len(fake_worker.recorded_tasks) == 2
    for label in REQUIRED_WHY_NOTABLE_LABELS:
        assert label in brief.why_notable


def fake_draft_output() -> dict[str, JsonValue]:
    return {
        "title_vi": "Tiêu đề kiểm thử",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": [],
        "suggested_formats": [],
        "ai_production": VALID_AI_PRODUCTION,
    }


@pytest.mark.parametrize(
    "change",
    [
        {"feasibility": "VERY_HIGH"},
        {"approach_vi": make_vietnamese_text(14)},
        {"approach_vi": make_vietnamese_text(81)},
        {"constraints_vi": []},
        {"constraints_vi": ["Kiểm tra bản quyền.", " \t "]},
        None,
    ],
    ids=["bad-enum", "14-words", "81-words", "empty-constraints", "blank-constraint", "missing"],
)
def test_invalid_ai_production_is_retried_once_and_rejected(change: dict[str, JsonValue] | None) -> None:
    output = fake_draft_output()
    if change is None:
        del output["ai_production"]
    else:
        output["ai_production"] = {**VALID_AI_PRODUCTION, **change}
    worker = FakeAIWorker([output, output], validate_schema=False)

    with pytest.raises(ValueError, match="Invalid ai_production after retry"):
        asyncio.run(GeminiBriefDrafter(worker).draft([make_test_item()], make_test_scores()))

    first, retry = worker.recorded_tasks
    assert first.output_schema == retry.output_schema == DRAFT_OUTPUT_SCHEMA
    assert "LỖI KHẢ NĂNG LÀM BẰNG AI" in retry.instructions


@pytest.mark.parametrize("word_count", [15, 80])
def test_production_word_count_boundaries_pass(word_count: int) -> None:
    output = fake_draft_output()
    approach = make_vietnamese_text(word_count).replace(" ", "\t")
    output["ai_production"] = {**VALID_AI_PRODUCTION, "approach_vi": approach}
    worker = FakeAIWorker([output])

    brief = asyncio.run(GeminiBriefDrafter(worker).draft([make_test_item()], make_test_scores()))

    assert brief.ai_production is not None
    assert brief.ai_production.approach_vi == approach
    assert len(worker.recorded_tasks) == 1


def test_worker_schema_rejection_can_recover_on_retry() -> None:
    output = fake_draft_output()
    del output["ai_production"]
    worker = FakeAIWorker([output, fake_draft_output()])

    brief = asyncio.run(GeminiBriefDrafter(worker).draft([make_test_item()], make_test_scores()))

    assert brief.ai_production is not None
    assert brief.ai_production.model_dump(mode="json") == VALID_AI_PRODUCTION
    assert len(worker.recorded_tasks) == 2
    assert "LỖI ĐỊNH DẠNG" in worker.recorded_tasks[1].instructions


def test_gemini_adapter_retries_an_output_rejected_by_schema() -> None:
    output = fake_draft_output()
    del output["ai_production"]
    runner = FakeRunner(*(
        RunResult(0, json.dumps({"status": "SUCCESS", "structured_output": response}))
        for response in (output, fake_draft_output())
    ))
    adapter = GeminiAdapter(executable="fake-agy", runner=runner)

    brief = asyncio.run(GeminiBriefDrafter(adapter).draft([make_test_item()], make_test_scores()))

    assert brief.ai_production is not None
    assert brief.ai_production.model_dump(mode="json") == VALID_AI_PRODUCTION
    _, retry_call = runner.calls
    argv, _, _, _ = retry_call
    assert "LỖI ĐỊNH DẠNG" in argv[argv.index("-p") + 1]


def test_worker_quota_error_stops_without_retry() -> None:
    worker = FakeAIWorker([AIResult(status=AIStatus.QUOTA_EXHAUSTED, error="BLOCKED (quota)")])

    with pytest.raises(RuntimeError, match="QUOTA_EXHAUSTED"):
        asyncio.run(GeminiBriefDrafter(worker).draft([make_test_item()], make_test_scores()))

    assert len(worker.recorded_tasks) == 1


def test_metadata_only_disclosure_honesty():
    # Item without body -> metadata_only is True
    item_no_body = make_test_item(has_body=False)
    scores = make_test_scores()

    output = {
        "ai_production": VALID_AI_PRODUCTION,
        "title_vi": "Tiêu đề",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Rủi ro bản quyền"],
        "suggested_formats": ["Shorts"],
        "metadata_note_vi": "Tóm tắt từ thông tin siêu dữ liệu, chưa xem toàn bộ video gốc.",
    }

    fake_worker = FakeAIWorker([output])
    drafter = GeminiBriefDrafter(fake_worker)

    brief = asyncio.run(drafter.draft([item_no_body], scores))
    assert brief.metadata_only is True
    assert brief.metadata_note_vi is not None
    assert "chưa xem" in brief.metadata_note_vi.lower() or "metadata" in brief.metadata_note_vi.lower()


def test_non_metadata_only_when_body_present():
    # Item with body -> metadata_only is False
    item_with_body = make_test_item(has_body=True)
    scores = make_test_scores()

    output = {
        "ai_production": VALID_AI_PRODUCTION,
        "title_vi": "Tiêu đề",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Rủi ro bản quyền"],
        "suggested_formats": ["Shorts"],
        "metadata_note_vi": None,
    }

    fake_worker = FakeAIWorker([output])
    drafter = GeminiBriefDrafter(fake_worker)

    brief = asyncio.run(drafter.draft([item_with_body], scores))
    assert brief.metadata_only is False
    assert brief.metadata_note_vi is None


def test_feedback_passed_through_to_instructions():
    item = make_test_item()
    scores = make_test_scores()

    output = {
        "ai_production": VALID_AI_PRODUCTION,
        "title_vi": "Tiêu đề sửa lại",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": ["Không có"],
        "suggested_formats": ["Reels"],
        "metadata_note_vi": "Tóm tắt từ metadata",
    }

    fake_worker = FakeAIWorker([output])
    drafter = GeminiBriefDrafter(fake_worker)

    revision_feedback = "Tập trung phân tích kỹ hơn về thuật toán trong phần why_notable"
    brief = asyncio.run(drafter.draft([item], scores, feedback=revision_feedback))

    assert brief.focus_tags == scores.focus_tags
    assert brief.ai_production is not None
    assert brief.ai_production.model_dump(mode="json") == VALID_AI_PRODUCTION
    assert len(fake_worker.recorded_tasks) == 1
    task_instructions = fake_worker.recorded_tasks[0].instructions
    assert "[YÊU CẦU SỬA ĐỔI TỪ CLAUDE LEADER (REVISION FEEDBACK)]" in task_instructions
    assert revision_feedback in task_instructions


def test_prompt_injection_guard_present_in_instructions():
    item = make_test_item()
    scores = make_test_scores()

    instructions = build_draft_instructions(
        [item],
        scores,
        metadata_only=True,
    )

    assert "PROMPT-INJECTION GUARD" in instructions
    assert "untrusted DATA" in instructions
    assert "bằng các nhóm công cụ" in instructions
    assert "chuyển ảnh thành video" in instructions
    assert "TUYỆT ĐỐI KHÔNG đề xuất tái tạo khuôn mặt hoặc giọng nói của người thật" in instructions
    assert "sao chép nhân vật, cảnh hoặc tập phim có bản quyền" in instructions
    assert "khiến người xem tưởng đó là cảnh quay thật" in instructions
    assert "feasibility phải là THAP hoặc TRUNG_BINH" in instructions


def test_honesty_fallbacks_for_content_type_and_platform():
    # Item missing platform and content_type in metadata
    item = make_test_item(metadata={"platform": "", "content_type": ""})
    scores = make_test_scores()

    output = {
        "ai_production": VALID_AI_PRODUCTION,
        "title_vi": "Tiêu đề",
        "summary_vi": make_vietnamese_text(60),
        "why_notable": VALID_WHY_NOTABLE,
        "risks_and_notes": [],
        "suggested_formats": [],
        "metadata_note_vi": "Tóm tắt từ metadata",
    }

    fake_worker = FakeAIWorker([output])
    drafter = GeminiBriefDrafter(fake_worker)

    brief = asyncio.run(drafter.draft([item], scores))

    assert brief.content_type == "không xác định"
    assert brief.platform == "không rõ nền tảng"
    assert brief.risks_and_notes == ["Chưa có đánh giá rủi ro từ AI; người duyệt cần kiểm tra."]
    assert brief.suggested_formats == []


def test_determine_verification_level_never_outputs_verified():
    now = datetime.now(UTC)
    scores = make_test_scores()

    # Single source
    item1 = make_test_item()
    level1 = determine_verification_level([item1], scores)
    assert level1 == "single_source"
    assert "verified" not in level1

    # Two distinct sources: corroborated, NOT verified
    item2 = RawItem(
        source_id="wikimedia",
        source_url=HttpUrl("https://en.wikipedia.org/wiki/Item"),
        title="Wiki Item",
        published_at=now,
        fetched_at=now,
    )
    level2 = determine_verification_level([item1, item2], scores)
    assert level2 == "corroborated by 2 sources (not independently fact-checked)"
    assert "verified" not in level2

    # Low credibility news claim: unverified
    low_cred_scores = ScoringResult(
        virality=80.0,
        relevance=80.0,
        credibility=40.0,
        priority=Priority.P2,
        explanation="Low credibility",
    )
    level_low = determine_verification_level([item1], low_cred_scores)
    assert level_low == "unverified (single source news/event claim)"


def test_one_sentence_description_is_not_body_content() -> None:
    """RSS connectors store a one-sentence teaser as `description`; that must still count as metadata only."""
    teaser = make_test_item(metadata={"description": "Một câu mô tả ngắn lấy từ RSS."})
    assert not has_body_content([teaser])
    assert has_body_content([make_test_item(metadata={"body": "Toàn văn bài viết."})])
    assert has_body_content([make_test_item(metadata={"transcript": "Phụ đề của video."})])
