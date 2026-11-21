# Backend architecture

T1 is a local Python 3.12 application with FastAPI, Pydantic v2, and the standard-library SQLite driver. The root `pyproject.toml` packages `backend/hunter` and configures tests for invocations from the repository root and `backend/`.

| Owner | Paths | Responsibility |
| --- | --- | --- |
| T1 | `backend/hunter/{db,models,queue,state,interfaces,services,api}`, `config.py` | Persistence, shared contracts, domain transitions, configuration, and API |
| T2 | `backend/hunter/connectors` | Public-source collectors, real connector health, and fingerprint deduplication |
| T3 | `backend/hunter/{orchestrator,ai}` | Scheduling, worker dispatch, CLI adapters, and Claude leader integration |
| T4 | `backend/hunter/{briefs,scoring}` | Brief generation, scoring, clustering and series grouping, Markdown and JSON rendering |
| T5 | `dashboard/` | React and TypeScript admin dashboard consuming the published OpenAPI |
| T6 | `backend/hunter/telegram` | Telegram notifier, deduplication receipts, acknowledgement, and P1 alerts |
| T7 | Windows startup and project docs | Windows login startup, operations, and deployment instructions |

## Persistence

Call `Database(path).migrate()` before storage access. Startup sets WAL mode, runs numbered SQL migrations in a write transaction, and records each applied version in `schema_migrations`. Every connection enables foreign keys. Domain writes acquire a `BEGIN IMMEDIATE` transaction for changes that must be atomic. Use the APIs below for state changes. Direct access to the local SQLite file is part of the trusted process boundary.

Database timestamps use UTC ISO-8601 with microseconds. Python models normalize aware timestamps to UTC and reject naive inputs. IDs are opaque strings except for integer sequence IDs on decisions, feedback and audit entries.

- `sources` and `connector_status` hold the source registry and last reported status per connector. `OperationsService.save_source`, `remove_source`, `record_connector_health` and `store_raw_item` cover audited source changes, health and observations. Removal hides a source while preserving references and enabling undo.
- `raw_items` holds the observed URL, metadata, fetch time, and captured metrics with a snapshot timestamp when metrics are present. `fingerprints` keys fingerprints by `(kind, digest)` and associates each with a raw item, a brief, or both. T2 owns fingerprint algorithms and the transaction for deduplicated collection.
- `briefs` stores current status, revision count and validated draft content. `brief_revisions` stores submitted snapshots numbered 0, 1 and 2. `review_decisions` links a reasoned decision to its snapshot. `trend_cluster_members` joins clusters to raw items and marks trusted members. `series_episodes` records episode URLs, optional sequence, and an optional raw item link.
- `jobs` and `job_attempts` retain queue state and attempt history. `ai_status` stores observed service availability, last error, and quota state. Report health through `MonitorService.record_ai_health`. Missing health means the adapter has yet to report.
- `handoffs` holds one selection per approved brief, its stable delivery key, and independent send and acknowledgement timestamps. `feedback` records the four admin feedback actions.
- `settings` holds editable dashboard preferences. `audit_log` preserves before and after snapshots, actor, and reason for each source or preference mutation. Undo applies while the current state still matches the recorded result. It writes its own audit entry and repeating the same undo returns that entry. Automated preference adjustments are limited to scan intervals and priority topics. Startup queue and retention limits are loaded from config and exposed read-only to the dashboard.

On startup and every 24 hours while the app is running, `RetentionService.purge()` deletes briefs, raw items and fingerprints strictly older than the configured cutoff, 90 days by default. It also deletes linked fingerprints and cascades brief revisions, review history, handoffs, and feedback. It accepts an injected clock and runs automatically. Trend and series records and operational history remain available. T1 creates no backups. The Windows backup workflow should apply the same retention policy to managed copies.

## Review workflow

```mermaid
stateDiagram-v2
    [*] --> COLLECTED
    COLLECTED --> PREPROCESSED
    PREPROCESSED --> PROCESSING
    PROCESSING --> PENDING_CLAUDE_REVIEW: submit numbered draft
    PENDING_CLAUDE_REVIEW --> APPROVED_BY_CLAUDE: approve with reason
    PENDING_CLAUDE_REVIEW --> REJECTED_BY_CLAUDE: reject with reason
    PENDING_CLAUDE_REVIEW --> REVISION_REQUIRED: request changes with revisions remaining
    REVISION_REQUIRED --> PROCESSING: increment revision count
    PENDING_CLAUDE_REVIEW --> REVIEW_FAILED: request changes after two revisions
```

`BriefStore.create()` persists a collected record. Workers use `advance(brief_id, target)` and `submit_draft(brief_id, draft, expected_revision=...)`. Draft content has a Vietnamese summary of 50–100 whitespace-delimited words, a metadata-only disclosure when applicable, and separate scores. The brief view combines that content with the record ID and persisted review and handoff states to expose all 24 product fields.

Only `ReviewService.decide()` writes Claude decisions. It checks the expected revision and records the decision and state change atomically. The API exposes this operation only to the Claude service credential. A recorded unavailable or quota-exhausted Claude leaves new results pending. Before any health observation, the separate credential and a valid explicit decision are required. The inbox always filters for `APPROVED_BY_CLAUDE`. P1 alerts must begin from the approved inbox or approved detail lookup. T6 also owns threshold, evidence, verification, freshness, and alert deduplication checks.

