# Viral Content Hunter — Admin Dashboard

Admin Dashboard UI for the **Viral Content Hunter** system, built with React 18, TypeScript (strict mode), and Vite.

Source of truth for product specifications: `idead.md` (§10 Content Brief, §11 Review states, §12 Dashboard, §13 Telegram handoff, §14 Feedback, §17 Budget policy 0 VND).
API specification: `docs/openapi.json`, `docs/API.md`, and `dashboard/RECONCILE.md`.

---

## 1. Quick Start

### Prerequisites
- Node.js 18+ and npm / pnpm.

### Development Mode
```bash
cd dashboard
npm install
npm run dev
```
The Vite dev server runs at `http://localhost:3000` and automatically proxies all `/api` requests to the FastAPI backend running at `http://127.0.0.1:8000`.

### Production Build
```bash
cd dashboard
npm run build
```
This runs strict TypeScript verification (`tsc`) followed by Vite compilation (`vite build`). Output assets are written to `dashboard/dist/`.

---

## 2. Architecture & API Adapter Layer

All backend HTTP communication is encapsulated into a thin, strongly-typed adapter fully aligned with the backend OpenAPI specification:

```
dashboard/
├── RECONCILE.md        # Detailed API alignment report & documented gaps
├── src/
│   ├── api/
│   │   ├── client.ts       # Unified fetch wrapper (base URL, JSON, Bearer token auth, 401 redirect)
│   │   ├── types.ts        # Strongly-typed DTOs aligned with docs/openapi.json
│   │   └── endpoints.ts    # Typed API functions mapped to real FastAPI routes
│   ├── context/
│   │   └── AuthContext.tsx # Bearer session token state & auto session validation
│   ├── components/         # Shared semantic UI components (Modals, Badges, Header, Sidebar)
│   ├── pages/              # 8 primary screens
│   └── styles/
│       └── global.css      # Plain CSS with CSS variables, light + dark mode (prefers-color-scheme)
```

### HTTP Client (`src/api/client.ts`)
- **Base URL**: Configured via `import.meta.env.VITE_API_BASE`, defaulting to `/api`.
- **No login**: there is no session, token or login page. The server only answers this machine (`backend/hunter/api/local_guard.py`).
- **Error Handling**: Custom `ApiError` class with HTTP status code and server validation details.

### Endpoints (`src/api/endpoints.ts`) & Types (`src/api/types.ts`)
Each endpoint maps directly to the backend routers:
- `health`: `GET /health`
- `briefs`:
  - `GET /briefs/inbox` (Discovery Inbox, approved briefs only)
  - `GET /briefs/:id` (Content Detail + Review History)
  - `GET /briefs/:id/export/:format` (Markdown / JSON export)
- `jobs`: `GET /jobs`, `GET /jobs/:id`, `GET /jobs/:id/attempts`
- `sources`: `GET /sources`, `POST /sources`, `GET /sources/health`, `GET /sources/:id`, `PUT /sources/:id`, `POST /sources/:id/remove`
- `handoffs`: `GET /handoffs`, `POST /handoffs`, `GET /handoffs/:id`, `POST /handoffs/:id/send`, `POST /handoffs/:id/check-ack`
- `feedback`: `GET /feedback`, `POST /feedback` (Actions: `good`, `irrelevant`, `duplicate`, `bad-source`)
- `settings`: `GET /settings`, `PUT /settings/:key`, `GET /settings/audit`, `POST /settings/audit/:id/undo`
- `monitor`: `GET /monitor/ai`, `GET /monitor/queues`, `GET /monitor/errors`, `GET /monitor/briefs`, `GET /monitor/briefs/:id`

---

## 3. Product Rules & Constraints Compliance

1. **No Fake Data**:
   - Zero hardcoded mock items or synthetic numbers.
   - Every data table and detail view explicitly handles `loading`, `empty`, and `error` states.
2. **0 VND Budget Policy**:
   - The Settings page displays the "Paid APIs: Vô hiệu hóa vĩnh viễn" (0 VNĐ/tháng) policy as strictly **read-only**.
   - No UI exists to activate paid API subscriptions, cloud VPS, proxy, or captcha bypass services.
3. **Claude Review Rule**:
   - The Discovery Inbox exclusively displays briefs that have been vetted and approved by Claude (`APPROVED_BY_CLAUDE`).
4. **Separate Scores**:
   - In Content Detail, Virality Score, Relevance Score, Credibility Score, and Priority are presented separately with dedicated reason explanations; they are never merged into an unexplainable single score.
5. **Metadata Warning Banner**:
   - If a brief's summary was generated from metadata only (`metadata_only: true`), a prominent warning banner alerts the user before video production.
6. **Telegram Handoff Lifecycle**:
   - The Handoff Board clearly separates "Đã gửi Telegram (`SENT`)" from "Đã xác nhận tiếp nhận (`ACKNOWLEDGED`)".
   - Outward-facing actions (sending to Telegram, retrying) require explicit confirmation dialogs.
   - Telegram Bot Token is treated as write-only / env-only and is never rendered back in the UI.
