# T9d — Dashboard: AI-production section, focus tags, Inbox filters (Gemini)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. You have NO shell: use only file view/create/edit tools; the orchestrator runs `npm run build` and sends you the errors. Read first: `dashboard/src/api/types.ts`, `dashboard/src/api/endpoints.ts`, `dashboard/src/pages/InboxPage.tsx`, `dashboard/src/pages/ContentDetailPage.tsx`, `dashboard/src/components/StatusBadge.tsx`, `dashboard/src/styles/global.css`, `dashboard/RECONCILE.md`.

## Context
The production team makes videos with generative AI. The backend (other tasks, running in parallel) adds two fields to every brief and two Inbox filters. Code against this contract; do not wait for the backend.

## API contract (exact)
Every brief object (`ContentBrief`, also inside `BriefDetail.brief`) gains:
- `focus_tags: Array<"phim_ngan" | "micro_drama" | "giai_tri" | "ai_san_xuat">` (may be empty; old briefs have `[]`)
- `ai_production: null | { feasibility: "CAO" | "TRUNG_BINH" | "THAP"; approach_vi: string; constraints_vi: string[] }` (`null` on old briefs)
`GET /briefs/inbox` gains optional query parameters `ai_feasibility` (`CAO|TRUNG_BINH|THAP`) and `focus_tag` (one tag above). Omit a parameter instead of sending an empty string.
Vietnamese labels: tags → "Phim ngắn", "Micro-drama", "Giải trí", "Sản xuất bằng AI"; feasibility → "Làm bằng AI: Cao" (green badge), "Làm bằng AI: Trung bình" (amber), "Làm bằng AI: Thấp" (red/grey); `null` → "Chưa đánh giá".

## Files you may touch (ONLY)
`dashboard/src/**` and `dashboard/RECONCILE.md` (add a short dated note). Not `package.json`, no new dependency, no backend files.

## Work
1. `types.ts`: add `FocusTag`, `AIFeasibility`, `AIProduction`; add `focus_tags` and `ai_production` to the brief type(s); add the two optional fields to the inbox filter params type. Keep the file's existing "reconciled against openapi" convention; do not invent other fields.
2. `endpoints.ts`: pass the two filter params through the existing inbox call (use the same omit-when-empty handling as the other filters).
3. `InboxPage.tsx`: two new filter selects ("Khả năng làm bằng AI": Tất cả / Cao / Trung bình / Thấp; "Nhóm nội dung": Tất cả / the four tags) wired to the query like the existing filters (React Query key must include them); on each brief row/card show the focus tags as small chips and the feasibility badge (use a new small component, for example `components/FeasibilityBadge.tsx`, reused by the detail page; keep the plain CSS/variables style, light and dark mode).
4. `ContentDetailPage.tsx`: a new card "Khả năng làm bằng AI" (placed after "Mức độ xác minh & Rủi ro"): the badge, `approach_vi`, and `constraints_vi` as a bullet list headed "Ràng buộc cần lưu ý". For `null` show "Chưa đánh giá khả năng làm bằng AI (hồ sơ cũ)." Also show the focus-tag chips under the title.
5. **Small existing bug to fix in the same file:** the "Trạng thái bàn giao" card shows the button "Phê duyệt & Bàn giao qua Telegram" even when the handoff is already `SENT` or `ACKNOWLEDGED`. Show the button only while the handoff can still be selected or sent (`NOT_HANDED_OFF`, `SELECTED`, `SEND_FAILED`); otherwise show the status text only. Check the handoff statuses in `types.ts`/`docs/API.md` before deciding.
6. Handle missing/undefined fields defensively (a response from an older backend must not crash the page).

## Rules specific to this task
No fake data, no placeholder content shown as real. Do not touch auth (there is no login any more), `client.ts`, or unrelated pages. Final report: files changed and anything you could not verify.
