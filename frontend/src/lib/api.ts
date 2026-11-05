/**
 * Typed API client for the Faceless AI Studio backend.
 *
 * - Bearer access token on every authenticated request.
 * - `X-Org-Id` tenant header on every org-scoped request.
 * - On 401: a single (deduplicated) POST /auth/refresh, then one retry.
 *   If refresh fails, tokens are cleared and `onAuthFailure` fires.
 * - Errors are normalized from the backend envelope into `ApiError`.
 */
import type {
  AdminUserUpdate,
  AgentRun,
  AgentRunCreate,
  AgentRunDetail,
  ApiCatalog,
  Approval,
  ApprovalCreate,
  ApprovalDecision,
  ApprovalStatus,
  Asset,
  AssetKind,
  AuditLog,
  ChangePasswordRequest,
  Channel,
  ChannelCreate,
  ChannelUpdate,
  Credential,
  CredentialCreate,
  CredentialTestResult,
  CredentialUpdate,
  DashboardData,
  ErrorEnvelope,
  LoginRequest,
  Me,
  Member,
  Message,
  ModelRoute,
  ModelRouteUpsert,
  OAuthStart,
  Organization,
  OrganizationUpdate,
  Page,
  PerformanceReport,
  Platform,
  Project,
  ProjectCreate,
  ProjectStatus,
  ProjectSummary,
  ProjectUpdate,
  PublishJob,
  PublishJobCreate,
  PublishJobUpdate,
  PublishStatus,
  RegisterRequest,
  RenderCreate,
  RenderJob,
  Role,
  RunStatus,
  SocialAccount,
  TokenPair,
  UploadableAssetKind,
  User,
  UserUpdate,
  ValidationErrorItem,
} from "./types";

// ------------------------------------------------------------------ errors

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }

  /** Validation errors from `details.errors[]` (422 responses). */
  get validationErrors(): ValidationErrorItem[] {
    const errs = this.details?.errors;
    return Array.isArray(errs) ? (errs as ValidationErrorItem[]) : [];
  }

  /**
   * Map of field name -> message. The key is the dotted location without the
   * leading "body"/"query" segment, e.g. `password` or `subtitle_style.primary_color`.
   */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.validationErrors) {
      const loc = (e.loc ?? []).filter((p, i) => !(i === 0 && (p === "body" || p === "query" || p === "path" || p === "header")));
      const key = loc.join(".") || "_";
      if (!out[key]) out[key] = cleanMsg(e.msg);
    }
    return out;
  }
}

function cleanMsg(msg: string): string {
  return (msg || "").replace(/^Value error, /, "");
}

/** Parse a fetch Response into an ApiError, tolerating non-envelope bodies. */
export async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  const text = await res.text().catch(() => "");
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  const env = body as Partial<ErrorEnvelope> | null;
  if (env && typeof env === "object" && env.error && typeof env.error === "object") {
    const e = env.error;
    return new ApiError(res.status, e.code || `http_${res.status}`, e.message || res.statusText || "Request failed", e.details || {}, e.request_id ?? null);
  }
  // FastAPI default {"detail": ...} fallback
  const detail = (body as { detail?: unknown } | null)?.detail;
  const message = typeof detail === "string" ? detail : text && text.length < 300 ? text : res.statusText || `Request failed (${res.status})`;
  return new ApiError(res.status, `http_${res.status}`, message || "Request failed");
}

/** Human-readable message for any thrown value. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return String(err ?? "Unknown error");
}

// ------------------------------------------------------------------ storage

export interface TokenStorage {
  getAccessToken(): string | null;
  getRefreshToken(): string | null;
  setTokens(pair: Pick<TokenPair, "access_token" | "refresh_token">): void;
  clear(): void;
}

export const STORAGE_KEYS = {
  access: "fas.access_token",
  refresh: "fas.refresh_token",
  org: "fas.org_id",
} as const;

function ls(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export const localTokenStorage: TokenStorage = {
  getAccessToken: () => ls()?.getItem(STORAGE_KEYS.access) ?? null,
  getRefreshToken: () => ls()?.getItem(STORAGE_KEYS.refresh) ?? null,
  setTokens: (pair) => {
    ls()?.setItem(STORAGE_KEYS.access, pair.access_token);
    ls()?.setItem(STORAGE_KEYS.refresh, pair.refresh_token);
  },
  clear: () => {
    ls()?.removeItem(STORAGE_KEYS.access);
    ls()?.removeItem(STORAGE_KEYS.refresh);
  },
};

export function getStoredOrgId(): string | null {
  return ls()?.getItem(STORAGE_KEYS.org) ?? null;
}

export function setStoredOrgId(id: string | null): void {
  const s = ls();
  if (!s) return;
  if (id) s.setItem(STORAGE_KEYS.org, id);
  else s.removeItem(STORAGE_KEYS.org);
}

/** In-memory storage (tests / SSR). */
export function memoryTokenStorage(initial?: { access?: string | null; refresh?: string | null }): TokenStorage {
  let access = initial?.access ?? null;
  let refresh = initial?.refresh ?? null;
  return {
    getAccessToken: () => access,
    getRefreshToken: () => refresh,
    setTokens: (p) => {
      access = p.access_token;
      refresh = p.refresh_token;
    },
    clear: () => {
      access = null;
      refresh = null;
    },
  };
}

