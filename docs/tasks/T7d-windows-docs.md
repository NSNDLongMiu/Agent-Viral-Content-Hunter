# T7d — Windows startup scripts + install/operations docs (Gemini)

> **MANDATORY: read `AGENTS.md` and `docs/tasks/_COMMON-RULES.md` first.** Zero extra cost applies. You have NO shell: use only file view/create/edit tools; the orchestrator runs and tests the scripts. Read `idead.md` §15–§18 and §23, `README.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/FEASIBILITY.md`, `config/settings.example.toml`, `dashboard/README.md`.

## Pinned interface (another agent is implementing it right now — code against exactly this)
- Project root = the folder containing `pyproject.toml`; Python venv at `.venv` (created with `python -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -e ".[test]"`).
- Launch command from the project root: `.venv\Scripts\python.exe -m uvicorn hunter.api.server:app --app-dir backend --host 127.0.0.1 --port 8000 --no-access-log`. It serves the API under `/api` and the built dashboard (`dashboard/dist`) at `/`.
- Dashboard build: `cd dashboard; npm install --ignore-scripts; npm run build`.
- Config: copy `config/settings.example.toml` to `config/settings.local.toml`; background work is enabled with `[runtime] enabled = true` or env `HUNTER_RUNTIME__ENABLED=1`. Admin password hash: `.venv\Scripts\python.exe -m hunter.api.auth` (interactive). Claude service token env `HUNTER_AUTH__CLAUDE_SERVICE_TOKEN`. Telegram env `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (stored in a git-ignored `.env`-style file the start script loads into the process environment, never into the repo).
- Seed sources: `.venv\Scripts\python.exe -m hunter.runtime seed-sources`.

## Files you may touch (ONLY)
- `scripts/windows/**`, `docs/INSTALL.md`, `docs/OPERATIONS.md`, `docs/CONFIGURATION.md`, `docs/TROUBLESHOOTING.md`

## Deliverables
1. `scripts/windows/install.ps1`: checks Python ≥ 3.12 and Node ≥ 20, creates the venv, installs the package, builds the dashboard, creates `config/settings.local.toml` from the example if missing, prints the next manual steps (admin password hash, tokens). Idempotent; never overwrites existing config; never prints secrets.
2. `scripts/windows/start-hunter.ps1`: loads the git-ignored env file (default `config/hunter.env`, `KEY=VALUE` lines, ignore comments), starts the launch command with output appended to `logs/hunter-YYYYMMDD.log` (create `logs/`), writes a PID file, refuses to start a second instance, restarts the process automatically with exponential backoff if it exits unexpectedly (cap the delay at 5 minutes, give up after 10 consecutive crashes within 10 minutes and write a clear log line). Loopback only.
3. `scripts/windows/stop-hunter.ps1`: stops the process tree gracefully, then forcefully after a timeout; cleans the PID file.
4. `scripts/windows/register-autostart.ps1` / `unregister-autostart.ps1`: create/remove a **per-user Scheduled Task** that runs `start-hunter.ps1` hidden at user logon (no admin rights, no service, no registry edits outside the task). **Both support `-DryRun`** which only prints what would be done. The default behavior of a bare call must be the dry run unless `-Apply` is given (this changes the machine, so it must never be silent).
5. `scripts/windows/status.ps1`: shows whether it is running, the port check against `/api/health`, last log lines, DB file size.
6. `docs/INSTALL.md` (from zero to working dashboard on Windows 11, including Telegram bot creation and `getUpdates` chat-id discovery), `docs/OPERATIONS.md` (daily use, what Claude Leader review means and how to run it with `python -m hunter.leader pending/decide`, backups with the 90-day retention note, restart behavior, how to read the Monitor screen), `docs/CONFIGURATION.md` (every config key and env var with defaults and what it does; the zero-cost rule), `docs/TROUBLESHOOTING.md` (quota exhausted, auth lost, `agy` empty-response guard, connector BLOCKED/robots, port in use, dashboard 404 under `/api`, access-denied temp dirs, Telegram not acknowledging).
Docs are for a non-expert Windows user; Vietnamese with command blocks in English; no marketing language; every claim must be something the project really does — if unsure, leave it out.

## Rules specific to the scripts
Windows PowerShell 5.1 compatible (no `&&`, no `?:`, no `??`), `Set-StrictMode -Version Latest`, `$ErrorActionPreference = 'Stop'`, quote all paths (the project path contains spaces), no `Invoke-Expression`, no downloads, no `Set-ExecutionPolicy` changes (document `powershell -ExecutionPolicy Bypass -File ...` for the user instead), never echo environment values. UTF-8 without BOM for logs.

## Done when
All files exist and are consistent with the pinned interface; final reply lists files and any assumption you could not verify without a shell.
