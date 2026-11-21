"""GeminiBriefDrafter implementing the BriefDrafter protocol."""

from collections.abc import Sequence
from uuid import uuid4

from hunter.interfaces.ai import AIStatus, AITask, AIWorker
from hunter.interfaces.briefs import BriefDrafter, ScoringResult
from hunter.models.briefs import BriefContent
from hunter.models.sources import RawItem

from .prompts import (
    DRAFT_OUTPUT_SCHEMA,
    REQUIRED_WHY_NOTABLE_LABELS,
    build_corrective_instructions,
    build_draft_instructions,
)


def has_body_content(items: Sequence[RawItem]) -> bool:
    """Check if any raw item has full body text or transcript beyond title and metadata."""
    body_fields = ("body", "content", "text", "article_text", "full_text", "transcript", "description")
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


class GeminiBriefDrafter:
    """Produces validated Vietnamese content briefs using an injected AIWorker."""

    def __init__(self, ai_worker: AIWorker) -> None:
        self.ai_worker = ai_worker

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
            timeout_seconds=60.0,
        )

        result = await self.ai_worker.run(task)
        if result.status != AIStatus.OK or result.output is None:
            raise RuntimeError(
                f"AIWorker drafting failed with status {result.status}: {result.error or 'no output'}"
            )

        output = result.output

        # Validation check for summary word count and 7 why_notable labels
        summary_vi = str(output.get("summary_vi", "")).strip()
        summary_word_count = len(summary_vi.split())
        summary_valid = 50 <= summary_word_count <= 100

        why_notable = str(output.get("why_notable", "")).strip()
        missing_labels = [lbl for lbl in REQUIRED_WHY_NOTABLE_LABELS if lbl not in why_notable]
        labels_valid = len(missing_labels) == 0

        # If invalid, retry ONCE with corrective instructions
        if not summary_valid or not labels_valid:
            corrective_instructions = build_corrective_instructions(
                instructions,
                summary_word_count=summary_word_count if not summary_valid else None,
                missing_why_notable_labels=missing_labels if not labels_valid else [],
            )

            retry_task = AITask(
                id=f"draft-retry-{uuid4().hex}",
                instructions=corrective_instructions,
                input=evidence_input,
                output_schema=DRAFT_OUTPUT_SCHEMA,
                timeout_seconds=60.0,
            )

            retry_result = await self.ai_worker.run(retry_task)
            if retry_result.status != AIStatus.OK or retry_result.output is None:
                raise RuntimeError(
                    f"AIWorker drafting retry failed with status {retry_result.status}: "
                    f"{retry_result.error or 'no output'}"
                )

            output = retry_result.output
            summary_vi = str(output.get("summary_vi", "")).strip()
            summary_word_count = len(summary_vi.split())
            if not 50 <= summary_word_count <= 100:
                raise ValueError(
                    f"Summary word count out of range (50-100) after retry: got {summary_word_count} words"
                )

            why_notable = str(output.get("why_notable", "")).strip()
            missing_labels = [lbl for lbl in REQUIRED_WHY_NOTABLE_LABELS if lbl not in why_notable]
            if missing_labels:
                raise ValueError(
                    f"why_notable missing required labels after retry: {', '.join(missing_labels)}"
                )

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
        )
