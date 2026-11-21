# Viral Content Hunter — Admin Dashboard

Admin Dashboard UI for the **Viral Content Hunter** system, built with React 18, TypeScript (strict mode), and Vite.

Source of truth for product specifications: `idead.md` (§10 Content Brief, §11 Review states, §12 Dashboard, §13 Telegram handoff, §14 Feedback, §17 Budget policy 0 VND).

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

All backend HTTP communication is encapsulated into a thin, strongly-typed adapter to allow seamless reconciliation when the backend API and OpenAPI specifications land:

```
dashboard/src/
├── api/
│   ├── client.ts       # Unified fetch wrapper (base URL, JSON, credentials: 'include', 401 redirect)
│   ├── types.ts        # All DTO and entity types (all guessed shapes marked with TODO(reconcile))
│   └── endpoints.ts    # Typed API functions mapped to backend endpoints
├── context/
│   └── AuthContext.tsx # Authentication session state & user credentials
├── components/         # Shared semantic UI components (Modals, Badges, Header, Sidebar)
├── pages/              # 8 primary screens
└── styles/
    └── global.css      # Plain CSS with CSS variables, light + dark mode (prefers-color-scheme)
```

### HTTP Client (`src/api/client.ts`)
- **Base URL**: Configured via `import.meta.env.VITE_API_BASE`, defaulting to `/api`.
- **Session Credentials**: Always includes credentials (`credentials: 'include'`).
- **Error Handling**: Custom `ApiError` class with HTTP status code and server details.
- **Auth Interception**: Automatically redirects unauthenticated requests (HTTP 401) to `/login`.

### Endpoints (`src/api/endpoints.ts`) & Types (`src/api/types.ts`)
Each endpoint maps to one of the backend routers:
- `health`: `GET /health`
- `auth`: `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`
- `briefs`:
  - `GET /briefs?review_status=APPROVED_BY_CLAUDE` (Discovery Inbox)
  - `GET /briefs/:id` (Content Detail)
  - `GET /briefs/:id/export/md` (Markdown Export)
  - `GET /briefs/:id/export/json` (JSON Export)
  - `GET /briefs/clusters/:id` (Trend Cluster)
  - `GET /briefs/series/:id` (Series Brief)
- `jobs`: `GET /jobs`
- `sources`: `GET /sources`, `PATCH /sources/:id/status`
- `handoffs`:
  - `GET /handoffs`
  - `POST /handoffs/select`
  - `POST /handoffs/approve`
  - `POST /handoffs/retry`
  - `POST /handoffs/acknowledge`
- `feedback`: `POST /feedback` (Actions: `good`, `irrelevant`, `duplicate`, `bad_source`)
- `settings`: `GET /settings`, `PUT /settings`
- `monitor`: `GET /monitor`, `GET /monitor/overview`

All guessed shapes are tagged with `// TODO(reconcile with docs/openapi.json)`.

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
   - If a brief's summary was generated from metadata only (`is_metadata_only_summary: true`), a prominent warning banner alerts the user before video production.
6. **Telegram Handoff Lifecycle**:
   - The Handoff Board clearly separates "Đã gửi Telegram" from "Đã xác nhận tiếp nhận" to ensure items are acknowledged by human creators.
   - Outward-facing actions (sending to Telegram, retrying) require explicit confirmation dialogs.
   - Telegram Bot Token is treated as write-only and is never rendered back in the UI.
