# T2 — Connectors (Codex)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. Then read `docs/FEASIBILITY.md` (what real sources returned) and `backend/hunter/interfaces/connector.py`.

## Goal
Implement real, free, public-data connectors against the `Connector` protocol, plus a small shared HTTP helper and a registry. No network in your sandbox: make HTTP injectable and test with fakes; the orchestrator will run live smoke tests.

## Files you may touch (ONLY)
- `backend/hunter/connectors/**`
- `backend/tests/test_connectors_*.py`, `backend/tests/fixtures/connectors/**` (fixtures must be tiny hand-written samples that follow each source's documented format; label them as fixtures)

## Connectors (all return `RawItem` with timezone-aware UTC times)
Study `spikes/e2_sources.py` and `docs/FEASIBILITY.md` — it contains the endpoints that worked and the exact fields observed.
1. **`hacker_news`** — official Firebase API (`https://hacker-news.firebaseio.com/v0/`): `topstories.json` then `item/<id>.json`. `source_url` = the HN discussion URL (`https://news.ycombinator.com/item?id=<id>`); put the linked article in `metadata["article_url"]`. `external_id` = HN id. `metrics.comments` = HN `descendants`. HN `score` is NOT likes: store it as `metadata["hn_score"]`. No views. `metrics_snapshot_at` = fetch time when metrics present. Respect `FetchLimits.max_items`; fetch items with a small bounded concurrency (≤ 4) and only as many as needed.
2. **`google_trends_vn`** — RSS `https://trends.google.com/trending/rss?geo=VN`. One `RawItem` per trending query: `title` = query, `source_url` = first linked news URL if public else the Trends page, `published_at` from RFC 822 date, approximate traffic text in `metadata["search_traffic_label"]` (string, never converted to a number), related news items in `metadata["news"]`.
3. **`wikimedia_top`** — Wikimedia Analytics pageviews `.../metrics/pageviews/top/en.wikipedia/all-access/YYYY/MM/DD` for the most recent day that has data (try yesterday, then the day before; data lags). Skip `Main_Page`, `Special:*`, `Wikipedia:*`, `-`. `metrics.views` = views, `metadata["pageviews_date"]`, `metadata["rank"]`. `source_url` = canonical en.wikipedia article URL.
4. **`youtube_channel`** — public Atom feed of a configured channel (`https://www.youtube.com/xml/feeds/videos.xml?channel_id=<id>`), channel ids supplied by the caller (never hard-code someone else's channel as a default). The earlier spike got HTTP 200 but parsed 0 items: parse the Atom feed robustly using namespaces `http://www.w3.org/2005/Atom`, `http://search.yahoo.com/mrss/` and `http://www.youtube.com/xml/schemas/2015` (`yt:videoId`), including `media:community/media:statistics@views` and `media:starRating`. Test with a hand-written fixture of the documented format. Report what you could not confirm.

Do NOT build TikTok/Douyin/Reddit/Weibo connectors: T0 showed no legitimate free path (see `docs/FEASIBILITY.md`).

## Shared pieces
- `connectors/http.py`: stdlib `urllib` only; injectable `Transport` (callable) so tests never touch the network; generic User-Agent `ViralContentHunter/0.1` (NO email/personal data); TLS verification on; no proxies, no cookies, no auth headers; per-call timeout from `FetchLimits.timeout_seconds`; max response size (e.g. 2 MiB); on HTTP 429/403/redirect-to-gate raise `ConnectorError` with a credential-free message and honour `Retry-After` by exposing it (do not sleep inside the connector); do NOT follow redirects to a different host; no automatic retries.
- Each connector keeps real health: after each `fetch`, `health()` reports `AVAILABLE` (with `last_success_at`), `DEGRADED` or `UNAVAILABLE` with a safe `last_error`. Never report healthy without a successful fetch.
- `connectors/registry.py`: `available_connectors()` returning the connector ids + factory functions, and `default_sources()` returning `SourceInput` objects (real public URLs) for the first three connectors. Do not write to the DB here.
- Items must pass `RawItem` validation (PublicUrl etc). Drop items that fail validation individually and count them in a connector diagnostic; never crash the whole fetch for one bad item.

## Tests (use fakes for the transport)
Parsing of each source's documented format, limits respected, 429/403/redirect handling, bad item dropped, health transitions, no network access attempted (assert the injected transport is the only I/O), `metrics_snapshot_at` always set when metrics exist.

## Done when
`pytest -q` for your tests passes; report includes the exact live smoke-test command, e.g. `python -m hunter.connectors.smoke hacker_news` (create a tiny `connectors/smoke.py` CLI that prints counts and the first item's title/URL only — no secrets).
