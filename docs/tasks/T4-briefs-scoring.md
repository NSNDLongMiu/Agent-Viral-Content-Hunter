# T4 — Briefs + Scoring (Gemini)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. You have NO shell: use only file view/create/edit tools; the orchestrator runs tests and sends you errors. Read `idead.md` §8, §9, §10, §11 and the contracts: `backend/hunter/interfaces/briefs.py`, `backend/hunter/interfaces/ai.py`, `backend/hunter/models/briefs.py`, `backend/hunter/models/sources.py`, `backend/hunter/models/common.py`.

## Goal
Rule-based scoring and Vietnamese brief drafting that plug into the existing protocols (`Scorer`, `BriefDrafter`), plus Markdown/JSON rendering. Scores must be explainable and never invented.

## Files you may touch (ONLY)
- `backend/hunter/scoring/**`, `backend/hunter/briefs/**`
- `backend/tests/test_scoring_*.py`, `backend/tests/test_briefs_*.py`

## 1. Scoring — `scoring/rules.py` (`RuleScorer` implements `Scorer`)
Return `ScoringResult(virality, relevance, credibility, priority, explanation)` — four independent signals, never merged into one number (§8). Use the `Score` type exactly as `models/briefs.py` defines it.
- **Virality** from observed metrics only (views/likes/shares/comments; `metadata` signals such as `hn_score` or `search_traffic_label`), log-scaled and compared against configurable reference values per platform kind; growth rate ONLY when two snapshots of the same item are provided (otherwise say "single snapshot: no growth rate"). Cross-source corroboration (same story in several sources) raises it. If an item has no engagement data at all, virality is low-confidence: compute from the available signals and state in `explanation` that no engagement metrics were available. NEVER fabricate numbers.
- **Relevance** to Vietnamese audience and configured topic preferences: simple, transparent keyword/topic tables (Vietnamese + English + Chinese terms) in a config dataclass, freshness decay from `published_at`, language hints. Priority topics boost, excluded topics suppress (configurable).
- **Credibility** from source reliability (a table keyed by connector/source id: official APIs high, aggregators medium, unknown low), number of independent corroborating sources, and whether the claim type needs verification (news/event claims need ≥2 independent sources else flagged unverified).
- **Priority** — `ScoringThresholds` dataclass (defaults P1 ≥ 85, P2 ≥ 60, else P3; adjustable). P1 requires ALL of: score ≥ threshold, traceable source URL, a notable signal, fresh enough (configurable hours), not flagged duplicate, risk check passed, and verification satisfied for news/event claims. If a condition is missing, cap at P2 and list exactly what is missing in `explanation`.
- A single combined ranking number is allowed only as an internal sort key; it must not be exposed as a score.
- Everything deterministic and unit-testable; weights are named constants in one place.

## 2. Brief drafting — `briefs/` (`GeminiBriefDrafter` implements `BriefDrafter`)
The drafter takes an injected `AIWorker` (from T3; tests use a fake implementing the protocol) and builds an `AITask` with `instructions`, `input` (the evidence from `RawItem`s) and an `output_schema` (JSON Schema Draft 2020-12) for ONLY the text fields the AI may write: `title_vi`, `summary_vi`, `why_notable`, `risks_and_notes`, `suggested_formats`, `metadata_note_vi`.
- **Code-owned fields** (`original_title`, URLs, platform, creator, dates, metrics, snapshot time, scores, priority, verification level, language) are copied from evidence/scores by code and can never be overwritten by the AI output.
- **Summary:** Vietnamese, 50–100 words counted with `len(text.split())` (what `BriefContent` validates). If outside the range, retry once with a corrective instruction; if still invalid raise a clear error (the job then fails normally).
- **Metadata-only honesty (§10):** when the evidence has no body/content text (only title/metadata), set `metadata_only=True` and a Vietnamese `metadata_note_vi` stating the summary comes from metadata and the content was not fully viewed. Never claim to have watched/read what only metadata shows.
- **`why_notable` — reverse-engineer-the-niche analysis** (analyse WHY it works so the production team can learn the formula, never to copy the content). Write it as labelled Vietnamese lines in this fixed order: `Hook:` · `Định dạng:` · `Cảm xúc / động lực chia sẻ:` · `Nhóm người xem:` · `Thời điểm:` · `Khả năng khai thác ở Việt Nam:` · `Bài học áp dụng (không sao chép):`. Each line must be grounded in the evidence; where evidence is insufficient write `Chưa đủ dữ liệu` instead of guessing. Validate that all seven labels exist; retry once otherwise.
- `suggested_formats`: short, concrete format ideas for original content (not scripts, not reposts — idead.md §2).
- Revision support: the optional `feedback` argument (Claude's revision request) is passed to the AI as an instruction and the brief is regenerated; keep it stateless.
- Prompt text lives in `briefs/prompts.py` (Vietnamese output, English instructions are fine). The prompt must tell the model: no tools, no browsing, JSON only, no invented facts or numbers.

## 3. Rendering — `briefs/render.py`
`to_markdown(brief: ContentBrief) -> str` (all 24 fields of §10 in a readable Vietnamese layout, including review/handoff status and metadata-only notice) and `to_json(brief) -> str` (stable, pretty, UTF-8, ensure_ascii=False). Pure functions.

## Tests (the orchestrator will run them)
Scorer: no-metrics case is flagged and never invents numbers; priority caps with missing conditions; P1 only when all conditions hold; independence of the four scores; thresholds adjustable. Drafter with a fake `AIWorker`: code-owned fields cannot be overridden; summary 50–100 word enforcement + single retry; metadata-only disclosure; seven labels enforced; feedback passed through. Render: all fields present, JSON round-trips to `ContentBrief`.

## Done when
All files above exist and are internally consistent; final reply lists files, assumptions, and anything you could not verify without a shell.
