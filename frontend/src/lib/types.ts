/**
 * Types mirroring the backend Pydantic schemas (backend/app/schemas/*.py).
 * UUIDs and datetimes are serialized as strings.
 */

export type UUID = string;
export type ISODate = string;
export type JSONObject = Record<string, unknown>;

// ------------------------------------------------------------------ enums

export const ROLES = ["viewer", "reviewer", "editor", "admin", "owner"] as const;
export type Role = (typeof ROLES)[number];

export const VIDEO_FORMATS = ["vertical", "horizontal"] as const;
export type VideoFormat = (typeof VIDEO_FORMATS)[number];

export const PROJECT_STATUSES = [
  "draft",
  "generating",
  "scripted",
  "rendering",
  "rendered",
  "pending_approval",
  "approved",
  "scheduled",
  "published",
  "failed",
  "archived",
] as const;
export type ProjectStatus = (typeof PROJECT_STATUSES)[number];

export const RUN_STATUSES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const ASSET_KINDS = ["image", "video", "narration", "music", "subtitle", "render", "thumbnail"] as const;
export type AssetKind = (typeof ASSET_KINDS)[number];
export const UPLOADABLE_ASSET_KINDS = ["image", "video", "narration", "music", "subtitle"] as const;
export type UploadableAssetKind = (typeof UPLOADABLE_ASSET_KINDS)[number];

export const PLATFORMS = ["youtube", "instagram"] as const;
export type Platform = (typeof PLATFORMS)[number];

export type SocialAccountStatus = "active" | "expired" | "revoked" | "error";

export const PUBLISH_STATUSES = [
  "draft",
  "pending_approval",
  "approved",
  "scheduled",
  "uploading",
  "processing",
  "published",
  "failed",
  "cancelled",
  "rejected",
] as const;
export type PublishStatus = (typeof PUBLISH_STATUSES)[number];

export type ApprovalStatus = "pending" | "approved" | "rejected" | "cancelled";

export const LLM_PROVIDERS = ["openai", "anthropic", "google", "openrouter", "azure_openai", "ollama", "mock"] as const;
export type LLMProvider = (typeof LLM_PROVIDERS)[number];

export const AGENT_NAMES = ["research", "strategy", "script", "fact_check", "storyboard", "optimization"] as const;
export type AgentName = (typeof AGENT_NAMES)[number];

export const TRANSITIONS = [
  "none",
  "fade",
  "fadeblack",
  "wipeleft",
  "wiperight",
  "slideup",
  "slideleft",
  "circleopen",
  "dissolve",
  "smoothleft",
] as const;
export type Transition = (typeof TRANSITIONS)[number];

export const MOTIONS = ["none", "zoom_in", "zoom_out", "pan_left", "pan_right"] as const;
export type Motion = (typeof MOTIONS)[number];

export type Privacy = "private" | "unlisted" | "public";

// ------------------------------------------------------------------ common

export interface Entity {
  id: UUID;
  created_at: ISODate;
  updated_at: ISODate;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Message {
  message: string;
}

export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: { errors?: ValidationErrorItem[] } & JSONObject;
    request_id: string | null;
  };
}

// ------------------------------------------------------------------ identity

export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string;
  organization_name?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type?: string;
  expires_in: number;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface Membership {
  organization_id: UUID;
  organization_name: string;
  organization_slug: string;
  role: Role;
}

export interface User extends Entity {
  email: string;
  full_name: string;
  is_active: boolean;
  is_superuser: boolean;
  email_verified: boolean;
  last_login_at: ISODate | null;
}

export interface Me extends User {
  memberships: Membership[];
}

export interface UserUpdate {
  full_name?: string | null;
}

export interface AdminUserUpdate extends UserUpdate {
  is_active?: boolean | null;
  is_superuser?: boolean | null;
}

export interface Organization extends Entity {
  name: string;
  slug: string;
  plan: string;
  monthly_token_budget: number | null;
  settings: JSONObject;
}

export interface OrganizationUpdate {
  name?: string;
  monthly_token_budget?: number | null;
  settings?: JSONObject;
}

export interface Member {
  user_id: UUID;
  email: string;
  full_name: string;
  role: Role;
  joined_at: ISODate;
}

export interface AuditLog extends Entity {
  actor_id: UUID | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  data: JSONObject;
}

// ------------------------------------------------------------------ content

export interface SubtitleStyle {
  font_name?: string | null;
  font_size?: number;
  primary_color?: string;
  outline_color?: string;
  highlight_color?: string;
  outline?: number;
  shadow?: number;
  bold?: boolean;
  position?: "bottom" | "center" | "top";
  margin_v?: number;
  max_words_per_line?: number;
  uppercase?: boolean;
}