// ------------------------------------------------------------------ client

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  query?: Query;
  /** JSON body */
  body?: unknown;
  /** multipart body (takes precedence over `body`) */
  form?: FormData;
  /** send Authorization header and handle 401 refresh (default true) */
  auth?: boolean;
  /** send X-Org-Id header (default true) */
  org?: boolean;
  signal?: AbortSignal;
}

export interface ApiClientOptions {
  baseUrl: string;
  fetch?: typeof fetch;
  storage?: TokenStorage;
  getOrgId?: () => string | null;
  /** Called after a failed refresh (tokens already cleared). */
  onAuthFailure?: () => void;
}

/** Codes for which a 401 is a real credential failure, not an expired session. */
const NO_REFRESH_CODES = new Set(["invalid_credentials"]);

export class ApiClient {
  readonly baseUrl: string;
  readonly storage: TokenStorage;
  private readonly fetchImpl: typeof fetch;
  private readonly getOrgId: () => string | null;
  private readonly onAuthFailure?: () => void;
  private refreshing: Promise<boolean> | null = null;

  constructor(opts: ApiClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, "");
    this.fetchImpl = opts.fetch ?? ((...args: Parameters<typeof fetch>) => globalThis.fetch(...args));
    this.storage = opts.storage ?? localTokenStorage;
    this.getOrgId = opts.getOrgId ?? (() => null);
    this.onAuthFailure = opts.onAuthFailure;
  }

  url(path: string, query?: Query): string {
    const p = path.startsWith("/") ? path : `/${path}`;
    let u = `${this.baseUrl}/api/v1${p}`;
    if (query) {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(query)) {
        if (v === undefined || v === null || v === "") continue;
        qs.append(k, String(v));
      }
      const s = qs.toString();
      if (s) u += `?${s}`;
    }
    return u;
  }

  private buildHeaders(opts: RequestOptions): Headers {
    const h = new Headers();
    h.set("Accept", "application/json");
    if (opts.body !== undefined && !opts.form) h.set("Content-Type", "application/json");
    if (opts.auth !== false) {
      const token = this.storage.getAccessToken();
      if (token) h.set("Authorization", `Bearer ${token}`);
    }
    if (opts.org !== false) {
      const org = this.getOrgId();
      if (org) h.set("X-Org-Id", org);
    }
    return h;
  }

  /** Low-level request returning the raw Response (after auth/refresh handling). Throws ApiError on !ok. */
  async raw(method: string, path: string, opts: RequestOptions = {}): Promise<Response> {
    const send = () =>
      this.fetchImpl(this.url(path, opts.query), {
        method,
        headers: this.buildHeaders(opts),
        body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
        signal: opts.signal,
      });

    let res = await send();
    if (res.status === 401 && opts.auth !== false) {
      const err = await parseError(res.clone());
      if (!NO_REFRESH_CODES.has(err.code)) {
        const ok = await this.refresh();
        if (!ok) {
          this.storage.clear();
          this.onAuthFailure?.();
          throw err;
        }
        res = await send();
      }
    }
    if (!res.ok) throw await parseError(res);
    return res;
  }

  async request<T>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const res = await this.raw(method, path, opts);
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    return (text ? JSON.parse(text) : undefined) as T;
  }

  get<T>(path: string, query?: Query, opts: RequestOptions = {}) {
    return this.request<T>("GET", path, { ...opts, query });
  }
  post<T>(path: string, body?: unknown, opts: RequestOptions = {}) {
    return this.request<T>("POST", path, { ...opts, body });
  }
  put<T>(path: string, body?: unknown, opts: RequestOptions = {}) {
    return this.request<T>("PUT", path, { ...opts, body });
  }
  patch<T>(path: string, body?: unknown, opts: RequestOptions = {}) {
    return this.request<T>("PATCH", path, { ...opts, body });
  }
  delete<T>(path: string, opts: RequestOptions = {}) {
    return this.request<T>("DELETE", path, opts);
  }

  async blob(path: string, query?: Query): Promise<Blob> {
    const res = await this.raw("GET", path, { query });
    return res.blob();
  }

  /**
   * Refresh the access token. Concurrent callers share a single in-flight
   * request. Resolves true on success, false otherwise.
   */
  refresh(): Promise<boolean> {
    if (!this.refreshing) {
      this.refreshing = this.doRefresh().finally(() => {
        this.refreshing = null;
      });
    }
    return this.refreshing;
  }

  private async doRefresh(): Promise<boolean> {
    const refresh_token = this.storage.getRefreshToken();
    if (!refresh_token) return false;
    try {
      const res = await this.fetchImpl(this.url("/auth/refresh"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh_token }),
      });
      if (!res.ok) return false;
      const pair = (await res.json()) as TokenPair;
      if (!pair?.access_token) return false;
      this.storage.setTokens(pair);
      return true;
    } catch {
      return false;
    }
  }
}

