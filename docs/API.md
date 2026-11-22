# Viral Content Hunter API

The local server API base URL is `http://127.0.0.1:8000/api`. All paths below are relative to that base. The dashboard uses the same origin and loads its pages from `/`. The standalone `hunter.api.app.create_app()` exposes the relative paths directly for API tests. [OpenAPI JSON](openapi.json)

## Authentication and errors

There is no login: every route except `/review/*` answers any caller on this machine. `/review/*` requires `Authorization: Bearer <token>` with the Claude leader service token. The server refuses (`403`) requests whose `Host` header is not `127.0.0.1`, `localhost` or `::1`, and state-changing requests (anything but `GET`, `HEAD`, `OPTIONS`) that carry an `Origin` header from a non-local site, so web pages from other sites cannot drive it. Non-browser callers (the leader CLI, `curl`) send no `Origin` and are unaffected.

HTTP `401` reports a missing or invalid Claude leader token on `/review/*`, with a bearer challenge. `403` reports a refused non-local `Host` or `Origin`. `404` means the record is unavailable at that route. `409` reports a workflow or settings conflict. `422` reports invalid request fields. Error responses use `detail`. Validation failures redact input values. List routes that support pagination return JSON arrays, with `limit` defaulting to 50 and bounded to 1–200, and `offset` defaulting to zero.

## Health

| Method and path | Behavior |
| --- | --- |
| `GET /health` | Returns `{"status":"ok"}` when the migrated SQLite database can be read. Returns `503` if it is unavailable. |

## Discovery and review

| Method and path | Access and behavior |
| --- | --- |
| `GET /briefs/inbox` | Admin. Lists approved briefs, newest update first. Accepts `priority`, `platform`, `content_type`, `discovered_after` (inclusive UTC datetime), `search` (case-insensitive title or summary substring), `ai_feasibility`, `focus_tag`, and pagination. |
| `GET /briefs/{brief_id}` | Admin. Returns `{"brief": …, "review_history": […]}` for an approved brief. |
| `GET /briefs/{brief_id}/export/{format}` | Admin. Renders an approved brief as `text/markdown` for `md` or `application/json` for `json`. Returns `404` for unavailable or unapproved briefs. |
| `GET /review/pending` | Claude. Returns pending draft snapshots, oldest update first, with pagination. |
| `GET /review/{brief_id}` | Claude. Returns a single pending draft with its current `revision_count`. Returns `404` once the draft is no longer pending. |
| `POST /review/{brief_id}/decision` | Claude. Takes `action`, `reason`, and `expected_revision` from the draft's `revision_count`. Actions are `APPROVE`, `REQUEST_REVISION`, and `REJECT`. Returns the stored decision and resulting status. Repeating the same decision returns the original record. |

Brief responses and JSON exports include `focus_tags`, an array assigned by the scorer with values `phim_ngan`, `micro_drama`, `giai_tri`, and `ai_san_xuat`. They also include `ai_production`, an object with `feasibility` (`CAO`, `TRUNG_BINH`, or `THAP`), `approach_vi` (a 15–80 word Vietnamese production approach), and `constraints_vi` (a nonempty array of Vietnamese notes).

`ai_feasibility` accepts one feasibility value. `focus_tag` accepts one focus tag and matches briefs containing it. Inbox filters combine with AND, and invalid values return a redacted `422`. Legacy briefs without these fields return `focus_tags: []` and `ai_production: null` and are excluded when either filter is applied.

## Jobs and source management

| Method and path | Admin behavior |
| --- | --- |
| `GET /jobs` | Lists jobs by newest creation time. Accepts `status` and pagination. Status values are `queued`, `running`, `succeeded`, and `dead`. |
| `GET /jobs/{job_id}` | Returns persisted job state, including attempt count, availability and current lease expiry. |
| `GET /jobs/{job_id}/attempts` | Returns the attempt history in ascending attempt order. |
| `GET /sources` | Lists current sources by descending priority, then name. Accepts pagination. |
| `POST /sources` | Creates a source with `{"source": {…}, "reason":"…"}` and returns `201` with the record. |
| `GET /sources/health` | Lists the last reported status for each connector. |
| `GET /sources/{source_id}` | Returns the current source record. |
| `PUT /sources/{source_id}` | Replaces editable source fields. Uses the same body as creation and returns the resulting source. |
| `POST /sources/{source_id}/remove` | Hides a source from the registry. Takes `{"reason":"…"}` and returns its audit record for undo. |

## Production handoff and feedback

| Method and path | Admin behavior |
| --- | --- |
| `GET /handoffs` | Lists existing handoffs. Accepts `status` and pagination. A brief without a row has `handoff_status=NOT_HANDED_OFF` in its detail. |
| `POST /handoffs` | Selects a Claude-approved brief using `{"brief_id":"…"}`. Repeated selection returns the existing row and deduplication key. |
| `GET /handoffs/{handoff_id}` | Returns the handoff's persisted state, delivery receipt and timestamps. |
| `POST /handoffs/{handoff_id}/send` | Takes no body. Formats the approved brief in Vietnamese with a link to its dashboard detail and returns the updated handoff after dispatch or receipt lookup. Returns `501` when Telegram is unavailable. |
| `POST /handoffs/{handoff_id}/check-ack` | Returns the current handoff, including any recipient acknowledgement recorded by the runtime poller. Returns `501` when Telegram is unavailable. |
| `GET /feedback` | Lists feedback, newest first. Accepts `brief_id` and pagination. |
| `POST /feedback` | Records feedback on an approved brief with `brief_id` and `action`. Actions are `good`, `irrelevant`, `duplicate`, and `bad-source`. Returns `201` with the stored record. |

## Settings, audit, and system monitor

| Method and path | Admin behavior |
| --- | --- |
| `GET /settings` | Returns dashboard `preferences` and effective startup `budget`, `queue`, and `retention` settings. |
| `PUT /settings/{key}` | Takes `{"value": …, "reason":"…"}` and returns the audit record. Editable keys are `p1_threshold` (integer 0–100), `scan_intervals_minutes` (map of names to positive integer minutes), `priority_topics` and `excluded_topics` (string arrays), and `telegram_enabled` (boolean). |
| `GET /settings/audit` | Returns source and preference changes in reverse audit order. Accepts pagination. |
| `POST /settings/audit/{record_id}/undo` | Takes `{"reason":"…"}`. Reverts a source or preference change when the current state still matches that record, and returns the new audit record. |
| `GET /monitor/ai` | Lists observed AI state, availability, quota flags and last safe errors. |
| `GET /monitor/queues` | Returns job counts for both `urgent` and `normal`, keyed by job status. |
| `GET /monitor/errors` | Lists recent job errors and expired attempts, newest first. Accepts pagination. |
| `GET /monitor/briefs` | Lists brief IDs, states and revision counts for operations monitoring. Accepts `status` and pagination. |
| `GET /monitor/briefs/{brief_id}` | Returns a submitted draft and its review history, including pending and failed reviews. |

To regenerate the OpenAPI file from the `backend` directory after installing the package, run the following command.

```powershell
python -c "import json; from pathlib import Path; from hunter.api.app import create_app; schema = create_app().openapi(); schema['servers'] = [{'url': '/api'}]; Path('../docs/openapi.json').write_text(json.dumps(schema, ensure_ascii=False, indent=2) + chr(10), encoding='utf-8', newline=chr(10))"
```
