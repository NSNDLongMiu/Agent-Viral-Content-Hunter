"""GeminiBriefDrafter implementing the BriefDrafter protocol."""

import math
from collections.abc import Sequence
from uuid import uuid4

from pydantic import JsonValue, ValidationError

from hunter.interfaces.ai import AIStatus, AITask, AIWorker
from hunter.interfaces.briefs import BriefDrafter, ScoringResult
from hunter.models.briefs import AIProduction, BriefContent
from hunter.models.sources import RawItem

from .prompts import (
    DRAFT_OUTPUT_SCHEMA,
    REQUIRED_WHY_NOTABLE_LABELS,
    build_corrective_instructions,
    build_draft_instructions,
)


def has_body_content(items: Sequence[RawItem]) -> bool:
    """Check if any raw item has full body text or transcript beyond title and metadata.

    `description` is deliberately not a body field: connectors store only a one-sentence teaser there.
    """
    body_fields = ("body", "content", "text", "article_text", "full_text", "transcript")
    for it in items:
        for field in body_fields:
            val = it.metadata.get(field)
            if isinstance(val, str) and val.strip():
                return True
    return False


def determine_verification_level(
    items: Sequence[RawItem],
    scores: ScoringResult,
) -> str:
    """Determine verification level grounded in independent evidence without inventing facts."""
    if scores.credibility <= 45.0:
        return "unverified (single source news/event claim)"
    distinct_sources = {it.source_id for it in items if it.source_id}
    num_sources = len(distinct_sources)
    if num_sources >= 2:
        return f"corroborated by {num_sources} sources (not independently fact-checked)"
    return "single_source"


def _parse_ai_production(value: JsonValue) -> AIProduction | None:
    try:
        production = AIProduction.model_validate(value)
    except ValidationError:
        return None
    return production if 15 <= len(production.approach_vi.split()) <= 80 else None


