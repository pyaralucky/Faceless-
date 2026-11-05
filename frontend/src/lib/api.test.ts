import { describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError, createApi, memoryTokenStorage, parseError } from "./api";

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function envelope(status: number, code: string, message: string, details: Record<string, unknown> = {}): Response {
  return json(status, { error: { code, message, details, request_id: "req-123" } });
}

function setup(handler: Handler, opts: { access?: string; refresh?: string; org?: string | null } = {}) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const i = init ?? {};
    calls.push({ url, init: i });
    return handler(url, i);
  });
  const storage = memoryTokenStorage({ access: opts.access ?? "access-1", refresh: opts.refresh ?? "refresh-1" });
  const onAuthFailure = vi.fn();
  const client = new ApiClient({
    baseUrl: "http://api.test/",
    fetch: fetchMock as unknown as typeof fetch,
    storage,
    getOrgId: () => (opts.org === undefined ? "org-1" : opts.org),
    onAuthFailure,
  });
  return { client, api: createApi(client), calls, fetchMock, storage, onAuthFailure };
}

function header(init: RequestInit, name: string): string | null {
  return new Headers(init.headers).get(name);
}

describe("ApiClient headers", () => {
  it("injects Authorization and X-Org-Id headers on org-scoped requests", async () => {
    const { api, calls } = setup(() => json(200, []));
    await api.channels.list();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("http://api.test/api/v1/channels");
    expect(header(calls[0].init, "Authorization")).toBe("Bearer access-1");
    expect(header(calls[0].init, "X-Org-Id")).toBe("org-1");
  });

  it("omits X-Org-Id for non-tenant endpoints and when no org is selected", async () => {
    const { api, calls } = setup(() => json(200, { id: "u", memberships: [] }));
    await api.auth.me();
    expect(header(calls[0].init, "X-Org-Id")).toBeNull();

    const s2 = setup(() => json(200, []), { org: null });
    await s2.api.channels.list();
    expect(header(s2.calls[0].init, "X-Org-Id")).toBeNull();
  });

  it("serializes query params and skips empty values", async () => {
    const { api, calls } = setup(() => json(200, { items: [], total: 0, limit: 25, offset: 0 }));
    await api.projects.list({ channel_id: "c1", status: "", q: "space cats", limit: 25 });
    expect(calls[0].url).toBe("http://api.test/api/v1/projects?channel_id=c1&q=space+cats&limit=25");
  });

  it("does not send auth headers to login and stores returned tokens", async () => {
    const { api, calls, storage } = setup(() => json(200, { access_token: "A2", refresh_token: "R2", expires_in: 900 }), {
      access: undefined,
    });
    await api.auth.login({ email: "a@b.co", password: "secret12345" });
    expect(header(calls[0].init, "Authorization")).toBeNull();
    expect(header(calls[0].init, "X-Org-Id")).toBeNull();
    expect(storage.getAccessToken()).toBe("A2");
    expect(storage.getRefreshToken()).toBe("R2");
  });
});

describe("error envelope parsing", () => {
  it("parses code, message, request_id and validation details", async () => {
    const res = envelope(422, "validation_failed", "Request validation failed", {
      errors: [
        { loc: ["body", "password"], msg: "Value error, Password must be at least 10 characters", type: "value_error" },
        { loc: ["body", "subtitle_style", "primary_color"], msg: "String should match pattern", type: "string_pattern_mismatch" },
      ],
    });
    const err = await parseError(res);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe("validation_failed");
    expect(err.message).toBe("Request validation failed");
    expect(err.requestId).toBe("req-123");
    expect(err.validationErrors).toHaveLength(2);
    expect(err.fieldErrors).toEqual({
      password: "Password must be at least 10 characters",
      "subtitle_style.primary_color": "String should match pattern",
    });
  });

  it("falls back gracefully for non-envelope bodies", async () => {
    const err = await parseError(new Response("Bad gateway", { status: 502, statusText: "Bad Gateway" }));
    expect(err.status).toBe(502);
    expect(err.code).toBe("http_502");
    expect(err.message).toBe("Bad gateway");

    const err2 = await parseError(json(404, { detail: "Not Found" }));
    expect(err2.message).toBe("Not Found");
  });

  it("throws ApiError from request() with envelope message", async () => {
    const { api } = setup(() => envelope(409, "conflict", "A credential with this provider and label already exists"));
    await expect(api.apiConfig.createCredential({ provider: "openai", api_key: "sk" })).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      code: "conflict",
      message: "A credential with this provider and label already exists",
    });
  });
});

