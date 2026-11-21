# MANDATORY RULES FOR EVERY AGENT (Claude, Codex, Gemini/agy, any subagent, any script)

## ZERO-COST POLICY — user requirement, no exceptions

The user pays ONLY for the AI subscription plans they already have. **Nothing may cost extra money. Ever.**
Quy tắc của chủ dự án: tuyệt đối không dùng bất kỳ thứ gì phát sinh thêm phí.

### Forbidden (never use, never enable, never suggest as the default path)
- Pay-per-token / metered APIs: Anthropic API, OpenAI API, Gemini API, Vertex AI, or any other LLM API key.
- Paid data APIs or paid scraping services, paid proxies, CAPTCHA-solving services.
- VPS, cloud hosting, paid storage, paid databases, paid SaaS, or any service that requires a credit card, including "free trials" and "free tiers that need a card".
- Buying credits, upgrading a plan, enabling overage / extra usage, or following any "Upgrade" / "purchase more credits" prompt.
- Paid packages, licenses or fonts/assets. Use only free, open-source, no-account-needed libraries.
- Any command that can create a bill (cloud CLIs, deploy/publish commands, key/billing setup).

### Required
- Use AI only through the user's existing subscription logins via the official CLIs (Claude Code, Codex, Gemini/Antigravity `agy`).
- Never read, set, create, print or rely on API key environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_GENAI_USE_VERTEXAI`, ...). When spawning child processes, REMOVE them from the child env.
- When a quota is exhausted: stop that task, mark it `BLOCKED (quota)`, queue it, and wait for the quota to reset. Do NOT buy anything and do NOT switch to a paid path.
- If a task seems to need something paid: STOP, mark it `BLOCKED (needs paid service)`, report it to the orchestrator. **Fail closed.** Never "just try it".
- Before adding any dependency or external service, confirm it is free, open-source (or free without an account) and needs no payment method.
- Local-first: SQLite, local files, free public endpoints that need no key.

### Also always
- No fake data presented as real. No bypassing CAPTCHA, login walls, rate limits or anti-bot protection. No secrets in code, logs or commits.
- Stay inside the file scope given in your task spec (`docs/tasks/*.md`). Do not `git commit` / `git push` unless the orchestrator tells you to.
- Product rules live in `idead.md` (Vietnamese). When in doubt, follow it and ask the orchestrator.
