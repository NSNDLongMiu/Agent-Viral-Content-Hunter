# T5 — Dashboard (React + TypeScript)

Source of truth for product rules: `idead.md` at the repo root (Vietnamese). Read §10 (Content Brief fields), §11 (review states), §12 (Dashboard), §13 (Telegram handoff), §14 (feedback), §17 (0 VND budget) first.

> **MANDATORY: read `AGENTS.md` at the repo root first. ZERO-COST POLICY applies to you: nothing that costs extra money, no API keys, no paid services, no card-required trials. If something needs payment or quota runs out: STOP, mark BLOCKED, report. Fail closed.**

## Goal
Build the admin dashboard UI. Backend (FastAPI) is being built concurrently by another task (T1); you code against a thin API adapter so reconciling with the real API later is a small change.

## Files you may touch (and ONLY these)
- `dashboard/**`

Do NOT touch `backend/`, `spikes/`, `docs/`, `config/`, `idead.md`, or any root file. Do NOT run `git commit`/`git push`. Do NOT run `npm install` / `npm create` / any package manager or network command: write all files by hand (including `package.json`); the orchestrator will run the install and build and send you any errors.

## Stack and constraints
- React 18 + TypeScript (strict) + Vite. Keep dependencies minimal: `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, plain CSS (CSS variables, light + dark via `prefers-color-scheme`). No UI kit, no CSS framework, no state library beyond React Query.
- Pin dependency versions in `package.json` to widely-used stable releases you are confident exist.
- UI language: Vietnamese labels. Code, identifiers and comments in English.
- NO fake data anywhere: no hard-coded sample briefs, no mock numbers, no placeholder charts with invented values. When the API has no data or is unreachable, show a clear empty state or error state. (Test fixtures, if any, live only under `dashboard/src/**/__fixtures__/` and are never imported by app code.)
- Never store secrets in the repo. Auth token/session handling per below.
- Budget policy is 0 VND: the Settings page must show the "paid APIs: disabled" policy as read-only; there must be no UI to enable paid services.

## API adapter (critical for later reconciliation)
All HTTP goes through ONE module: `dashboard/src/api/client.ts` (fetch wrapper: base URL from `import.meta.env.VITE_API_BASE` defaulting to same-origin `/api`, credentials included, JSON, typed errors incl. 401 → redirect to login). All DTO types live in ONE file: `dashboard/src/api/types.ts`. Each endpoint is a typed function in `dashboard/src/api/endpoints.ts`.
The backend task is defining these routers (exact schemas will land later in `docs/openapi.json`; until then derive types from `idead.md` §10 and mark every guessed shape with `// TODO(reconcile with docs/openapi.json)`):
`health`, `auth` (login/logout/me), `briefs` (inbox = approved only; detail; export md/json), `jobs`, `sources`, `handoffs`, `feedback` (actions: good | irrelevant | duplicate | bad_source), `settings`, `monitor` (AI status, queues, recent errors).
Vite dev server must proxy `/api` to `http://127.0.0.1:8000`.

## Screens (idead.md §12) — routes under a shared layout with sidebar
1. **Login** (single admin group; no RBAC).
2. **Overview**: counts (new items, P1 candidates, waiting for Claude, approved, handed off), source status, AI status (Claude/Codex/Gemini/Local), queue health, recent errors. Values come only from the API.
3. **Discovery Inbox**: approved briefs only; filters (platform, topic, time range, priority P1/P2/P3), text search, open Trend Cluster, open Series Brief, the 4 quick-feedback buttons (Tin tốt / Không phù hợp / Trùng nội dung / Thiếu hoặc sai nguồn), select for handoff.
4. **Content Detail**: all Content Brief fields of idead.md §10, original link, metadata, engagement metrics + snapshot time, related sources, score breakdown with reasons (Virality / Relevance / Credibility / Priority shown SEPARATELY — never merged into one number), review history (decisions + reasons), handoff status. If the summary was generated from metadata only, show that notice prominently.
5. **Handoff Board**: columns Not handed off / Selected / Sent to Telegram / Acknowledged / Send failed. Distinguish "sent" from "acknowledged". Actions: approve handoff, retry failed send, mark acknowledged.
6. **Source Manager**: sources list, priority, blocked sources, connector health, last scan, error history, enable/disable.
7. **AI & System Monitor**: Claude/Codex/Gemini/Local availability, running jobs, queues (urgent/normal), timeouts, retries, quota errors, execution history, dead-letter jobs.
8. **Settings**: P1 threshold, scan schedule, watched sources, priority topics, excluded topics, Telegram (never display the bot token; write-only field), job limits, budget policy (read-only), retention (90 days default).

## Quality requirements
- Accessible: semantic HTML, keyboard navigable, visible focus, labels on inputs, sufficient contrast in light and dark.
- Responsive down to ~360px width.
- Every data view handles loading / empty / error states explicitly.
- Destructive or outward-facing actions (handoff send, retry) require an explicit confirm.
- Optimistic updates only where safe; otherwise invalidate queries.
- Build output: `npm run build` produces `dashboard/dist` (the backend will serve it later).

## Deliverables
`dashboard/package.json`, `tsconfig*.json`, `vite.config.ts`, `index.html`, `src/**` (api/, pages/, components/, styles/, routes), `dashboard/README.md` (how to run dev + build, how the adapter maps to the API).

## Done when
- All screens above exist and are wired to the adapter.
- The code is written to pass `npm run build` (tsc strict + vite) — the orchestrator will run it and report errors for you to fix.
- No hard-coded data presented as real; nothing outside `dashboard/` modified.
