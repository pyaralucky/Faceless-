# Architecture

```
            ┌──────────────┐        ┌──────────────────────────┐
 Browser ──▶│ Next.js web  │──REST─▶│ FastAPI (uvicorn, N pods) │──┐
            └──────────────┘        └────────────┬─────────────┘  │
                                                 │ enqueue         │ SQL
 Google / Meta OAuth redirects ─────────────────▶│                 ▼
                                    ┌────────────▼───┐      ┌─────────────┐
                                    │ Redis (queue,  │      │ PostgreSQL  │
                                    │ rate limits,   │      │ (tenants,   │
                                    │ progress pub)  │      │ jobs, logs) │
                                    └────────┬───────┘      └──────▲──────┘
                                             │ jobs                │
                                    ┌────────▼──────────────────────┴──┐
                                    │ arq worker(s)                     │
                                    │  run_agents  → LangGraph + router │──▶ LLM providers
                                    │  render_video → FFmpeg pipeline   │──▶ shared media volume
                                    │  publish_video → YouTube / IG API │──▶ platform APIs
                                    │  cron: dispatch due posts (30s),  │
                                    │        collect analytics (hourly) │
                                    └───────────────────────────────────┘
```

## Multi-tenancy

- An **Organization** is the tenant. Users join organizations through a **Membership** that has a role.
- Every tenant-owned table has an indexed `organization_id`, and all lookups by id go through `services/scoping.get_scoped(model, id, org_id)`. That makes cross-tenant reads impossible by construction: they return 404, so nothing reveals that the record exists.
- The active tenant comes from the `X-Org-Id` header. `api/deps.get_org_context` checks the caller's membership, and `require_role()` enforces the minimum role per endpoint.
- Platform superusers (`users.is_superuser`) can administer users and can view any organization.

### Role matrix

| Action | viewer | reviewer | editor | admin | owner |
|---|:-:|:-:|:-:|:-:|:-:|
| Read channels, projects, renders, analytics | ✓ | ✓ | ✓ | ✓ | ✓ |
| Approve or reject publishing | | ✓ | ✓ | ✓ | ✓ |
| Create or edit projects, run agents, render, schedule posts, connect accounts | | | ✓ | ✓ | ✓ |
| Delete channels, API keys and model routes, manage team, disconnect accounts, audit log | | | | ✓ | ✓ |
| Grant the owner role | | | | | ✓ |

## Data model (17 tables)

| Table | Purpose |
|---|---|
| `users`, `refresh_tokens` | identity; refresh tokens are stored hashed and rotated in token families |
| `organizations`, `memberships` | tenants and role assignments (unique per org and user) |
| `audit_logs` | who did what, when and from which IP |
| `channels` | brand kit, language, tone, default format, `require_approval` |
| `projects` | topic and brief, plus the latest output of each agent (JSONB), and the status lifecycle |
| `assets` | uploaded media and generated renders and thumbnails (path, checksum, probe data) |
| `provider_credentials` | encrypted LLM API keys per org (`config.pricing` sets cost estimation) |
| `model_routes` | per-agent provider, model, temperature, max tokens and fallbacks (`*` is the org default) |
| `agent_runs`, `agent_steps` | run status, token and cost totals; one step row per LLM attempt (the execution log) |
| `render_jobs` | resolved render spec, progress and stage, checkpoint manifest, QC report, outputs |
| `social_accounts` | connected YouTube channels and IG professional accounts, with encrypted tokens |
| `publish_jobs` | the queue: schedule, attempts and backoff, resumable upload state, history |
| `approval_requests` | review workflow linked to a project and optionally a publish job |
| `analytics_snapshots` | time series of platform metrics per published post |

All tables use UUID primary keys and timezone-aware timestamps, and indexes are named consistently. Enums are stored as `VARCHAR`, so adding a value never needs a type migration.

## AI agents

```
research → strategy → script → fact_check ──(verdict=revise and revisions < AGENT_MAX_REVISIONS)──▶ script
                                    └──(pass)──▶ storyboard → optimization → END
```

- Each agent is an `AgentSpec` (`app/agents/definitions.py`) made of a system prompt, a Pydantic output model, a prompt builder and an offline mock generator.
- `build_graph()` compiles a LangGraph `StateGraph` that contains only the requested agents. If an agent's prerequisites are not being run, they must already exist on the project.
- **Model router** (`app/llm/router.py`):
  1. Resolves the agent route (or the `*` default, or the env default), followed by its fallbacks.
  2. Calls the provider adapter with a JSON-mode request, with the schema embedded in the system prompt.
  3. Parses and validates the response. If the JSON is invalid, it sends the validation error back to the model and asks for a correction.
  4. Retries retryable errors (429, 5xx, timeouts) with exponential backoff and jitter. Non-retryable errors (such as a bad key) move straight to the next fallback model.
  5. Reports every attempt through a callback, which the runner persists as an `agent_steps` row with tokens, cost, latency and any error.
- Outputs are saved to the project after each agent, so a failure keeps the work done so far.

## Rendering pipeline

`app/video/pipeline.py` runs these stages. Each one writes an output file and a fingerprint (a hash of its inputs) to `manifest.json`.

| Stage | What happens |
|---|---|
| plan | probes narration, scales scene durations to fit it, and computes the timeline accounting for transition overlap |
| scenes | renders one H.264 segment per scene: image with zoom or pan, a video clip (looped and cropped), or a color card, plus an optional headline |
| assemble | chains `xfade` transitions (or `concat` for hard cuts) after normalizing timebase and fps |
| audio | mixes narration and music; music is ducked with `sidechaincompress`, then `loudnorm` to the target LUFS and a fade-out (silence if no audio is supplied) |
| subtitles | builds cues from the SRT or from scene narration, then writes styled ASS with resolution-aware sizes and positions |
| compose | burns captions with libass (or muxes `mov_text`), muxes the AAC audio and sets `+faststart` |
| thumbnail | picks a representative frame from the caption-free video and adds title text: 1280×720 for horizontal, 1080×1920 for vertical |
| qc | checks container, resolution, codec, pixel format, audio, duration, file size, loudness, black frames, and the Shorts/Reels length limit |

**Resumability**: a stage or scene is skipped when its fingerprint matches and its output exists. Intermediate files are written as `*.part.*` and renamed atomically. If a render fails, is cancelled, or the worker crashes, the render can be resumed: `POST /renders/{id}/resume` does this manually, and worker startup re-queues `running` jobs automatically. Only the missing or changed work is redone.

**Progress**: FFmpeg's `-progress` output is parsed into a weighted overall percentage. It is written to `render_jobs.progress` (throttled), published on the Redis channel `render:{id}`, and streamed over SSE at `GET /renders/{id}/events`.

## Publishing flow

```
create job ─▶ channel.require_approval? ─yes─▶ pending_approval ─approve─▶ scheduled
                         └──no──────────────────────────────────────────▶ scheduled
scheduled ─(cron every 30s claims due jobs with FOR UPDATE SKIP LOCKED)─▶ uploading ─▶ processing ─▶ published
            ▲                                                                │
            └──── retryable error: attempts < max → next_attempt_at = base·2^n ┘
                  non-retryable, auth error, or attempts exhausted → failed (auth errors also mark the account expired)
```

- The YouTube upload session URI and the Instagram container ID are stored in `publish_jobs.state`, so a retry resumes the upload instead of starting it again.
- Access tokens are refreshed shortly before they expire: Google tokens 5 minutes ahead, Meta long-lived tokens 7 days ahead.
- Instagram downloads the video from a **signed, expiring URL**: `/api/v1/media/{jwt}` serves only render and thumbnail assets.