export interface ChannelBase {
  name: string;
  niche: string;
  description: string;
  language: string;
  tone: string;
  target_audience: string;
  default_format: VideoFormat;
  require_approval: boolean;
  branding: JSONObject & { subtitle_style?: SubtitleStyle };
}

export type ChannelCreate = ChannelBase;
export type ChannelUpdate = Partial<ChannelBase> & { is_active?: boolean };

export interface Channel extends ChannelBase, Entity {
  organization_id: UUID;
  is_active: boolean;
  project_count: number;
}

export interface ProjectCreate {
  channel_id: UUID;
  title: string;
  topic?: string;
  format?: VideoFormat | null;
  target_duration_sec?: number;
  brief?: JSONObject;
}

export interface ProjectUpdate {
  title?: string;
  topic?: string;
  format?: VideoFormat;
  target_duration_sec?: number;
  brief?: JSONObject;
  status?: ProjectStatus;
  script?: JSONObject;
  storyboard?: JSONObject;
  optimization?: JSONObject;
}

export interface ProjectSummary extends Entity {
  organization_id: UUID;
  channel_id: UUID;
  title: string;
  topic: string;
  status: ProjectStatus;
  format: VideoFormat;
  target_duration_sec: number;
}

export interface Project extends ProjectSummary {
  brief: JSONObject;
  research: JSONObject;
  strategy: JSONObject;
  script: JSONObject;
  fact_check: JSONObject;
  storyboard: JSONObject;
  optimization: JSONObject;
}

export interface Asset extends Entity {
  project_id: UUID | null;
  kind: AssetKind;
  filename: string;
  mime_type: string;
  size_bytes: number;
  duration_sec: number | null;
  width: number | null;
  height: number | null;
  meta: JSONObject;
}

// ------------------------------------------------------------------ API configuration

export interface CredentialCreate {
  provider: LLMProvider;
  label?: string;
  api_key: string;
  base_url?: string | null;
  config?: JSONObject;
}

export interface CredentialUpdate {
  api_key?: string;
  base_url?: string | null;
  is_active?: boolean;
  config?: JSONObject;
}

export interface Credential extends Entity {
  provider: LLMProvider;
  label: string;
  key_hint: string;
  base_url: string | null;
  is_active: boolean;
  config: JSONObject;
}

