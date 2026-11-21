# T7a — Ingest: normalize, dedup, cluster (Codex)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. Then read `backend/hunter/ingest/contracts.py` (fixed by the orchestrator — implement it exactly, do not change it), `backend/hunter/db/migrations/0001_foundation.sql` (tables `raw_items`, `fingerprints`, `trend_clusters`, `trend_cluster_members`), `backend/hunter/services/operations.py` (`store_raw_item`), `backend/hunter/models/sources.py`, `docs/FEASIBILITY.md`.

## Goal
Take `RawItem`s from connectors and turn them into clean, deduplicated stored items with trend clusters. Rule-based only (no AI, no new dependencies). Pipeline task T7b codes against `contracts.py` in parallel, so the names and signatures there are binding.

## Files you may touch (ONLY)
- `backend/hunter/ingest/**` EXCEPT `contracts.py` (read-only)
- `backend/hunter/connectors/**` (only for the YouTube cleanup below)
- `backend/tests/test_ingest_*.py`, `backend/tests/test_connectors_*.py`, `backend/tests/fixtures/connectors/**`

## 1. `ingest/normalize.py`
- `canonical_url(url)`: lowercase scheme+host, drop fragment and default ports, remove tracking params (`utm_*`, `fbclid`, `gclid`, `igshid`, `si`, `ref`, `ref_src`, `mc_cid`, `mc_eid`), sort remaining params, strip a trailing slash except for the root. Reject non-http(s), embedded credentials, localhost/private IPs (reuse the `PublicUrl` rules from `hunter.models.common`).
- `normalize_title(text)`: NFKC, collapse whitespace, strip, keep Vietnamese/Chinese characters intact; `title_tokens(text)` for similarity (casefolded, punctuation-stripped, stop-words minimal).
- `detect_language(text)`: rule-based by Unicode ranges and Vietnamese diacritics → `"zh"`, `"vi"`, `"en"` or `"und"`. Never guess beyond the rules.

## 2. `ingest/fingerprint.py` + `ingest/service.py` (`Ingestor` implements `IngestPort`)
- Exact fingerprints written to the existing `fingerprints` table: kind `url` (sha256 of the canonical URL), kind `external` (sha256 of `source_id|external_id` when present), kind `title` (sha256 of the normalized, casefolded title — only for titles of at least 3 tokens, so one-word trends do not collide).
- `Ingestor.ingest(source, items)`: per item, in ONE `BEGIN IMMEDIATE` transaction: validate/normalize → if ANY exact fingerprint already exists, count a duplicate and write nothing → else insert the `raw_items` row (same columns/JSON conventions as `OperationsService.store_raw_item`, do not edit that service) and its fingerprints. Concurrent ingests of the same item must produce exactly one row (rely on the fingerprint primary key). A single bad/invalid item is counted in `rejected_count`; the rest continue.
- **Metadata added at ingest time** (the brief drafter and scorer read these; without them briefs show unknown platform/type): `metadata["platform"] = source.platform`, `metadata["language"]` via `detect_language` when the connector did not set it, `metadata["content_type"]` from a table keyed by connector id (hacker_news → `"tin công nghệ / thảo luận"`, google_trends_vn → `"xu hướng tìm kiếm"`, wikimedia_top → `"bài viết bách khoa"`; unknown connector → leave unset, never invent), and `metadata["canonical_url"]`. Never overwrite a value the connector set.
- `get_item(raw_item_id)` rebuilds the `RawItem` exactly (including `metrics`, `metrics_snapshot_at`, timestamps in UTC).
- Provide `collect(connector, source, ingestor, operations, *, since, limits)`: calls `connector.fetch`, passes items to `ingest`, records real connector health via `OperationsService.record_connector_health(connector.health())`; on `ConnectorError` it records the degraded health and re-raises (no swallowing, no fake success).

## 3. `ingest/cluster.py` (`ClusterService` implements `ClusterPort`)
Rule-based grouping into the existing `trend_clusters` / `trend_cluster_members` tables, within a configurable window (default 72 h): two items belong together when they share a canonical URL or `metadata["article_url"]`, or their title-token Jaccard similarity is ≥ 0.6 (and each has ≥ 3 tokens), or a Google-Trends query appears as a title/entity of another item. A cluster needs ≥ 2 distinct items; a single item returns `None` from `assign`. Cluster `topic` = the representative title; `viral_signals_json` = a compact list of the observed signals (metric name + value + source id, never invented); `trend_status` = `"emerging"` for new clusters, `"rising"` when members from ≥ 2 distinct sources arrive; `trusted` member flag = source reliability ≥ 70 when known. Idempotent: assigning the same item twice changes nothing. `related_items(id, limit)` returns the item first, then the other members newest first.
(Admin split/merge and series grouping are out of scope.)

## 4. YouTube cleanup (connectors)
Live verification proved there is no legitimate keyless path: `/xml/feeds/videos.xml` is a static PubSubHubbub descriptor with no entries, and the real feed `/feeds/videos.xml` is `Disallow`ed in youtube.com/robots.txt (see `docs/FEASIBILITY.md`). Remove `connectors/youtube_channel.py`, its registry entry, its fixture and its tests, and make sure nothing still imports it. Do not leave a connector that reports success with 0 items.

## Tests (fakes + real temp SQLite via the T1 `Database`)
URL canonicalization table, title/language rules incl. Vietnamese and Chinese samples, exact duplicate suppression across url/external/title, concurrency (two threads ingesting the same item → one row), invalid item counted not fatal, metadata injection and no-overwrite, `get_item` round trip, clustering (shared URL, similar titles, trends↔article, singleton stays None, idempotent, window), `collect` health recording and error propagation.

## Done when
Tests pass; report lists exact public names so T7c can wire them, e.g. `from hunter.ingest import Ingestor, ClusterService, collect`.
