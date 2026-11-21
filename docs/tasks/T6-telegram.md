# T6 — Telegram notifier, acknowledgement and P1 alerts (Codex)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies (Telegram Bot API is free). Read `idead.md` §13, `docs/FEASIBILITY.md` (E3), `docs/ARCHITECTURE.md` (Handoff workflow + `Notifier`), `backend/hunter/interfaces/notifier.py`, `backend/hunter/services/handoffs.py`, `spikes/e3_telegram.py`.

## Goal
A real `Notifier` for Telegram with durable idempotent delivery, an acknowledgement flow, and the P1 alert policy. No network in your sandbox: all HTTP is injectable and tested with fakes; the orchestrator runs the live test with the real test bot.

## Files you may touch (ONLY)
- `backend/hunter/telegram/**`
- `backend/tests/test_telegram_*.py`

## 1. `TelegramNotifier` (implements `Notifier`; `incurs_cost = False`)
- Credentials ONLY from env `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (injectable for tests). Never log or persist them; redact the token from every exception/diagnostic (the token appears in the request URL — never put the URL in an error message).
- stdlib `urllib` only, injectable transport, TLS verification on, no proxies, bounded timeouts, response size cap.
- **Durable ledger** in its own SQLite file (path injectable, default under `backend/data/`, which is git-ignored) — do NOT change the T1 schema. A dedup key is reserved BEFORE sending. States: `reserved → sent(receipt) | failed | unknown`.
  - `send(message, dedup_key)`: if a receipt exists for the key → return it, never resend. If the key is reserved/unknown (crash or ambiguous network result) → return `UNKNOWN` and do NOT resend. Only a definitive Telegram failure (HTTP 4xx with `ok:false`, or clearly not delivered) allows the same key to be sent again. Telegram has no client idempotency key — document this limit in the module docstring.
  - Network error/timeout/5xx after the request left → `UNKNOWN`.
  - `lookup_send(dedup_key)`: reads the ledger only, no dispatch.
- Messages are plain text or MarkdownV2 with CORRECT escaping (test escaping of every special character) — prefer plain text unless formatting is needed. Respect Telegram's 4096-character limit (truncate with an ellipsis and keep the Dashboard link).
- Attach an inline keyboard to handoff messages with one button `✅ Đã nhận` whose `callback_data` encodes the dedup key (≤ 64 bytes: use a short stable hash mapped in the ledger).

## 2. Acknowledgement — `check_ack(external_id, dedup_key)`
Acknowledged only on an explicit recipient action: a `callback_query` from the configured chat for that key (or a reply to that message). "Sent" is never "read". Implement `poll_updates()` using `getUpdates` with a persisted `offset` and `allowed_updates=["callback_query","message"]`, answer the callback (`answerCallbackQuery`) and record the ack in the ledger. Ignore updates from other chats. `check_ack` reads the ledger (after calling `poll_updates` if a poller is configured). Only ONE consumer may call `getUpdates` — note this in the docstring.

## 3. P1 alert policy — `telegram/alerts.py`
`should_alert(brief: ContentBrief, *, now, cluster_alerted: bool, ...) -> AlertDecision(allowed, reasons)`; allowed ONLY when ALL hold (§13.1): brief status is `APPROVED_BY_CLAUDE`; priority is P1 and score threshold satisfied; traceable source URL; verification satisfied; still fresh (configurable max age, e.g. 12 h from `published_at` or `discovered_at`); not previously alerted for the same Trend Cluster without material new development; not a duplicate alert key. Backlogged P1 (machine was off / quota out) must re-check freshness and signals before sending. Return explicit `reasons` for every denial. Build the Vietnamese alert text: title, short summary, score + priority, source, why notable (first lines), Dashboard link (base URL injectable).

## 4. Handoff message
`format_handoff(brief, dashboard_url)` → Vietnamese message with the Content Brief essentials + Dashboard URL (§13.2).

## Tests (fakes only)
Idempotent send (same key twice → one dispatch), crash between reserve and confirm → `UNKNOWN` and no resend, definitive failure permits retry, token never appears in exceptions/logs (assert), 4096 truncation, escaping, callback ack from the right chat vs a foreign chat, offset persistence, `should_alert` for each denial reason, stale backlog P1 denied.

## Done when
Tests pass; report gives the live test commands, e.g. `python -m hunter.telegram.smoke send-test` and `... poll` (create a tiny `telegram/smoke.py` printing only status/receipt id masked — never the token or chat id).