## Queue workflow

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: claim and start numbered attempt
    running --> running: heartbeat extends lease
    running --> queued: retry or reclaim expired lease
    running --> succeeded: complete with live lease
    running --> dead: retry limit or policy block
```

`PersistentQueue.enqueue(JobInput, available_at=...)` uses a durable idempotency key. The first enqueue owns the key for the lifetime of the job. `claim(worker, worker_id)` chooses an eligible urgent job before a normal job for that worker kind. It acquires the lease and records the attempt in one transaction. Running jobs hold their slots. Concurrency is configurable per worker kind. The default local limit is one slot per four logical CPUs, with at least one slot. A configured zero disables claims for that kind.

Pass the returned job ID and lease token to `heartbeat`, `complete`, or `fail`. Workers should heartbeat before expiry and discard stale completions when they lose the lease. Queue-backed business operations should use their own idempotency keys for effects outside the lease transaction. Startup and later claims reclaim expired leases without resetting attempt counts. Expiry recovery is immediately eligible within the retry limit. Explicit transient failures follow exponential backoff with up to 25% jitter. Three retries follow the initial attempt. A job that requires a paid service ends with `POLICY_BLOCKED` (`BLOCKED (needs paid service)`). An AI quota failure pauses claims for its worker kind until a later health report confirms availability with quota restored.

## Handoff workflow

```mermaid
stateDiagram-v2
    [*] --> NOT_HANDED_OFF
    NOT_HANDED_OFF --> SELECTED: authenticated admin selects approved brief
    SELECTED --> SENT: confirmed delivery receipt
    SELECTED --> SEND_FAILED: failed or uncertain delivery
    SEND_FAILED --> SEND_FAILED: retry or receipt lookup
    SEND_FAILED --> SENT: successful retry or recovered receipt
    SENT --> ACKNOWLEDGED: confirmed recipient action
```

`HandoffService.select_by_admin` is called only from an authenticated admin action. Selection generates one durable deduplication key. `send` serializes concurrent dispatches using a short, persisted lease. After an uncertain result or abandoned dispatch, the service only looks up the existing key. It can retry sending once definitive failure is established. A successful send records the returned receipt, and `check_ack` records acknowledgement only after the notifier confirms recipient action. T6 must durably associate delivery receipts with deduplication keys and preserve uncertainty when a receipt cannot be recovered.

## Adapter contracts

Import these protocols and their input and result types from `hunter.interfaces`. Persistence models and enums are exported from `hunter.models`.

| Protocol | Methods and shared types |
| --- | --- |
| `Connector` | Stable `id`, `capabilities: Collection[ConnectorCapability]`, `async fetch(since: datetime \| None, limits: FetchLimits) -> list[RawItem]`, and `health() -> ConnectorHealth`. Raise `ConnectorError` for real fetch failures and report credential-free diagnostics. |
| `AIWorker` | `name: AIName`, `async run(task: AITask) -> AIResult`, and `health() -> AIHealth`. Outcomes are `OK`, `AUTH_LOST`, `QUOTA_EXHAUSTED`, `TIMEOUT`, `UNAVAILABLE`, and `ERROR`. Build successful results with `AIResult.success(task, output)` and validate them at the orchestrator boundary with `validate_for(task)`. Output is an object validated against Draft 2020-12 JSON Schema without remote reference fetching. |
| `Scorer` | `score(items: Sequence[RawItem]) -> ScoringResult` returns independent virality, relevance, credibility, categorical priority, and a human-readable explanation. |
| `BriefDrafter` | `async draft(items, scores, *, feedback=None) -> BriefContent` produces validated Vietnamese content. |
| `BriefReviewer` | `async review(brief: ContentBrief) -> ReviewInput` obtains the Claude decision, reason and revision. Submit it through the review service credential. |
| `Notifier` | `incurs_cost: bool \| None`, `send(message, dedup_key) -> SendResult`, `lookup_send(dedup_key) -> SendResult`, and `check_ack(external_id, dedup_key) -> bool`. Lookup performs no dispatch. `SENT` includes an external receipt. `FAILED` is definitive. `UNKNOWN` preserves delivery uncertainty. |

## Configuration and access

`config/settings.local.toml` is the optional local config. `HUNTER_CONFIG` points to an alternate TOML file. Environment variables override individual fields, including `HUNTER_DATABASE_PATH`, `HUNTER_QUEUE__CLAUDE`, `HUNTER_RETENTION__DAYS`, `HUNTER_AUTH__ADMIN_PASSWORD_HASH`, and `HUNTER_AUTH__CLAUDE_SERVICE_TOKEN`. Relative database paths are resolved from the repository root when launched from inside the checkout. By default, the database lives at `backend/data/hunter.sqlite3`.

`budget.allow_paid_api` is locked to false. Adapters must establish verified zero incremental cost and call `BudgetSettings.require_allowed(incurs_cost=...)` before external I/O. Paid or unknown cost fails closed. AI adapters must use the official subscription-authenticated CLIs and remove API-key and metered-mode variables from child environments. Persist only credential-free error codes or diagnostics.

Admin authentication uses a salted scrypt password hash and opaque bearer sessions stored in the server process. Run a single API process. Restarting it expires admin sessions. The Claude leader uses a distinct configured credential. The API binds to loopback in the documented launch command. The dashboard should proxy the API at the same origin in its production setup.