describe("token refresh flow", () => {
  it("refreshes on 401 token_expired and retries the original request with the new token", async () => {
    const { api, calls, storage } = setup((url, init) => {
      if (url.endsWith("/auth/refresh")) {
        expect(JSON.parse(String(init.body))).toEqual({ refresh_token: "refresh-1" });
        return json(200, { access_token: "access-2", refresh_token: "refresh-2", expires_in: 900 });
      }
      const auth = header(init, "Authorization");
      if (auth === "Bearer access-1") return envelope(401, "token_expired", "Token expired");
      return json(200, [{ id: "ch1" }]);
    });

    const result = await api.channels.list();
    expect(result).toEqual([{ id: "ch1" }]);
    expect(calls.map((c) => c.url.replace("http://api.test/api/v1", ""))).toEqual(["/channels", "/auth/refresh", "/channels"]);
    expect(header(calls[2].init, "Authorization")).toBe("Bearer access-2");
    expect(header(calls[2].init, "X-Org-Id")).toBe("org-1");
    expect(storage.getAccessToken()).toBe("access-2");
    expect(storage.getRefreshToken()).toBe("refresh-2");
  });

  it("deduplicates concurrent refreshes into a single /auth/refresh call", async () => {
    let refreshCalls = 0;
    const { api, calls } = setup(async (url, init) => {
      if (url.endsWith("/auth/refresh")) {
        refreshCalls++;
        await new Promise((r) => setTimeout(r, 10));
        return json(200, { access_token: "access-2", refresh_token: "refresh-2", expires_in: 900 });
      }
      return header(init, "Authorization") === "Bearer access-2" ? json(200, { ok: url }) : envelope(401, "token_expired", "Token expired");
    });

    const results = await Promise.all([api.channels.list(), api.dashboard.get(), api.social.accounts()]);
    expect(results).toHaveLength(3);
    expect(refreshCalls).toBe(1);
    expect(calls.filter((c) => c.url.endsWith("/auth/refresh"))).toHaveLength(1);
  });

  it("clears tokens and calls onAuthFailure when refresh fails", async () => {
    const { api, storage, onAuthFailure } = setup((url) => {
      if (url.endsWith("/auth/refresh")) return envelope(401, "invalid_token", "Refresh token revoked");
      return envelope(401, "token_expired", "Token expired");
    });

    await expect(api.channels.list()).rejects.toMatchObject({ status: 401, code: "token_expired" });
    expect(onAuthFailure).toHaveBeenCalledTimes(1);
    expect(storage.getAccessToken()).toBeNull();
    expect(storage.getRefreshToken()).toBeNull();
  });

  it("only retries once if the retried request is still unauthorized", async () => {
    const { api, calls, onAuthFailure } = setup((url) => {
      if (url.endsWith("/auth/refresh")) return json(200, { access_token: "access-2", refresh_token: "refresh-2", expires_in: 900 });
      return envelope(401, "token_expired", "Token expired");
    });
    await expect(api.channels.list()).rejects.toBeInstanceOf(ApiError);
    expect(calls).toHaveLength(3);
    expect(onAuthFailure).not.toHaveBeenCalled();
  });

  it("does not attempt a refresh for unauthenticated endpoints such as login", async () => {
    const { api, calls } = setup(() => envelope(401, "invalid_credentials", "Invalid email or password"));
    await expect(api.auth.login({ email: "a@b.co", password: "nope" })).rejects.toMatchObject({ code: "invalid_credentials" });
    expect(calls).toHaveLength(1);
  });

  it("does not refresh on invalid_credentials (wrong current password)", async () => {
    const { api, calls, onAuthFailure } = setup(() => envelope(401, "invalid_credentials", "Current password is incorrect"));
    await expect(api.auth.changePassword({ current_password: "x", new_password: "newpassword1" })).rejects.toMatchObject({
      message: "Current password is incorrect",
    });
    expect(calls).toHaveLength(1);
    expect(onAuthFailure).not.toHaveBeenCalled();
  });
});

describe("multipart upload", () => {
  it("sends FormData with kind and file without a JSON content-type", async () => {
    const { api, calls } = setup(() => json(201, { id: "a1" }));
    await api.assets.upload("p1", "image", new Blob(["x"], { type: "image/png" }), "x.png");
    const init = calls[0].init;
    expect(calls[0].url).toBe("http://api.test/api/v1/projects/p1/assets");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("kind")).toBe("image");
    expect(header(init, "Content-Type")).toBeNull();
    expect(header(init, "X-Org-Id")).toBe("org-1");
  });
});

describe("Server-Sent Events", () => {
  it("parses frames split across chunks and sends auth + org headers", async () => {
    const chunks = ['data: {"status":"running","stage":"scenes","progress":1', '0,"error":null}\n\nda', 'ta: {"status":"succeeded","stage":"completed","progress":100,"error":null}\n\n'];
    const { api, calls } = setup(
      () =>
        new Response(
          new ReadableStream({
            start(ctrl) {
              for (const c of chunks) ctrl.enqueue(new TextEncoder().encode(c));
              ctrl.close();
            },
          }),
          { status: 200, headers: { "Content-Type": "text/event-stream" } },
        ),
    );
    const events = [];
    for await (const ev of api.renders.events("job-1")) events.push(ev);
    expect(events.map((e) => [e.stage, e.progress])).toEqual([
      ["scenes", 10],
      ["completed", 100],
    ]);
    expect(calls[0].url).toBe("http://api.test/api/v1/renders/job-1/events");
    expect(header(calls[0].init, "Authorization")).toBe("Bearer access-1");
    expect(header(calls[0].init, "X-Org-Id")).toBe("org-1");
  });

  it("throws ApiError when the stream request fails", async () => {
    const { api } = setup(() => envelope(404, "not_found", "Render job not found"));
    await expect(async () => {
      for await (const _ of api.renders.events("missing")) void _;
    }).rejects.toBeInstanceOf(ApiError);
  });
});
