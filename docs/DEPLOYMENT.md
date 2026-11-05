# Deployment Guide

## 1. Prerequisites

- A Linux host or cluster with Docker 24+ and docker compose v2 (or Kubernetes; see section 7).
- A domain with TLS, for example `app.example.com` for the web app and `api.example.com` for the API.
- PostgreSQL 16 and Redis 7. You can use the bundled containers or managed services such as RDS, Cloud SQL or ElastiCache.
- Persistent storage for media, mounted at `/data` in the `api` and `worker` containers. **Both containers must share it.**

## 2. Configure secrets

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"                                # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"    # ENCRYPTION_KEYS
```

| Variable | Notes |
|---|---|
| `ENVIRONMENT=production` | enables production safety checks: the app refuses to start without `SECRET_KEY` and `ENCRYPTION_KEYS` |
| `SECRET_KEY` | signs JWTs and OAuth state; changing it signs everyone out |
| `ENCRYPTION_KEYS` | Fernet keys for API keys and OAuth tokens. **Back them up**: without them, stored secrets can't be decrypted |
| `PUBLIC_API_URL` | public HTTPS base URL of the API, used for OAuth redirect URIs |
| `FRONTEND_URL`, `CORS_ORIGINS` | the web app's origin |
| `MEDIA_PUBLIC_BASE_URL` | public HTTPS base URL that Instagram fetches videos from (usually the same as `PUBLIC_API_URL`) |
| `DATABASE_URL`, `REDIS_URL` | set automatically by compose; set them yourself for managed services |

**Rotating the encryption key**: put the new key first (`ENCRYPTION_KEYS=new,old`) and redeploy. New writes use the new key, and old values still decrypt. Remove the old key only after every secret has been re-saved.

## 3. OAuth applications (official APIs)

### YouTube (Google Cloud)
1. Create a project and enable **YouTube Data API v3** and **YouTube Analytics API**.
2. Configure the OAuth consent screen with the scopes `youtube.upload`, `youtube.readonly` and `yt-analytics.readonly`. While the app is in *Testing*, only listed test users can connect. Complete Google's verification before going public.
3. Create an OAuth client ID of type *Web application* with the authorized redirect URI `https://api.example.com/api/v1/social/oauth/youtube/callback`.
4. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
5. Note: videos uploaded by **unverified** API projects are restricted to private until the project passes Google's API audit. Upload quota is limited by the project's daily units, and custom thumbnails need a verified channel.

### Instagram (Meta for Developers)
1. Create a *Business* app and add **Facebook Login for Business** and the **Instagram Graph API**.
2. Request the permissions `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement` and `business_management`. Advanced access requires Meta App Review.
3. Add the valid OAuth redirect URI `https://api.example.com/api/v1/social/oauth/instagram/callback`.
4. Set `META_APP_ID`, `META_APP_SECRET` and `META_GRAPH_VERSION`.
5. The Instagram account must be a **Professional (Business or Creator)** account linked to a Facebook Page. Reels must be vertical, and the video URL must be reachable over public HTTPS (see `MEDIA_PUBLIC_BASE_URL`).

## 4. Launch

```bash
docker compose up -d --build        # db, redis, migrate (one-shot), api, worker, web
docker compose ps
curl -f https://api.example.com/ready
```

Migrations run automatically through the `migrate` service before `api` and `worker` start. To run them by hand: `docker compose run --rm migrate`. To roll back one revision: `docker compose run --rm migrate alembic downgrade -1`.

## 5. Reverse proxy and TLS

Put nginx, Caddy, Traefik or a cloud load balancer in front of the app:

```nginx
server {
  server_name api.example.com;
  client_max_body_size 600m;              # asset uploads (MAX_UPLOAD_MB=512)
  location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Request-ID $request_id;
    proxy_buffering off;                  # SSE render progress
    proxy_read_timeout 3600s;
  }
}
server {
  server_name app.example.com;
  location / { proxy_pass http://127.0.0.1:3000; proxy_set_header Host $host; }
}
```

Build the web image with the public API URL baked in: `PUBLIC_API_URL=https://api.example.com docker compose build web`.

## 6. Scaling and operations

| Concern | Guidance |
|---|---|
| API | stateless; scale horizontally (`--workers` per container, more replicas) |
| Workers | rendering is CPU-heavy, so scale worker replicas by CPU. Each worker runs `max_jobs=4`; on small hosts, lower it or run dedicated render workers. All workers need the shared `/data` volume |
| Scheduler | the cron job (dispatch every 30s) runs in each worker, but claims are safe thanks to `SELECT … FOR UPDATE SKIP LOCKED` and arq `unique` cron jobs |
| Crash recovery | on startup, a worker re-queues renders and agent runs left `running` and returns interrupted uploads to `scheduled`. Renders resume from checkpoints |
| Logs | JSON on stdout (`LOG_JSON=true`) with `request_id`; ship them to Loki, ELK or CloudWatch. The API returns the request ID in `X-Request-ID` and in error bodies |
| Health | `/health` for liveness, `/ready` for readiness (checks DB and Redis); the worker healthcheck is `arq --check` |
| Backups | PostgreSQL: daily `pg_dump` or managed snapshots with PITR. Media: snapshot the `/data` volume, or sync it to object storage. Keep `ENCRYPTION_KEYS` in a secrets manager |
| Storage growth | intermediate render files live in `orgs/<org>/projects/<id>/renders/<job>/segments`. A periodic job can delete `segments/` and `*.part.*` files from succeeded renders older than N days |
| Redis | run with persistence (AOF) and `noeviction` so queued jobs are never evicted |

## 7. Kubernetes notes

- Deployments: `api` (HPA on CPU and RPS) and `worker` (HPA on CPU or queue depth). Run `alembic upgrade head` as a Job or Helm pre-upgrade hook.
- Media volume: use a `ReadWriteMany` PVC (EFS or Filestore), or swap `app/services/storage.py` for an S3-compatible backend. The interface is deliberately small.
- Secrets: `SECRET_KEY`, `ENCRYPTION_KEYS`, OAuth secrets and the database password come from a Secret, ideally backed by an external secrets manager.

## 8. Verifying a deployment

```bash
make test                                          # backend test suite in the Docker "test" target
curl -s https://api.example.com/api/v1/docs        # OpenAPI UI
```

Then, in the web app: register, create a channel and project, run agents (on the mock provider if no keys are set), render, connect a test YouTube account, schedule a private upload, approve it, and confirm it publishes.
