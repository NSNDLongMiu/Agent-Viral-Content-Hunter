# T5b — Reconcile the dashboard with the real API (Gemini)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. You have NO shell: use only file view/create/edit tools; the orchestrator runs `npm run build` and sends you errors. Then read `docs/tasks/T5-dashboard.md` (the original spec), `docs/openapi.json`, `docs/API.md` and `docs/ARCHITECTURE.md`.

## Goal
The dashboard in `dashboard/` was written before the backend existed, with 42 `TODO(reconcile with docs/openapi.json)` guesses. Make it match the real API exactly.

## Files you may touch (ONLY)
- `dashboard/**` (do not touch `node_modules/`, `dist/`, `package-lock.json`, and do not add dependencies)

## Work
1. For every endpoint the UI uses, align `dashboard/src/api/types.ts`, `endpoints.ts` and `client.ts` with `docs/openapi.json` (paths, methods, request/response field names, enums such as `BriefStatus`, `HandoffStatus`, `Priority`, error shapes). Remove each `TODO(reconcile…)` you resolved. Keep ALL HTTP in the adapter module.
2. **Auth is a bearer session, not a cookie:** `POST /auth/login` returns an opaque token. Keep the token in memory with `sessionStorage` as a same-tab fallback (never `localStorage`); send `Authorization: Bearer …`; on 401 clear it and go to login. Restarting the API invalidates sessions — handle it gracefully.
3. **API gaps:** if a screen needs data/actions the API does not offer, do NOT invent endpoints. Show an honest empty/"chưa hỗ trợ" state for that part and list every gap in a new file `dashboard/RECONCILE.md` (screen → needed capability → closest existing endpoint).
4. Keep the rules of the original spec: no fake data, Virality/Relevance/Credibility/Priority shown separately, settings never send `budget_policy`, Telegram token write-only, confirm dialogs for outward-facing actions, Vietnamese UI, accessibility.
5. Keep `npm run build` (tsc strict + vite) passing. No unused imports/locals that break strict mode.

## Done when
`grep TODO(reconcile` finds none that is still resolvable; `RECONCILE.md` lists the true gaps; final reply lists changed files and assumptions.
