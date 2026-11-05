# Compliance and Security

## Platform policy compliance

Faceless AI Studio talks to social platforms **only** through their official, documented APIs, using the account owner's explicit OAuth consent.

| Platform | Mechanism | What we never do |
|---|---|---|
| YouTube | Google OAuth 2.0 (authorization code, offline access), YouTube Data API v3 resumable uploads, YouTube Analytics API | browser automation, headless logins, cookie or session reuse, scraping, quota evasion, rotating projects to get around limits |
| Instagram | Facebook Login for Business, Instagram Graph API Content Publishing (`/media` → `/media_publish`) and Insights | automating the Instagram app or website, private or unofficial APIs, posting to personal (non-professional) accounts |

- Platform quotas, rate limits and processing errors are respected. Failed uploads are retried with exponential backoff up to `PUBLISH_MAX_ATTEMPTS`, never in a tight loop. Auth failures stop retries and ask the user to reconnect.
- Uploads to YouTube declare `containsSyntheticMedia: true`, because the content is AI-generated. Review each platform's policy on altered or synthetic content and label your content accordingly.
- Approval workflows give a human review before publication (the four-eyes rule: requesters can't approve their own content unless `ALLOW_SELF_APPROVAL=true`).
- The fact-checking agent flags unsupported claims, and the optimization agent is told not to write misleading clickbait. Human review is still required. Operators are responsible for the content they publish.

## Security controls

| Area | Control |
|---|---|
| Passwords | bcrypt (cost 12) over a SHA-256 pre-hash; minimum length and complexity checks; equal timing for unknown emails |
| Sessions | 15-minute HS256 JWT access tokens; opaque refresh tokens stored as SHA-256 hashes, rotated on use, with family revocation on reuse |
| Brute force | Redis fixed-window rate limits per IP and per email on login and registration |
| Secrets at rest | LLM API keys and OAuth access and refresh tokens are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) through `MultiFernet` key rotation. API responses only return a masked hint |
| OAuth CSRF | the `state` parameter is a signed, 15-minute JWT tied to the organization, user and platform |
| Tenant isolation | every query is scoped by `organization_id`; other tenants' resources return 404 |
| Authorization | role-based (viewer → owner) and enforced server-side on every route; nobody can grant a role above their own; the last owner can't be removed |
| Uploads | MIME allow-list per asset kind, size limit, sanitized filenames, storage path traversal protection |
| Public media | only render and thumbnail assets, through signed URLs that expire after 6 hours (needed by Instagram's API) |
| Auditing | `audit_logs` records security-relevant actions with the actor and IP |
| Transport | deploy behind TLS; the API sets `X-Content-Type-Options` and `Referrer-Policy`; CORS is restricted to `CORS_ORIGINS` |
| Logging | structured JSON logs with request IDs; secrets and tokens are never logged |

## Data handling

- Disconnecting an account revokes the Google token where possible, wipes the stored tokens and cancels its pending posts. The account row stays (marked `revoked`) so publish history and analytics are kept.
- Deleting a project removes its database rows (cascade) and its media directory.
- All tenant tables use `ON DELETE CASCADE` from `organizations`, so deleting an organization removes all of its data in one operation. Self-service organization deletion is not exposed in the API yet; a platform admin performs it on request.