export interface CredentialTestResult {
  ok: boolean;
  error?: string;
  model?: string;
  reply?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

export interface ModelTarget {
  provider: LLMProvider;
  model: string;
}

export interface ModelRouteUpsert {
  provider: LLMProvider;
  model: string;
  temperature: number;
  max_tokens: number;
  fallbacks: ModelTarget[];
}

export interface ModelRoute extends Entity {
  agent_name: string;
  provider: LLMProvider;
  model: string;
  temperature: number;
  max_tokens: number;
  fallbacks: ModelTarget[];
}

export interface ApiCatalog {
  providers: LLMProvider[];
  agents: AgentName[];
  suggested_models: Record<string, string[]>;
}

// ------------------------------------------------------------------ runs

export interface AgentRunCreate {
  agents?: AgentName[];
  instructions?: string;
}

export interface AgentStep extends Entity {
  agent_name: string;
  attempt: number;
  status: string;
  provider: string | null;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_ms: number;
  error: string | null;
  output: JSONObject;
}

export interface AgentRun extends Entity {
  project_id: UUID;
  status: RunStatus;
  agents: string[];
  input: JSONObject;
  error: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  started_at: ISODate | null;
  finished_at: ISODate | null;
}

export interface AgentRunDetail extends AgentRun {
  output: JSONObject;
  steps: AgentStep[];
}

export interface RenderSceneIn {
  asset_id?: UUID | null;
  duration: number;
  text?: string;
  overlay_text?: string;
  transition?: Transition;
  transition_duration?: number;
  motion?: Motion;
  background_color?: string;
}

export interface RenderCreate {
  format?: VideoFormat | null;
  scenes?: RenderSceneIn[] | null;
  narration_asset_id?: UUID | null;
  music_asset_id?: UUID | null;
  subtitle_asset_id?: UUID | null;
  burn_subtitles?: boolean;
  subtitle_style?: SubtitleStyle;
  music_volume?: number;
  duck_music?: boolean;
  target_lufs?: number;
  thumbnail_text?: string | null;
}

export interface QCCheck {
  name: string;
  passed: boolean;
  value: unknown;
  expected: unknown;
  severity: "error" | "warning" | string;
}

export interface QCReport {
  passed?: boolean;
  checks?: QCCheck[];
  warnings?: string[];
}

export interface RenderJob extends Entity {
  project_id: UUID;
  status: RunStatus;
  format: VideoFormat;
  /** 0..100 */
  progress: number;
  stage: string;
  qc_report: QCReport & JSONObject;
  output_asset_id: UUID | null;
  thumbnail_asset_id: UUID | null;
  attempts: number;
  error: string | null;
  started_at: ISODate | null;
  finished_at: ISODate | null;
}

// ------------------------------------------------------------------ social & publishing

export interface SocialAccount extends Entity {
  channel_id: UUID | null;
  platform: Platform;
  external_id: string;
  display_name: string;
  avatar_url: string | null;
  token_expires_at: ISODate | null;
  scopes: string[];
  status: SocialAccountStatus;
  meta: JSONObject;
}

export interface OAuthStart {
  authorization_url: string;
}

export interface PublishJobCreate {
  project_id: UUID;
  social_account_id: UUID;
  render_job_id?: UUID | null;
  title?: string | null;
  description?: string | null;
  tags?: string[] | null;
  privacy?: Privacy;
  scheduled_at?: ISODate | null;
}

export interface PublishJobUpdate {
  title?: string | null;
  description?: string | null;
  tags?: string[] | null;
  privacy?: Privacy | null;
  scheduled_at?: ISODate | null;
}

export interface PublishHistoryEntry extends JSONObject {
  at?: string;
  event?: string;
}

export interface PublishJob extends Entity {
  project_id: UUID;
  social_account_id: UUID;
  render_job_id: UUID;
  platform: Platform;
  status: PublishStatus;
  title: string;
  description: string;
  tags: string[];
  privacy: Privacy | string;
  scheduled_at: ISODate | null;
  next_attempt_at: ISODate | null;
  attempts: number;
  max_attempts: number;
  /** 0..100 */
  upload_progress: number;
  last_error: string | null;
  external_id: string | null;
  external_url: string | null;
  published_at: ISODate | null;
  history: PublishHistoryEntry[];
  /** Present on list responses only. */
  project_title?: string | null;
  account_name?: string | null;
}

export interface ApprovalCreate {
  project_id: UUID;
  publish_job_id?: UUID | null;
  note?: string;
}

export interface ApprovalDecision {
  decision: "approve" | "reject";
  note?: string;
}

export interface Approval extends Entity {
  project_id: UUID;
  publish_job_id: UUID | null;
  requested_by_id: UUID | null;
  reviewer_id: UUID | null;
  status: ApprovalStatus;
  request_note: string;
  decision_note: string | null;
  decided_at: ISODate | null;
  /** Present on list responses only. */
  project_title?: string | null;
}

// ------------------------------------------------------------------ analytics & dashboard

export interface AnalyticsSnapshot extends Entity {
  publish_job_id: UUID;
  platform: Platform;
  external_id: string;
  captured_at: ISODate;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  saves: number;
  impressions: number;
  reach: number;
  watch_time_minutes: number;
  avg_view_duration_sec: number;
}

export interface PerformanceRow {
  publish_job_id: UUID;
  project_id: UUID;
  title: string;
  platform: Platform;
  external_url: string | null;
  published_at: ISODate | null;
  views: number;
  likes: number;
  comments: number;
  shares: number;
  /** percentage, e.g. 4.25 = 4.25% */
  engagement_rate: number;
  watch_time_minutes: number;
}

export interface ChannelPerformance {
  channel_id: UUID;
  name: string;
  posts: number;
  views: number;
  likes: number;
}

export interface DailyViews {
  date: string;
  cumulative_views: number;
}

export interface PerformanceReport {
  period_start: ISODate;
  period_end: ISODate;
  totals: Record<string, number>;
  by_platform: Record<string, Record<string, number>>;
  by_channel: ChannelPerformance[];
  top_posts: PerformanceRow[];
  daily: DailyViews[];
}

export interface DashboardData {
  counts: {
    channels: number;
    projects: number;
    social_accounts: number;
    pending_approvals: number;
    scheduled_posts: number;
    published_posts: number;
    failed_posts: number;
    renders_30d: number;
  };
  project_status: Partial<Record<ProjectStatus, number>>;
  total_views: number;
  usage: {
    tokens_30d: number;
    cost_usd_30d: number;
    tokens_this_month: number;
    monthly_token_budget: number | null;
  };
  upcoming_posts: { id: UUID; title: string; platform: Platform; status: PublishStatus; scheduled_at: ISODate | null }[];
  recent_agent_runs: { id: UUID; project_id: UUID; status: RunStatus; tokens: number; created_at: ISODate }[];
  active_renders: { id: UUID; project_id: UUID; progress: number; stage: string; status: RunStatus }[];
}

/** Payload of GET /renders/{id}/events (Server-Sent Events). */
export interface RenderProgressEvent {
  status: RunStatus;
  stage: string;
  progress: number;
  error: string | null;
}