// ------------------------------------------------------------------ endpoints

export interface ProjectFilters {
  channel_id?: string;
  status?: ProjectStatus | "";
  q?: string;
  limit?: number;
  offset?: number;
}

export interface PublishFilters {
  project_id?: string;
  status?: PublishStatus | "";
  platform?: Platform | "";
  limit?: number;
  offset?: number;
}

export function createApi(c: ApiClient) {
  return {
    client: c,

    auth: {
      async login(data: LoginRequest): Promise<TokenPair> {
        const pair = await c.post<TokenPair>("/auth/login", data, { auth: false, org: false });
        c.storage.setTokens(pair);
        return pair;
      },
      async register(data: RegisterRequest): Promise<TokenPair> {
        const pair = await c.post<TokenPair>("/auth/register", data, { auth: false, org: false });
        c.storage.setTokens(pair);
        return pair;
      },
      async logout(): Promise<void> {
        const refresh_token = c.storage.getRefreshToken();
        try {
          if (refresh_token) await c.post<Message>("/auth/logout", { refresh_token }, { auth: false, org: false });
        } finally {
          c.storage.clear();
        }
      },
      me: () => c.get<Me>("/auth/me", undefined, { org: false }),
      changePassword: (data: ChangePasswordRequest) => c.post<Message>("/auth/change-password", data, { org: false }),
    },

    users: {
      updateMe: (data: UserUpdate) => c.patch<User>("/users/me", data, { org: false }),
      list: (q: { q?: string; limit?: number; offset?: number } = {}) => c.get<Page<User>>("/users", q, { org: false }),
      update: (id: string, data: AdminUserUpdate) => c.patch<User>(`/users/${id}`, data, { org: false }),
    },

    orgs: {
      mine: () => c.get<Organization[]>("/organizations", undefined, { org: false }),
      create: (name: string) => c.post<Organization>("/organizations", { name }, { org: false }),
      current: () => c.get<Organization>("/organizations/current"),
      update: (data: OrganizationUpdate) => c.patch<Organization>("/organizations/current", data),
      members: () => c.get<Member[]>("/organizations/current/members"),
      addMember: (email: string, role: Role) => c.post<Member>("/organizations/current/members", { email, role }),
      updateMember: (userId: string, role: Role) => c.patch<Member>(`/organizations/current/members/${userId}`, { role }),
      removeMember: (userId: string) => c.delete<Message>(`/organizations/current/members/${userId}`),
      auditLogs: (q: { limit?: number; offset?: number } = {}) => c.get<Page<AuditLog>>("/organizations/current/audit-logs", q),
    },

    channels: {
      list: (includeInactive = false) => c.get<Channel[]>("/channels", { include_inactive: includeInactive || undefined }),
      get: (id: string) => c.get<Channel>(`/channels/${id}`),
      create: (data: ChannelCreate) => c.post<Channel>("/channels", data),
      update: (id: string, data: ChannelUpdate) => c.patch<Channel>(`/channels/${id}`, data),
      remove: (id: string) => c.delete<Message>(`/channels/${id}`),
    },

    projects: {
      list: (f: ProjectFilters = {}) => c.get<Page<ProjectSummary>>("/projects", { ...f }),
      get: (id: string) => c.get<Project>(`/projects/${id}`),
      create: (data: ProjectCreate) => c.post<Project>("/projects", data),
      update: (id: string, data: ProjectUpdate) => c.patch<Project>(`/projects/${id}`, data),
      remove: (id: string) => c.delete<Message>(`/projects/${id}`),
    },

    assets: {
      list: (projectId: string, kind?: AssetKind) => c.get<Asset[]>(`/projects/${projectId}/assets`, { kind }),
      upload: (projectId: string, kind: UploadableAssetKind, file: File | Blob, filename?: string) => {
        const form = new FormData();
        form.append("kind", kind);
        if (filename) form.append("file", file, filename);
        else form.append("file", file);
        return c.request<Asset>("POST", `/projects/${projectId}/assets`, { form });
      },
      file: (projectId: string, assetId: string) => c.blob(`/projects/${projectId}/assets/${assetId}/file`),
      remove: (projectId: string, assetId: string) => c.delete<Message>(`/projects/${projectId}/assets/${assetId}`),
    },

    apiConfig: {
      catalog: () => c.get<ApiCatalog>("/api-config/catalog"),
      credentials: () => c.get<Credential[]>("/api-config/credentials"),
      createCredential: (data: CredentialCreate) => c.post<Credential>("/api-config/credentials", data),
      updateCredential: (id: string, data: CredentialUpdate) => c.patch<Credential>(`/api-config/credentials/${id}`, data),
      deleteCredential: (id: string) => c.delete<Message>(`/api-config/credentials/${id}`),
      testCredential: (id: string, model?: string) =>
        c.request<CredentialTestResult>("POST", `/api-config/credentials/${id}/test`, { query: { model } }),
      routes: () => c.get<ModelRoute[]>("/api-config/routes"),
      upsertRoute: (agent: string, data: ModelRouteUpsert) => c.put<ModelRoute>(`/api-config/routes/${encodeURIComponent(agent)}`, data),
      deleteRoute: (agent: string) => c.delete<Message>(`/api-config/routes/${encodeURIComponent(agent)}`),
    },

    agentRuns: {
      start: (projectId: string, data: AgentRunCreate) => c.post<AgentRun>(`/projects/${projectId}/agent-runs`, data),
      list: (q: { project_id?: string; limit?: number; offset?: number } = {}) => c.get<Page<AgentRun>>("/agent-runs", q),
      get: (id: string) => c.get<AgentRunDetail>(`/agent-runs/${id}`),
      cancel: (id: string) => c.post<AgentRun>(`/agent-runs/${id}/cancel`),
    },

    renders: {
      create: (projectId: string, data: RenderCreate) => c.post<RenderJob>(`/projects/${projectId}/renders`, data),
      list: (q: { project_id?: string; status?: RunStatus; limit?: number; offset?: number } = {}) => c.get<Page<RenderJob>>("/renders", q),
      get: (id: string) => c.get<RenderJob>(`/renders/${id}`),
      resume: (id: string) => c.post<RenderJob>(`/renders/${id}/resume`),
      cancel: (id: string) => c.post<RenderJob>(`/renders/${id}/cancel`),
    },

    social: {
      accounts: () => c.get<SocialAccount[]>("/social/accounts"),
      authorize: (platform: Platform, channelId?: string) => c.get<OAuthStart>(`/social/${platform}/authorize`, { channel_id: channelId }),
      assign: (id: string, channelId: string | null) => c.patch<SocialAccount>(`/social/accounts/${id}`, { channel_id: channelId }),
      refresh: (id: string) => c.post<SocialAccount>(`/social/accounts/${id}/refresh`),
      disconnect: (id: string) => c.delete<Message>(`/social/accounts/${id}`),
    },

    publishing: {
      create: (data: PublishJobCreate) => c.post<PublishJob>("/publishing/jobs", data),
      list: (f: PublishFilters = {}) => c.get<Page<PublishJob>>("/publishing/jobs", { ...f }),
      get: (id: string) => c.get<PublishJob>(`/publishing/jobs/${id}`),
      update: (id: string, data: PublishJobUpdate) => c.patch<PublishJob>(`/publishing/jobs/${id}`, data),
      cancel: (id: string) => c.post<PublishJob>(`/publishing/jobs/${id}/cancel`),
      retry: (id: string) => c.post<PublishJob>(`/publishing/jobs/${id}/retry`),
      publishNow: (id: string) => c.post<PublishJob>(`/publishing/jobs/${id}/publish-now`),
    },

    approvals: {
      list: (q: { status?: ApprovalStatus; project_id?: string; limit?: number; offset?: number } = {}) => c.get<Page<Approval>>("/approvals", q),
      request: (data: ApprovalCreate) => c.post<Approval>("/approvals", data),
      decide: (id: string, data: ApprovalDecision) => c.post<Approval>(`/approvals/${id}/decision`, data),
    },

    analytics: {
      report: (q: { days?: number; channel_id?: string } = {}) => c.get<PerformanceReport>("/analytics/report", q),
      collect: () => c.post<Message>("/analytics/collect"),
    },

    dashboard: {
      get: () => c.get<DashboardData>("/dashboard"),
    },
  };
}

export type Api = ReturnType<typeof createApi>;

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  const { pathname, search } = window.location;
  if (pathname.startsWith("/login") || pathname.startsWith("/register")) return;
  const next = encodeURIComponent(pathname + search);
  window.location.assign(`/login?next=${next}`);
}

export const api: Api = createApi(
  new ApiClient({
    baseUrl: API_BASE_URL,
    storage: localTokenStorage,
    getOrgId: getStoredOrgId,
    onAuthFailure: redirectToLogin,
  }),
);
