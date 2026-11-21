# T0 — Feasibility Spike

Source of truth for product rules: `idead.md` at the repo root (Vietnamese). Read §4.3, §6.5, §15–§17, §21 (Bước 2) first.

## Goal
Verify with REAL experiments what is actually possible on this Windows machine before the system is built. Output an honest report with `PASS` / `FAIL` / `BLOCKED` per experiment.

## Files you may touch (and ONLY these)
- `spikes/**`

Do NOT touch anything else. Do NOT run `git commit`, `git push`, or change git config. Another task (T1) is editing `backend/`, `docs/`, `config/` concurrently.

## Hard constraints (from idead.md)
- Budget is 0 VND/month. NEVER use paid APIs, paid proxies, CAPTCHA solvers, or any pay-per-token API.
- When spawning AI CLIs, REMOVE these env vars from the child process env so no API-key billing can happen: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`. Fail closed: if a CLI only works with an API key, report `BLOCKED`.
- Do not bypass CAPTCHA, login walls, rate limits or anti-bot protections. No cookies/tokens extracted from browsers. No fake view/like numbers. No mock data presented as real.
- Never print or log secrets (tokens, cookies, auth files). Redact before saving evidence.
- Keep request volume tiny (a handful of requests per source), polite User-Agent, respect HTTP 429/Retry-After.
- Keep AI CLI prompts tiny (e.g. "Return JSON {\"ok\":true}") to save subscription quota.
- Python 3.12 is installed. Use a venv at `spikes/.venv` if you need packages (prefer stdlib + `httpx`). Add `spikes/.gitignore` ignoring `.venv/` and `out/`.

## Experiments

### E1 — AI CLI non-interactive + structured output
For each of `claude` (Claude Code), `codex`, `gemini`:
- Is it installed? version?
- Can it run a task non-interactively and return machine-parseable output (e.g. `claude -p ... --output-format json`, `codex exec ...` with JSON/`--output-schema`/last-message file, `gemini -p ...`)? Use the CLI's own `--help` to find the right flags; do not guess.
- Does it use the existing subscription login (not an API key)?
- How can the orchestrator detect: auth lost, quota exhausted, timeout? Capture the exact exit codes/stderr patterns where you can observe them safely; otherwise document from `--help`/docs and mark as "unverified".
- `gemini` is currently NOT installed on this machine: report `BLOCKED` for Gemini and document the install + login steps the user would need. Do NOT install it yourself.

### E2 — Real data from free, legitimate public sources
Try at least these and record for each: endpoint used, HTTP status, whether real items came back with source URL + metadata (title, time, views/likes/comments if present), rate-limit behavior, ToS/robots notes, a verdict:
- Hacker News (official Firebase API and/or Algolia HN search API)
- Reddit public JSON (may be blocked; report honestly)
- YouTube (RSS feeds of channels / public pages; no paid Data API key)
- Google Trends public RSS (daily trending)
- Wikipedia / Wikimedia pageviews (trending articles)
- Weibo hot search (public endpoint, if reachable without login)
- TikTok: only legitimate public surfaces (oEmbed, public page without login). Report limits honestly.
- Douyin: only legitimate public surfaces without login/CAPTCHA. Report limits honestly.
Anything needing login/CAPTCHA/anti-bot = `BLOCKED`, not a workaround. Save a small REAL sample (redacted, ≤ 5 items per source) under `spikes/out/` as evidence.

### E3 — Telegram
- Script that sends a test message via Bot API and reads back `getUpdates`/`getMe` to confirm. Credentials come ONLY from env vars `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. If unset → `BLOCKED (needs user credentials)`; do not invent values and do not ask interactively.
- Document how to create the bot + find the chat id for the user (short).
- Verify the idempotency approach for avoiding duplicate sends (document the design; a real send is only exercised when creds exist).

### E4 — Job persistence & crash recovery
Prototype a minimal SQLite-backed queue (WAL mode) with: lease + heartbeat, retry counter (max 3, exponential backoff), idempotency key, dead-letter state. Then prove on Windows:
1. enqueue N jobs, start a worker process, hard-kill it mid-job (`taskkill /F`), restart;
2. no job lost, no job duplicated, retry/attempt counters preserved, expired lease reclaimed;
3. repeat with the whole machine-level scenario approximated by killing the process tree.
Record the real outputs.

### E5 — Host resources / Local AI (light)
CPU cores, RAM, GPU presence, free disk; whether Ollama (or similar) is installed. Do NOT download any model. Conclude whether local AI is viable or rule-based fallback is required.

## Deliverables
- `spikes/e1_ai_cli.py`, `spikes/e2_sources.py`, `spikes/e3_telegram.py`, `spikes/e4_queue_recovery.py`, `spikes/e5_resources.py` (each runnable standalone; any shared helper in `spikes/common.py`).
- `spikes/run_all.py` runs everything and regenerates `spikes/REPORT.md`.
- `spikes/REPORT.md`: table of experiment → PASS/FAIL/BLOCKED → evidence summary → limitations → recommendation for which connectors/AI integrations to build first. Be honest: a connector is only "PASS" if real data was fetched.

## Done when
- `python spikes/run_all.py` completes without crashing and produces `spikes/REPORT.md` with truthful statuses.
- No secrets in any saved file (grep for token-like strings before finishing).
- Nothing outside `spikes/` modified.
