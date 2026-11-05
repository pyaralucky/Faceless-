# Faceless AI Studio

A multi-tenant SaaS for producing **faceless videos** end to end: AI agents research and script the video, an FFmpeg pipeline renders it in vertical and horizontal formats, and a publishing queue posts it to **YouTube** and **Instagram** through their official OAuth APIs, with approval workflows and analytics.

| Layer | Tech |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS |
| API | FastAPI, SQLAlchemy 2 (async), Pydantic v2 |
| Data | PostgreSQL 16 (JSONB), Redis 7 |
| Background jobs | arq (Redis) worker with cron scheduling |
| AI orchestration | LangGraph + a provider-agnostic model router (OpenAI, Anthropic, Google, OpenRouter, Azure OpenAI, Ollama, offline mock) |
| Video | FFmpeg / ffprobe / libass |
| Deployment | Docker, docker compose, GitHub Actions CI |

## Features

- **Auth and users**: email/password with bcrypt, short-lived JWT access tokens, rotating refresh tokens with reuse detection, rate-limited login, password change, and platform admin user management.
- **Multi-tenant workspaces**: organizations, memberships with roles (`owner > admin > editor > reviewer > viewer`), every query scoped by tenant, and an audit log.
- **Channels and projects**: channel brand kits (tone, audience, subtitle style, default format, approval policy), projects with a status lifecycle, and media asset uploads.
- **API configuration**: per-organization provider API keys encrypted at rest (Fernet with key rotation), plus per-agent model routes with temperature, token limits and ordered fallbacks.
- **AI agents**: research, strategy, scriptwriting, fact-checking, storyboarding and optimization agents. They are orchestrated with LangGraph and include a fact-check → rewrite loop. Outputs are validated JSON (Pydantic), with retries, exponential backoff, self-repair of invalid JSON, model fallback, token and cost tracking, a monthly token budget, and a per-attempt execution log.
- **Video pipeline**: takes images, video clips, narration, music, SRT subtitles and scene prompts, and produces 1080×1920 or 1920×1080 H.264/AAC MP4. It supports Ken Burns motion, xfade transitions, music ducking under narration, EBU R128 loudness normalization, styled ASS captions, headline overlays, thumbnails and automated quality checks. Renders run in the background, report progress live, are checkpointed and can be resumed or cancelled.
- **Publishing**: YouTube (Data API v3 resumable uploads, custom thumbnails) and Instagram Reels (Graph API content publishing). Includes scheduling, a publishing queue, upload progress, retries with backoff, approval gating with a four-eyes rule, token refresh and secure token storage.
- **Analytics**: hourly metric collection (views, likes, comments, shares, saves, reach, watch time) and performance reports by platform, channel and post.
- **Ops**: JSON structured logs with request IDs, a consistent error envelope, `/health` and `/ready` probes, crash recovery for interrupted jobs, Alembic migrations and 67 backend tests.

> **Platform compliance:** the app only uses the official, documented APIs and OAuth consent flows of Google and Meta. It contains no browser automation, scraping or credential sharing, and no other way around platform limits. See [docs/COMPLIANCE.md](docs/COMPLIANCE.md).

## Quick start (Docker)

```bash
cp .env.example .env                       # set SECRET_KEY, ENCRYPTION_KEYS, POSTGRES_PASSWORD
docker compose up -d --build
open http://localhost:3000                 # web app
open http://localhost:8000/api/v1/docs     # interactive API docs
```

The first account you register becomes the platform superuser. Without any LLM keys, the agents run on the offline **mock** provider, so you can try the full pipeline straight away. To use real models, add keys under **Settings → API**.

## Local development

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+asyncpg://faceless:faceless@localhost:5432/faceless
alembic upgrade head
uvicorn app.main:app --reload                       # API on :8000
arq app.workers.worker.WorkerSettings               # worker (separate shell)
pytest -q                                           # tests (SQLite by default)
TEST_DATABASE_URL=postgresql+asyncpg://... pytest   # tests against PostgreSQL

# frontend
cd frontend && npm install && npm run dev           # http://localhost:3000
```

FFmpeg must be on your `PATH` for rendering and for the video tests (the video tests are skipped if it is missing).

## Repository layout

```
backend/
  app/
    api/v1/        REST routes (auth, users, organizations, channels, projects, api-config,
                   agents, renders, social, publishing, approvals, analytics, dashboard, media)
    agents/        agent schemas, prompts, LangGraph graph, run executor
    llm/           provider adapters, structured output, model router, pricing
    video/         FFmpeg pipeline, subtitles, probe, render spec
    integrations/  YouTube & Instagram official API clients
    services/      business logic (auth, storage, renders, publishing, social, analytics)
    workers/       arq worker + cron jobs
    models/        SQLAlchemy models        schemas/  Pydantic API schemas
    core/          config, security, logging, errors, rate limiting
  alembic/         migrations
  tests/           pytest suite
frontend/          Next.js app
docs/              architecture, deployment, API, compliance
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md): components, data model and job flows
- [Deployment](docs/DEPLOYMENT.md): production setup, OAuth app configuration, scaling, backups
- [API guide](docs/API.md): authentication, tenancy headers, errors, main workflows
- [Compliance and security](docs/COMPLIANCE.md)
