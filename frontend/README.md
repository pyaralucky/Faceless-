# Faceless AI Studio — Frontend

Next.js 15 (App Router) + React 19 + TypeScript (strict) + Tailwind CSS 3 web app for
Faceless AI Studio: a multi-tenant SaaS for researching, scripting, rendering and
publishing faceless AI videos. It talks to the FastAPI backend in `../backend`.

## Quick start

```bash
cd frontend
cp .env.example .env.local      # adjust NEXT_PUBLIC_API_URL if needed
npm ci
npm run dev                     # http://localhost:3000
```

The backend must be running (default `http://localhost:8000`) and must allow the
frontend origin via its `CORS_ORIGINS` setting (default `http://localhost:3000`).
For the social OAuth flow, the backend's `FRONTEND_URL` must point at this app so
that callbacks land on `/accounts?connected=…` / `/accounts?error=…`.

## Environment variables

| Variable              | Default                 | Description                                                                 |
| --------------------- | ----------------------- | --------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Public base URL of the backend (no trailing slash). Inlined at build time. |

Because `NEXT_PUBLIC_*` values are compiled into the client bundle, changing the API
URL requires a rebuild (or a new Docker image built with a different build arg).

## Scripts

| Command             | What it does                                     |
| ------------------- | ------------------------------------------------ |
| `npm run dev`       | Start the dev server with hot reload             |
| `npm run build`     | Production build (`output: "standalone"`)        |
| `npm start`         | Serve the production build (`next start`)        |
| `npm run lint`      | ESLint (`next/core-web-vitals` + TypeScript)     |
| `npm run typecheck` | `tsc --noEmit`                                   |
| `npm test`          | Vitest unit tests (API client)                   |

## Docker

```bash
docker build -t faceless-frontend --build-arg NEXT_PUBLIC_API_URL=https://api.example.com .
docker run -p 3000:3000 faceless-frontend
```

The image is multi-stage on `node:22-alpine`, runs as a non-root user (`nextjs`, uid 1001)
and ships only the Next.js standalone server (`node server.js`).

## Architecture

```
src/
  app/
    (auth)/login, (auth)/register     public pages
    (app)/…                           authenticated pages inside the app shell
      dashboard, channels, projects, projects/[id] (overview · agents · assets · render · publish),
      accounts, publishing, approvals, analytics,
      settings/api, settings/team, settings/profile, admin/users
  components/
    app-shell.tsx    sidebar nav, org switcher, create-org, auth guard, mobile drawer
    ui.tsx           buttons, inputs, modal, tabs, badges, tables, empty/error states …
    toast.tsx        toast notifications
    project/*        project workspace tabs and agent output renderers
    publish-job.tsx  publish job row/edit modal shared by the project & queue pages
    line-chart.tsx   dependency-free SVG line chart
  lib/
    api.ts           typed API client (auth, refresh, tenant header, error envelope)
    types.ts         TypeScript mirrors of backend Pydantic schemas
    auth.tsx         AuthProvider / useAuth (user, memberships, current org, role checks)
    hooks.ts         useQuery (fetch + polling), useDebounced, authenticated blob URLs
    format.ts        formatting helpers, role ranking, password policy
```

### API client behaviour

- Every request goes to `${NEXT_PUBLIC_API_URL}/api/v1…` with `Authorization: Bearer <access>`.
- Org-scoped requests add `X-Org-Id` from the selected organization (persisted in
  `localStorage`, defaulting to the user's first membership).
- On `401` the client performs **one** `POST /auth/refresh` (concurrent requests share
  the same in-flight refresh), stores the rotated token pair and retries the request
  once. If the refresh fails, tokens are cleared and the browser is sent to `/login`.
- Errors are normalized from `{"error": {code, message, details, request_id}}` into
  `ApiError`; `fieldErrors` maps validation `details.errors[]` to form fields.
- Protected media (asset files, rendered videos, thumbnails) are fetched with auth
  headers as blobs and displayed through object URLs.

### Roles

`viewer < reviewer < editor < admin < owner`. The UI hides or disables actions the
current role cannot perform (e.g. approve/reject needs reviewer, create/edit needs
editor, API configuration and team management need admin). The backend remains the
source of truth and enforces every permission.

Polling intervals: dashboard 10s, active agent run 2s, active render 2s, publish lists 10–15s.
Polling pauses while the browser tab is hidden.
