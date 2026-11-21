# T3 — Orchestrator + AI adapters (Codex)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. Then read `docs/FEASIBILITY.md` (verified CLI behaviour), `docs/ARCHITECTURE.md` (queue + adapter contracts), `backend/hunter/interfaces/ai.py`, `backend/hunter/queue/persistent.py`, `backend/hunter/state/jobs.py`, `backend/hunter/services/monitor.py`.

## Goal
(1) AI worker adapters that call the official subscription CLIs safely and map real failures to `AIStatus`; (2) an async orchestrator that drains the persistent queue with handlers, heartbeats, timeouts and recovery. All process execution must be injectable so tests use fakes; the orchestrator verifies real CLIs outside your sandbox.

## Files you may touch (ONLY)
- `backend/hunter/ai/**`, `backend/hunter/orchestrator/**`
- `backend/tests/test_ai_*.py`, `backend/tests/test_orchestrator_*.py`

## 1. `ai/cli_runner.py` — safe subprocess runner
- `asyncio` subprocess, NEVER `shell=True`; argument list only; prompt passed via stdin or a temp file, never interpolated into a shell string.
- Child environment = current env MINUS: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `CODEX_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT` (zero-cost: no metered mode can be activated).
- Hard timeout; on timeout kill the whole process tree on Windows (`taskkill /T /F /PID` via the injectable runner, fall back to terminate) and return a TIMEOUT outcome. Cap captured output (e.g. 1 MiB). Redact anything that looks like a token in diagnostics.
- Injectable `Runner` interface so tests pass a fake that returns scripted `(exit_code, stdout, stderr)`.

## 2. Adapters (each implements `AIWorker`; use `AIResult.success(task, output)`; call `BudgetSettings.require_allowed(incurs_cost=False)`-style checks before any external I/O as `docs/ARCHITECTURE.md` says)
- **`codex_adapter.py` (`name="codex"`)**: non-interactive `codex exec` with structured output. Verify the exact flags with `codex exec --help` in your sandbox (do not guess); prefer `--json`, `--output-schema <file>`, `--output-last-message <file>`, read-only sandbox for analysis tasks. Parse the JSON result and validate against `task.output_schema`. Known real failure texts (map to statuses, case-insensitive substring match, keep the list in one constant):
  - quota: `You've hit your usage limit` / `usage limit` / `try again at` → `QUOTA_EXHAUSTED`
  - auth: `access token could not be refreshed` / `signed in to another account` / `Please sign in again` / `not logged in` → `AUTH_LOST`
  - binary missing → `UNAVAILABLE`; timeout → `TIMEOUT`; anything else non-zero or unparsable → `ERROR`.
- **`gemini_adapter.py` (`name="gemini"`)**: uses Antigravity CLI `agy`. Locate the executable: configured path, else `shutil.which("agy")`, else `%LOCALAPPDATA%\agy\bin\agy.exe`; the standard `gemini` CLI is optional fallback only if found. Command shape verified by the orchestrator: `agy -p "<prompt>" --output-format json --model <model> --mode plan --print-timeout <Ns>` (add `--json-schema` only if `agy --help` in your sandbox confirms it). The JSON envelope is `{"status","response","denied_actions","usage",...}`. **Critical guard:** `status:"SUCCESS"` is NOT success if `response` is empty/whitespace or `denied_actions` is non-empty → return `ERROR` with a safe message (observed bug: a denied shell command returns SUCCESS with an empty response). Analysis tasks must instruct the model not to use tools. Parse the model's JSON answer from `response` (strip code fences) and validate against the schema. Auth/quota patterns for `agy` are UNVERIFIED: map obvious strings (`quota`, `rate limit`, `sign in`, `login`, `unauthorized`) conservatively and document them as unverified in the module docstring.
- **`claude_adapter.py` (`name="claude"`)**: DISABLED by default. Constructor `enabled: bool = False`. When disabled, `run()` returns `UNAVAILABLE` with a message that headless Claude is off until the user confirms paid usage credits are disabled; `health()` reports it truthfully. When enabled it may use `claude -p --output-format json` through the same runner, with the same env stripping. (The Claude Leader normally reviews through the review API with the service credential, not through this adapter.)
- **`local_adapter.py` (`name="local"`)**: `UNAVAILABLE` stub — no local runtime is installed (see feasibility); rule-based processing lives elsewhere.
- Every adapter implements `health()` from the last observed outcome (never claims OK before a real success; before any run: `UNAVAILABLE`/unknown with a clear reason). Provide `report_health(monitor_service, adapter)` that calls `MonitorService.record_ai_health`.

## 3. `orchestrator/` — queue worker service
- `Orchestrator` (asyncio): registers handlers per job kind (`register(kind, handler)`), runs one worker loop per worker kind (claude/codex/gemini/local/collector) respecting the queue's concurrency limits; urgent-first is already done by `PersistentQueue.claim` — do not reimplement it.
- While a handler runs, heartbeat the lease on an interval well under the lease duration; if the lease is lost, discard the result (no completion).
- Per-kind default timeouts; handler timeout → `fail` with a transient error so backoff/retry applies; unknown job kind → `fail` as policy/terminal (no infinite loop).
- Map `AIStatus` → queue outcome using the queue's own failure semantics (read `queue/persistent.py`): `QUOTA_EXHAUSTED` pauses that worker kind via the queue's quota path and reports AI health; `AUTH_LOST`/`UNAVAILABLE` → record health, do not hot-loop (backoff); `TIMEOUT`/`ERROR` → transient retry; a result requiring a paid service → `POLICY_BLOCKED`.
- Startup: reclaim expired leases (the queue does it on claim — verify and call explicitly at start). Graceful stop: stop claiming, let running handlers finish up to a grace period, then leave the lease to expire (never mark success without a result).
- Resource governor (stdlib only, no new deps): optionally skip claiming when system memory use is above a configurable threshold (use `ctypes` `GlobalMemoryStatusEx` on Windows, injectable for tests). Keep it small.
- Do NOT write business pipeline logic (collect → draft → score → review) here; later tasks register handlers. Provide `orchestrator/health.py` summarising adapters' health for the monitor service.

## Tests (fakes only)
Adapter status mapping for each known failure text; `agy` empty-response/`denied_actions` guard; env stripping (assert the forbidden vars are absent in the child env); timeout path; claude adapter disabled by default; orchestrator: success, retry→dead after 3, quota pause, lost lease discarded, unknown kind, heartbeat extends lease, graceful stop, crash/restart reclaim. Use a real in-memory/temp SQLite queue from T1 (not mocks of the queue).

## Done when
Your tests pass; report lists the exact smoke-test commands the orchestrator should run outside the sandbox for each adapter (a tiny `python -m hunter.ai.smoke codex|gemini` that sends a trivial schema-bound prompt and prints only status + short result).