class GeminiBriefDrafter:
    """Produces validated Vietnamese content briefs using an injected AIWorker."""

    def __init__(self, ai_worker: AIWorker, timeout_seconds: float = 180.0) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("Draft timeout must be positive and finite")
        self.ai_worker = ai_worker
        self.timeout_seconds = timeout_seconds

    async def _request_output(self, task: AITask, *, retry: bool) -> dict[str, JsonValue] | None:
        """Return None for a schema rejection or an indistinguishable generic CLI failure."""
        try:
            result = await self.ai_worker.run(task)
        except ValueError as error:
            if str(error) == "AI output failed task schema validation":
                return None
            raise

        if result.status == AIStatus.OK:
            return result.output
        # GeminiAdapter converts schema validation errors to the generic ERROR diagnostic.
        if result.status == AIStatus.ERROR and result.error == "The AI task failed.":
            return None
        stage = "drafting retry" if retry else "drafting"
        raise RuntimeError(f"AIWorker {stage} failed with status {result.status}: {result.error or 'no output'}")

    async def draft(
        self,
        items: Sequence[RawItem],
        scores: ScoringResult,
        *,
        feedback: str | None = None,
    ) -> BriefContent:
        """Draft or revise a brief with evidence and disclose any metadata-only summary."""
        if not items:
            raise ValueError("At least one RawItem is required for brief drafting")

        primary = items[0]
        metadata_only = not has_body_content(items)

        # Build evidence payload
        evidence_input = {
            "primary": {
                "source_id": primary.source_id,
                "source_url": str(primary.source_url),
                "title": primary.title or "Untitled",
                "creator": primary.creator,
                "published_at": primary.published_at.isoformat() if primary.published_at else None,
                "fetched_at": primary.fetched_at.isoformat(),
                "metrics": primary.metrics.model_dump(exclude_none=True) if primary.metrics else {},
                "metadata": primary.metadata,
            },
            "related_count": len(items) - 1,
            "metadata_only": metadata_only,
            "scores": {
                "virality": scores.virality,
                "relevance": scores.relevance,
                "credibility": scores.credibility,
                "priority": scores.priority.value,
                "explanation": scores.explanation,
            },
            "feedback": feedback,
        }

        instructions = build_draft_instructions(
            items,
            scores,
            metadata_only=metadata_only,
            feedback=feedback,
        )

        task = AITask(
            id=f"draft-{uuid4().hex}",
            instructions=instructions,
            input=evidence_input,
            output_schema=DRAFT_OUTPUT_SCHEMA,
            timeout_seconds=self.timeout_seconds,
        )

        retry = False
        while True:
            output = await self._request_output(task, retry=retry)
            if output is None:
                if retry:
                    raise ValueError("Draft output failed schema validation or was unavailable after retry")
                corrections = build_corrective_instructions(instructions, invalid_output_schema=True)
            else:
                summary_vi = str(output.get("summary_vi", "")).strip()
                summary_word_count = len(summary_vi.split())
                summary_valid = 50 <= summary_word_count <= 100
                why_notable = str(output.get("why_notable", "")).strip()
                missing_labels = [lbl for lbl in REQUIRED_WHY_NOTABLE_LABELS if lbl not in why_notable]
                ai_production = _parse_ai_production(output.get("ai_production"))

                if summary_valid and not missing_labels and ai_production is not None:
                    break
                if retry:
                    if not summary_valid:
                        raise ValueError(
                            f"Summary word count out of range (50-100) after retry: got {summary_word_count} words"
                        )
                    if missing_labels:
                        raise ValueError(
                            f"why_notable missing required labels after retry: {', '.join(missing_labels)}"
                        )
                    raise ValueError("Invalid ai_production after retry")

                corrections = build_corrective_instructions(
                    instructions,
                    summary_word_count=summary_word_count,
                    missing_why_notable_labels=missing_labels,
                    invalid_ai_production=ai_production is None,
                )
            task = task.model_copy(update={"id": f"draft-retry-{uuid4().hex}", "instructions": corrections})
            retry = True

        # Code-owned fields copied from evidence/scores; AI cannot overwrite them
        original_title = primary.title or "Untitled"
        original_url = primary.source_url
        related_urls = [
            it.source_url
            for it in items[1:]
            if str(it.source_url) != str(primary.source_url)
        ]

        # Honesty fix: platform from metadata['platform'] or 'không rõ nền tảng'
        meta_plat = primary.metadata.get("platform")
        platform = str(meta_plat).strip() if isinstance(meta_plat, str) and meta_plat.strip() else "không rõ nền tảng"

        original_language = str(
            primary.metadata.get("language")
            or primary.metadata.get("original_language")
            or "unknown"
        )

        # Honesty fix: content_type from metadata['content_type'] or 'không xác định'
        meta_ct = primary.metadata.get("content_type")
        content_type = str(meta_ct).strip() if isinstance(meta_ct, str) and meta_ct.strip() else "không xác định"

        published_at = primary.published_at
        discovered_at = primary.fetched_at
        creator = primary.creator
        engagement_metrics = primary.metrics

        # Ensure metrics_snapshot_at is populated if engagement metrics exist
        if engagement_metrics and engagement_metrics.model_dump(exclude_none=True):
            metrics_snapshot_at = primary.metrics_snapshot_at or primary.fetched_at
        else:
            metrics_snapshot_at = None

        virality_score = scores.virality
        relevance_score = scores.relevance
        credibility = scores.credibility
        priority = scores.priority
        score_explanation = scores.explanation
        verification_level = determine_verification_level(items, scores)

        # Handle metadata disclosure
        if metadata_only:
            ai_note = str(output.get("metadata_note_vi") or "").strip()
            metadata_note_vi = (
                ai_note
                if ai_note
                else "Tóm tắt được tạo dựa trên siêu dữ liệu (metadata), chưa xem đầy đủ nội dung gốc."
            )
        else:
            metadata_note_vi = None

        # AI-authored fields
        title_vi = str(output.get("title_vi") or original_title).strip()

        # Honesty fix: risks_and_notes disclosure when empty
        risks_and_notes = [
            str(r).strip()
            for r in output.get("risks_and_notes", [])
            if str(r).strip()
        ]
        if not risks_and_notes:
            risks_and_notes = ["Chưa có đánh giá rủi ro từ AI; người duyệt cần kiểm tra."]

        # Honesty fix: suggested_formats returns empty list if AI returns none
        suggested_formats = [
            str(f).strip()
            for f in output.get("suggested_formats", [])
            if str(f).strip()
        ]

        return BriefContent(
            title_vi=title_vi,
            original_title=original_title,
            content_type=content_type,
            platform=platform,
            original_language=original_language,
            published_at=published_at,
            discovered_at=discovered_at,
            creator=creator,
            summary_vi=summary_vi,
            why_notable=why_notable,
            virality_score=virality_score,
            relevance_score=relevance_score,
            credibility=credibility,
            priority=priority,
            original_url=original_url,
            related_urls=related_urls,
            engagement_metrics=engagement_metrics,
            metrics_snapshot_at=metrics_snapshot_at,
            verification_level=verification_level,
            risks_and_notes=risks_and_notes,
            suggested_formats=suggested_formats,
            metadata_only=metadata_only,
            metadata_note_vi=metadata_note_vi,
            score_explanation=score_explanation,
            focus_tags=scores.focus_tags,
            ai_production=ai_production,
        )
