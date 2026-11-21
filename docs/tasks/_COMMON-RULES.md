# Common rules for every task (read this + `AGENTS.md` first)

Product rules: `idead.md` (Vietnamese). Contracts you code against: `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/openapi.json`, `backend/hunter/interfaces/*`, `backend/hunter/models/*`. Verified facts about this machine and sources: `docs/FEASIBILITY.md`.

## 1. Zero extra cost (user requirement, no exceptions)
Nothing may cost money beyond the user's existing AI subscriptions. No API keys, no paid APIs/proxies/CAPTCHA solvers/cloud, no card-required trials, no new paid packages. If something needs payment or a quota is exhausted: STOP, report `BLOCKED`, never switch to a paid path. Full text in `AGENTS.md`.

## 2. File ownership — touch ONLY the paths listed in your task
Parallel agents work in the same checkout. Another agent edits the other paths at the same time.
- Never edit `backend/hunter/{db,models,queue,state,interfaces,services,api}`, `config.py`, `pyproject.toml`, `docs/openapi.json`, `docs/API.md`, `docs/ARCHITECTURE.md`, `.gitignore` — they belong to the finished T1. If you need a change there, do NOT make it: describe it precisely in your final report.
- New dependencies are NOT allowed (Python: standard library + what `pyproject.toml` already lists; dashboard: what `package.json` has). If you believe one is needed, stop and report why.
- Do NOT run `git commit`, `git push`, `git add`, or change git config. The orchestrator commits.
- Never print, log, store or commit secrets. Never read `.env`. Credentials come from environment variables only and are provided by the orchestrator at run time.

## 3. Honesty / no fake data
- No data presented as real unless it was fetched from a real source. Test doubles are allowed in tests only and must be named as fakes/fixtures. Real captured sample responses may be put under `backend/tests/fixtures/<task>/` ONLY if the orchestrator supplies them.
- Never mark something done that you could not run. Say exactly what you ran and what you could not.
- A connector/adapter counts as working only when verified with real data/CLI by the orchestrator outside your sandbox.

## 4. Sandbox facts (Codex agents)
Your sandbox has NO network, may lack a home dir, and cannot `taskkill`. So:
- Never attempt real network calls. Make all I/O injectable (transport/runner parameters) and test with fakes.
- Real-world smoke tests are run by the orchestrator. Say precisely how to run them (a short `python -m ...` command) in your report.
- Run tests with: `D:\Agent Viral Content Hunter\.venv\Scripts\python.exe -m pytest -q <your test files>` (from the repo root). If you cannot run them, say so.

## 5. Sandbox facts (Gemini agents via `agy`)
You have NO shell. Use only file view/create/edit tools. You cannot run tests or builds; write code carefully. The orchestrator will run tests/builds and send you the errors to fix.

## 6. Code quality
Python 3.12, full type hints, small modules, no dead code, no speculative abstractions. Match existing style in `backend/hunter`. All timestamps timezone-aware UTC. Errors carry credential-free messages. Prefer boring and simple (idead.md §1.9).

## 7. Final report (your last message)
List: files created/changed; what you ran and the real results; what you could NOT verify; any contract change you need from T1; how the orchestrator can smoke-test it.
