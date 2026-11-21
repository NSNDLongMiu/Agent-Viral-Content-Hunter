# T7c — Runtime wiring, API prefix, Telegram poller, export routes (Codex)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. Launch this task ONLY after T7a (ingest) and T7b (pipeline/scheduler) are committed. Read `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/FEASIBILITY.md`, `backend/hunter/api/app.py`, `backend/hunter/api/routes.py`, `backend/hunter/api/dependencies.py`, `backend/hunter/config.py`, and the public names exported by `hunter.ingest`, `hunter.pipeline`, `hunter.scheduler`, `hunter.orchestrator`, `hunter.ai`, `hunter.telegram`, `hunter.briefs`.

## Goal
Make the system run as ONE local process: API + dashboard + scheduler + orchestrator + Telegram poller, with the pieces from T1–T7b wired together. You are the only agent allowed to edit the T1 API files in this wave.

## Files you may touch (ONLY)
- `backend/hunter/runtime/**` (new), `backend/hunter/leader/**` (new)
- `backend/hunter/api/**`, `backend/hunter/config.py`, `config/settings.example.toml`
- `docs/openapi.json`, `docs/API.md`, `docs/ARCHITECTURE.md` (update to match)
- `backend/tests/test_runtime_*.py`, `backend/tests/test_leader_*.py`, and existing `backend/tests/test_api.py` only where behavior intentionally changes

## 1. API under `/api` + dashboard served by the backend (found bug)
The dashboard calls `/api/...`, Vite's dev proxy forwards `/api/...` WITHOUT stripping the prefix, and the backend serves routes at the root, so every dashboard call would 404. SPA paths (`/sources`, `/settings`, `/briefs/:id`) also collide with API paths. Fix: keep `create_app` (the API) as is, add `hunter/api/server.py` with `create_server_app(...)` returning a root app that mounts the API at `/api` and serves the built dashboard from `dashboard/dist` (static assets + SPA fallback to `index.html` for non-`/api` paths; serve nothing sensitive; if `dist` is missing, return a clear JSON message instead of crashing). Expose `app = create_server_app()`. The documented launch becomes `uvicorn hunter.api.server:app --host 127.0.0.1 --port 8000 --no-access-log`. Keep loopback binding. Update `docs/*` and README accordingly. The existing API tests must keep passing against `create_app`.

## 2. Runtime (`runtime/service.py`) started from the root app's lifespan
- Builds the AI adapters (`GeminiAdapter`, `CodexAdapter`, `ClaudeAdapter(enabled=False)`, `LocalAdapter`), the `Orchestrator`, `pipeline.register_all`, the `Scheduler` loop (tick every 30 s), the retention loop that already exists, and the Telegram poller below. Reports AI health to `MonitorService.record_ai_health` after real calls (never before). Graceful stop on shutdown.
- Controlled by config `runtime.enabled` (default **false** so tests and plain API runs never start background work) and the env override `HUNTER_RUNTIME__ENABLED`; add the `[runtime]` section to `config.py` and `config/settings.example.toml` with: `enabled`, `scheduler_tick_seconds`, `telegram_poll_seconds`, `dashboard_dir`, `dashboard_url`. No secrets in config.
- Everything must fail closed on cost: `budget.allow_paid_api` stays locked false; adapters keep stripping API-key env vars.
- Seeding sources: provide `python -m hunter.runtime seed-sources` that inserts the `default_sources()` (real public sources) through `OperationsService.save_source` with an audit reason, idempotent, never automatic.

## 3. Telegram (single `getUpdates` consumer)
- Build `TelegramNotifier` from env `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` when present and `telegram_enabled` preference is true; otherwise `notifier=None` (routes keep returning 501 with a clear message, never crash).
- Poller loop in the runtime is the ONLY caller of `poll_updates`: it must answer each callback within a second (`answerCallbackQuery`), then edit the original message so the button is replaced by "✅ Đã nhận" (use `editMessageReplyMarkup`/`editMessageText`; a stale callback that Telegram rejects must not break acknowledgement recording). `POST /handoffs/{id}/check-ack` then simply reads the recorded state.
- P1 alert watcher: periodically take approved briefs (via `InboxService`) with priority P1, run `telegram.alerts.should_alert(...)`, send through the notifier with a stable dedup key per brief/cluster, never from unapproved briefs, and re-check freshness for backlog. Record nothing in the DB schema (use the Telegram ledger).
- Wire `routes.briefs.export` to `briefs.render.to_markdown` / `to_json` (return `text/markdown` / `application/json`, admin only, approved briefs only) and remove the 501 for exports. Handoff send builds the Vietnamese message with `telegram.messages.format_handoff` using `runtime.dashboard_url`.

## 4. Claude Leader helper (`hunter/leader/`)
A small CLI used by the Claude Leader session (stdlib `urllib` over loopback, service token from env `HUNTER_AUTH__CLAUDE_SERVICE_TOKEN`, never printed): `python -m hunter.leader pending` (compact JSON of pending drafts incl. revision, scores, why_notable, summary, evidence URLs), `python -m hunter.leader show <brief_id>`, `python -m hunter.leader decide <brief_id> --action APPROVE|REQUEST_REVISION|REJECT --reason "…" --revision N`. It only calls `/api/review/*`; it cannot approve without an explicit non-empty reason and revision.

## Tests
Root app: `/api/health` ok, `/health` 404 at root, SPA fallback, missing `dist`, auth still enforced under `/api`; runtime disabled by default; runtime start/stop with fakes (no threads leak); poller answers callback then edits message, ignores foreign chats, only one consumer; alert watcher denies unapproved/stale/duplicate; export routes; leader CLI argument/HTTP behavior against a fake server; no secret in any output.

## Done when
Tests pass (including the whole existing suite) and `docs/` are regenerated/updated. Report: exact launch command, new config keys, and the live smoke commands for the orchestrator to run outside your sandbox.
