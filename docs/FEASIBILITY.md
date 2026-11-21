# Feasibility verdict (T0) — Leader's consolidated result

Date: 2026-11-22. Machine: Windows 11, 10 physical / 16 logical cores, 31.8 GiB RAM, AMD RX 6600, ~21 GiB free disk.
Raw evidence: `spikes/REPORT.md`, `spikes/out/*.json`. Reproduce: `python spikes/run_all.py` **from a normal shell**.

> **Important correction.** Codex's first T0 run reported E1/E2 as BLOCKED because its sandbox has no network (`PermissionError 10013`, DNS `11001`), no home dir and denies `taskkill`. Those were sandbox artefacts, not facts about the platform. The results below come from re-running outside the sandbox. **Any task that needs network, process control or a home directory must be run/verified by the orchestrator outside the Codex sandbox.**

## Status per experiment
| # | Experiment | Verdict | One-line truth |
|---|---|---|---|
| E1 | AI CLI non-interactive | Codex PASS · Gemini(`agy`) PASS with caveats · Claude NOT TESTED | see below |
| E2 | Public sources | 4 PASS, 2 FAIL, 2 BLOCKED | real data from HN, Google Trends VN, Wikimedia, TikTok oEmbed (known URL only) |
| E3 | Telegram | BLOCKED | needs `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` from the user |
| E4 | Queue crash recovery | PASS | `taskkill /F` and `/F /T`: 4 jobs retained, 3 unique completions, 1 dead letter, lease reclaimed |
| E5 | Host / local AI | PASS (survey) | no local runtime installed -> **rule-based fallback for MVP** |

## E1 — AI CLIs (verified by hand, tiny prompts, subscription logins only)
- **Codex** — PASS. Task via the codex-companion returned a real answer on the ChatGPT login. Detectable failures observed: quota -> message `You've hit your usage limit … try again at <time>`; auth change -> `Your access token could not be refreshed because you have since logged out or signed in to another account`. After re-login the **shared broker keeps the old token**: restart only this session's `app-server-broker.mjs` tree. Raw `codex exec --json --output-schema` not exercised.
- **Gemini via Antigravity CLI** — PASS with caveats. Standard `gemini` CLI is NOT installed; use `%LOCALAPPDATA%\agy\bin\agy.exe` (not on PATH). `agy -p "<prompt>" --output-format json --mode accept-edits --model gemini-3.8-flash-high` returns JSON. **Caveat:** in headless mode a denied tool call still returns `status: "SUCCESS"` with an empty `response`; always check `response` non-empty and `denied_actions` empty. Prompts that forbid shell tools and inline the spec worked. Quota-exhausted / auth-lost patterns: unverified.
- **Claude Code** — NOT TESTED live. `claude -p --output-format json` is documented. The login is a Claude **Team** plan; whether paid usage credits are enabled cannot be verified from here. **User action:** confirm extra usage / usage credits are OFF, then the orchestrator may run a one-prompt test. Until then Claude review runs only in an interactive Claude Code session.
- No API key variable is set at User/Machine scope; child processes must still strip them (see `AGENTS.md`).

## E2 — sources (real samples in `spikes/out/e2_*.json`)
| Source | Verdict | What we really get | Limits |
|---|---|---|---|
| Hacker News (Firebase) | PASS | title, HN link + article URL, score, comments, publish time | no view counts |
| Google Trends VN RSS | PASS | trending query, linked news URL, approx. search-traffic label | traffic label is approximate |
| Wikimedia pageviews | PASS | top articles with daily views and rank | daily granularity, English Wikipedia sample |
| TikTok oEmbed | PASS (narrow) | embed metadata for a **known** video URL | no discovery, no engagement/publish time, docs announce deprecation |
| Reddit `.json` | BLOCKED | — | robots.txt disallows; not bypassed |
| Weibo hot search | BLOCKED | — | 302 redirect to a gate; not followed/bypassed |
| YouTube channel feed | FAIL | HTTP 200 but 0 items parsed | parsing issue or wrong channel id; T2 must investigate before claiming it |
| Douyin public page | FAIL | HTTP 200, 0 items parsed | page is not parseable without a browser/login; no legitimate free path found |

**Honest conclusion on the product's two priority sources:** with free, legitimate, no-login endpoints we can **not** do viral *discovery* on TikTok or Douyin today. We can enrich a known TikTok URL via oEmbed. Do not claim a Douyin/TikTok connector is done. MVP discovery starts from HN, Google Trends VN and Wikimedia (cross-market signals), then YouTube once fixed, plus admin-supplied URLs/keywords.

## Decisions for the design
1. Build the SQLite persistent queue (WAL, leases, fenced, backoff, dead letter) — validated by E4.
2. First connectors: Hacker News, Google Trends VN, Wikimedia. TikTok oEmbed = enrichment only. YouTube after a fix.
3. Rule-based normalisation, dedup and scoring first; AI only for summary/translation/review.
4. Telegram needs user credentials before it can be verified.
5. Gemini calls go through `agy` with the empty-response/`denied_actions` guard; Codex calls through the companion.
