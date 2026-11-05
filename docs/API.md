# API Guide

Interactive OpenAPI documentation: `GET /api/v1/docs` (the schema is at `/api/v1/openapi.json`).

## Conventions

- **Auth**: send `Authorization: Bearer <access_token>`. Access tokens last 15 minutes. Refresh them with `POST /auth/refresh {refresh_token}`. Refresh tokens rotate on every use, and reusing an old one revokes the whole session family.
- **Tenant**: every organization-scoped route needs `X-Org-Id: <organization uuid>`. You can find these IDs in the `memberships` field of `GET /auth/me`.
- **Pagination**: list endpoints accept `limit` and `offset` and return `{items, total, limit, offset}`.
- **Errors** always use this shape:

```json
{"error": {"code": "validation_failed", "message": "Request validation failed",
           "details": {"errors": [{"loc": ["body", "password"], "msg": "...", "type": "value_error"}]},
           "request_id": "8f2c1a..."}}
```

  | HTTP | code examples |
  |---|---|
  | 401 | `unauthenticated`, `invalid_token`, `token_expired`, `token_reused`, `invalid_credentials` |
  | 403 | `forbidden` (role too low) |
  | 404 | `not_found` (also returned for other tenants' resources) |
  | 409 | `conflict`, `email_taken` |
  | 422 | `validation_failed` |
  | 429 | `rate_limited` |

- **Async work** (agent runs, renders, publish-now) returns `202 Accepted` with a job resource. Poll it, or for renders use the SSE stream.

## End-to-end workflow

```http
POST /api/v1/auth/register            {"email","password","full_name","organization_name"}
GET  /api/v1/auth/me                  → memberships[0].organization_id  → X-Org-Id

POST /api/v1/channels                 {"name":"History Shorts","niche":"history","tone":"dramatic","require_approval":true}
POST /api/v1/projects                 {"channel_id":"…","title":"The Lost City","target_duration_sec":45}

# Optional: configure models (admin)
POST /api/v1/api-config/credentials   {"provider":"anthropic","api_key":"sk-ant-…","config":{"pricing":{"claude-sonnet-5-5":{"input":3,"output":15}}}}
PUT  /api/v1/api-config/routes/*      {"provider":"anthropic","model":"claude-sonnet-5-5","fallbacks":[{"provider":"openai","model":"gpt-4.1-mini"}]}
PUT  /api/v1/api-config/routes/fact_check {"provider":"openai","model":"gpt-4.1","temperature":0.1}

# AI pipeline
POST /api/v1/projects/{id}/agent-runs {"agents":[], "instructions":"Target teens, avoid jargon"}
GET  /api/v1/agent-runs/{run_id}      → status, token totals, steps[] (execution log)

# Media + render
POST /api/v1/projects/{id}/assets     multipart: kind=image|video|narration|music|subtitle, file=@…
POST /api/v1/projects/{id}/renders    {"format":"vertical","narration_asset_id":"…","music_asset_id":"…",
                                       "subtitle_style":{"position":"bottom","highlight_color":"#FFD400"}}
GET  /api/v1/renders/{job_id}         → progress, stage, qc_report, output_asset_id
GET  /api/v1/renders/{job_id}/events  → text/event-stream progress
POST /api/v1/renders/{job_id}/resume  → continue a failed or cancelled render from checkpoints

# Accounts + publishing
GET  /api/v1/social/youtube/authorize?channel_id=… → {authorization_url}  (redirect the browser there)
POST /api/v1/publishing/jobs          {"project_id","social_account_id","privacy":"private","scheduled_at":"2026-11-06T15:00:00Z"}
GET  /api/v1/approvals?status=pending
POST /api/v1/approvals/{id}/decision  {"decision":"approve","note":"Looks good"}   (reviewer+, not the requester)
GET  /api/v1/publishing/jobs/{id}     → status, attempts, next_attempt_at, upload_progress, external_url, history

# Analytics
GET  /api/v1/analytics/report?days=30&channel_id=…
GET  /api/v1/dashboard
```

## Explicit render scenes

If you leave out `scenes`, the render is built from the project storyboard and uses the project's uploaded images and videos in order. To control each scene yourself:

```json
{
  "format": "horizontal",
  "scenes": [
    {"asset_id": "<image>", "duration": 4, "text": "Narration for captions", "motion": "zoom_in", "transition": "fade"},
    {"asset_id": "<video>", "duration": 3.5, "overlay_text": "Fact #1", "transition": "wipeleft", "transition_duration": 0.6},
    {"duration": 3, "text": "Follow for more", "background_color": "#14213D", "transition": "fadeblack"}
  ],
  "narration_asset_id": "<audio>",
  "burn_subtitles": true,
  "target_lufs": -14
}
```

- Transitions: `none fade fadeblack wipeleft wiperight slideup slideleft circleopen dissolve smoothleft`.
- Motions: `none zoom_in zoom_out pan_left pan_right`.
- When narration is provided, scene durations are scaled to fit it (`fit_to_narration`).
