# T1 — Backend Foundation

Source of truth for product rules: `idead.md` at the repo root (Vietnamese). Read §7, §9, §10, §11, §13, §15, §16, §17, §18, §19, §21 first.

## Goal
Build the backend foundation that all later parallel tasks code against: SQLite schema, persistent queue, state machines, typed models, abstract interfaces, and a FastAPI skeleton with auth. Later tasks (connectors, orchestrator/AI adapters, briefs/scoring, Telegram, dashboard) will be developed in parallel against the interfaces you define — so make the interfaces precise and document them.

## Files you may touch (and ONLY these)
- `backend/**`
- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/openapi.json`
- `config/**`
- `pyproject.toml` (at repo root or in `backend/` — choose one and document it), `.gitignore`, `README.md`

Do NOT touch `spikes/**` or `docs/tasks/**`. Do NOT run `git commit`, `git push`, or change git config. Another task (T0) is editing `spikes/` concurrently.

## Hard constraints
- Python 3.12, FastAPI, pydantic v2, stdlib `sqlite3` (WAL mode), uvicorn, pytest. Keep it simple: no microservices, no Docker requirement, no Celery/Redis, no paid services.
- No fake/seed data that pretends to be real content. Test fixtures must be clearly labelled as test fixtures and only used in tests.
- Never log secrets. Config secrets come from env vars or a gitignored local file; ship only `config/settings.example.*`.
- Budget policy is 0 VND: the config must have `budget.allow_paid_api = false` as a hard default, and any code path that would use a paid API must fail closed.

## Package layout (create exactly this so parallel tasks do not collide)
```
backend/
  hunter/
    config.py            # settings loading (env + yaml/toml), budget policy flag
    db/                  # connection (WAL, foreign keys), migration runner, schema SQL
    models/              # pydantic models: ContentBrief (all 24 fields of idead.md §10), Source, Job, TrendCluster, SeriesGroup, ReviewDecision, Handoff, Feedback
    queue/               # persistent SQLite queue
    state/               # brief + handoff + job state machines
    interfaces/          # abstract contracts (see below)
    services/            # review service, retention service, inbox service
    api/                 # FastAPI app, routers, auth
    connectors/          # EMPTY package (owned by task T2)  -> only __init__.py
    orchestrator/        # EMPTY package (owned by task T3)  -> only __init__.py
    ai/                  # EMPTY package (owned by task T3)  -> only __init__.py
    briefs/              # EMPTY package (owned by task T4)  -> only __init__.py
    scoring/             # EMPTY package (owned by task T4)  -> only __init__.py
    telegram/            # EMPTY package (owned by task T6)  -> only __init__.py
  tests/
```
The dashboard (React+TS) will live in `dashboard/` (task T5) — do not create it.

## Required behavior

### DB schema (versioned migrations)
Tables at least: `sources`, `connector_status`, `raw_items` (collected data with source URL + metadata + fetched_at + metric snapshot time), `fingerprints` (dedup), `briefs` (+ `brief_revisions`, `review_decisions` with mandatory reason), `trend_clusters` (+ membership), `series_groups` (+ episodes), `jobs` (+ `job_attempts`), `handoffs`, `feedback`, `settings`, `audit_log` (source list changes, setting changes, adjustments — all reversible/undoable records), `ai_status` (per AI: availability, last error, quota flag).
All timestamps UTC ISO-8601. Every table that is subject to retention carries a `created_at` used by the 90-day retention (§18).

### Persistent queue (§7, §16)
- Two queues: `urgent` and `normal`; urgent served first, but never preempts a running job.
- Lease + heartbeat; on startup, expired leases are reclaimed safely (job returns to queued with attempt count preserved).
- Retry max 3 with exponential backoff (+ jitter); after that → `dead` (error queue). Never infinite loop.
- Idempotency key per job (enqueue same key twice → one job).
- Per-worker concurrency limits (configurable: claude=1, codex=2, gemini=2, local=resource-based, collector=configurable).
- Atomic claim (no two workers get the same job).

### State machines (§11, §13)
- Brief: `COLLECTED → PREPROCESSED → PROCESSING → PENDING_CLAUDE_REVIEW → {APPROVED_BY_CLAUDE | REVISION_REQUIRED | REJECTED_BY_CLAUDE}`; `REVISION_REQUIRED → PROCESSING` up to **2** revisions (persist `revision_count`, never reset by crash); after that `REVIEW_FAILED`. Invalid transitions raise.
- Only the review service may set `APPROVED_BY_CLAUDE`, and only with a non-empty reason. Nothing else (no worker, no API route for workers) may.
- Discovery Inbox query returns ONLY `APPROVED_BY_CLAUDE` briefs.
- Handoff: `NOT_HANDED_OFF → SELECTED → SENT | SEND_FAILED → ACKNOWLEDGED`; "sent" ≠ "acknowledged". Idempotent send (dedup key) to prevent duplicate Telegram sends. A handoff can only start from an admin action on an approved brief.
- When Claude is unavailable, results stay `PENDING_CLAUDE_REVIEW`; nothing is auto-approved; P1 alerts are never emitted from unapproved briefs.

### Interfaces (`backend/hunter/interfaces/`) — abstract contracts others will implement
Define as `typing.Protocol` or ABC with docstrings and full type hints:
- `Connector`: `id`, `capabilities`, `async fetch(since, limits) -> list[RawItem]`, `health() -> ConnectorHealth`; must report real errors; no fake data.
- `AIWorker`: `name` in {claude, codex, gemini, local}, `async run(task: AITask) -> AIResult` returning structured (JSON-schema validated) output plus a status enum `OK | AUTH_LOST | QUOTA_EXHAUSTED | TIMEOUT | UNAVAILABLE | ERROR`; `health()`.
- `Notifier` (Telegram): `send(message, dedup_key) -> SendResult`, `check_ack(...)`.
- `Scorer`: computes Virality / Relevance / Credibility / Priority separately with an explanation string (§8) — interface only.
- `BriefDrafter` / `BriefReviewer`: interface only.

### API (FastAPI) — skeleton with real behavior where specified
Routers: `health`, `auth`, `briefs` (inbox = approved only; detail; export md/json endpoints may return 501 with a clear message until T4), `review` (internal use by the Claude leader process; authenticated by a separate service token), `jobs`, `sources`, `handoffs`, `feedback` (4 actions: good / irrelevant / duplicate / bad-source), `settings`, `monitor` (AI status, queues, recent errors).
Auth: single admin group; password hash (argon2/bcrypt/scrypt) from config, session cookie or bearer token; every route except `/health` requires auth. No complex RBAC.
Export `docs/openapi.json` and describe every route in `docs/API.md` (the dashboard task will code against it).

### Retention (§18)
`services/retention.py`: deletes briefs, their history, fingerprints, raw items older than 90 days (configurable constant defaulting to 90); no admin confirmation; testable with an injected clock.

### Docs
`docs/ARCHITECTURE.md`: layout, module ownership map for the follow-up tasks (T2 connectors, T3 orchestrator+ai, T4 briefs+scoring, T5 dashboard, T6 telegram, T7 windows+docs), the state machines (diagram in mermaid), interface contracts, and any assumptions you made.

## Tests (`cd backend && python -m pytest -q` must pass)
Cover at least: queue claim atomicity, crash/lease-expiry recovery with attempts preserved, retry→dead after 3, idempotent enqueue, invalid state transitions, revision limit → `REVIEW_FAILED`, approval requires reason, inbox returns only approved, handoff idempotency, retention with injected clock, auth required on protected routes, paid-API flag fail-closed.

## Done when
- `python -m pytest -q` passes; the app starts with `uvicorn hunter.api.app:app` (document the exact command) and `/health` works.
- `docs/openapi.json`, `docs/API.md`, `docs/ARCHITECTURE.md` exist and match the code.
- Nothing outside the allowed paths modified.
