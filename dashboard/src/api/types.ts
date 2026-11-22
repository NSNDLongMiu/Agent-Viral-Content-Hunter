/**
 * DTO and Data Models for Viral Content Hunter Admin Dashboard.
 * Reconciled against docs/openapi.json and docs/API.md.
 */

// ==========================================
// 1. Common, Health & Errors
// ==========================================

export interface HealthResponse {
  status: 'ok';
}
export type HealthStatus = HealthResponse;

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

export interface HTTPValidationError {
  detail?: ValidationError[];
}

export interface ApiErrorResponse {
  message?: string;
  detail?: string | ValidationError[] | Record<string, unknown>;
  code?: string;
}

// ==========================================
// 3. Content Brief (OpenAPI: ContentBrief, BriefDetail, BriefProgress)
// ==========================================

export type FocusTag = 'phim_ngan' | 'micro_drama' | 'giai_tri' | 'ai_san_xuat';

export type AIFeasibility = 'CAO' | 'TRUNG_BINH' | 'THAP';

export interface AIProduction {
  feasibility: AIFeasibility;
  approach_vi: string;
  constraints_vi: string[];
}

export type Priority = 'P1' | 'P2' | 'P3';
export type PriorityLevel = Priority;

export type BriefStatus =
  | 'COLLECTED'
  | 'PREPROCESSED'
  | 'PROCESSING'
  | 'PENDING_CLAUDE_REVIEW'
  | 'APPROVED_BY_CLAUDE'
  | 'REVISION_REQUIRED'
  | 'REJECTED_BY_CLAUDE'
  | 'REVIEW_FAILED';
export type ReviewStatus = BriefStatus;

export type HandoffStatus =
  | 'NOT_HANDED_OFF'
  | 'SELECTED'
  | 'SENT'
  | 'SEND_FAILED'
  | 'ACKNOWLEDGED';

export type ReviewAction = 'APPROVE' | 'REQUEST_REVISION' | 'REJECT';

export interface MetricSnapshot {
  views?: number | null;
  likes?: number | null;
  shares?: number | null;
  comments?: number | null;
  growth_rate?: string | null;
}
export type EngagementMetrics = MetricSnapshot;

export interface ReviewDecision {
  id: number;
  brief_id: string;
  action: ReviewAction;
  reason: string;
  expected_revision: number;
  resulting_status: BriefStatus;
  created_at: string;
}

export interface ContentBrief {
  id: string;
  title_vi: string;
  original_title: string;
  content_type: string;
  platform: string;
  original_language: string;
  published_at: string | null;
  discovered_at: string;
  creator: string | null;
  summary_vi: string;
  why_notable: string;
  virality_score: number;
  relevance_score: number;
  credibility: number;
  priority: Priority;
  original_url: string;
  related_urls: string[];
  engagement_metrics: MetricSnapshot | null;
  metrics_snapshot_at: string | null;
  verification_level: string;
  risks_and_notes: string[];
  suggested_formats: string[];
  metadata_only: boolean;
  metadata_note_vi: string | null;
  score_explanation: string | null;
  status: BriefStatus;
  handoff_status: HandoffStatus;
  revision_count: number;
  created_at: string;
  updated_at: string;

  // AI Production & Focus Tags (T9d contract)
  focus_tags?: FocusTag[];
  ai_production?: AIProduction | null;

  // Compatibility aliases for existing UI components
  author?: string | null;
  source_url?: string;
  title_original?: string;
  notable_reason?: string;
  credibility_score?: number;
  metrics_recorded_at?: string | null;
  is_metadata_only_summary?: boolean;
  suggested_format?: string;
  review_status?: BriefStatus;
  scoring_reasons?: {
    virality?: string;
    relevance?: string;
    credibility?: string;
    priority?: string;
  };
  review_history?: ReviewDecision[];
  cluster_id?: string | null;
  series_id?: string | null;
}

export interface BriefDetail {
  brief: ContentBrief;
  review_history: ReviewDecision[];
}

export interface BriefProgress {
  id: string;
  status: BriefStatus;
  revision_count: number;
}

export interface BriefFilterParams {
  priority?: Priority;
  platform?: string;
  content_type?: string;
  discovered_after?: string;
  search?: string;
  ai_feasibility?: AIFeasibility;
  focus_tag?: FocusTag;
  limit?: number;
  offset?: number;
  // UI filter helpers
  topic?: string;
  time_range?: 'today' | '24h' | '7d' | '30d' | 'all';
}

// ==========================================
// 4. Trend Cluster & Series Group (idead.md §9 / API Gaps)
// Note: Clustering and series endpoints are deferred to T4 and not published in openapi.json.
// ==========================================

export interface TrendCluster {
  id: string;
  main_topic: string;
  sources_count: number;
  discovered_at: string;
  viral_signal: string;
  credible_source: string;
  status: string;
  representative_brief_id: string;
  briefs?: ContentBrief[];
}

export interface SeriesEpisode {
  episode_num?: number;
  title?: string;
  url: string;
}

export interface SeriesBrief {
  id: string;
  original_title: string;
  vietnamese_title: string;
  genre: string;
  plot_summary: string;
  creator?: string;
  episodes_found: number;
  is_complete: boolean;
  episodes: SeriesEpisode[];
  rights_info?: string;
}

// ==========================================
// 5. Feedback (OpenAPI: Feedback, FeedbackInput, FeedbackAction)
// ==========================================

export type FeedbackAction = 'good' | 'irrelevant' | 'duplicate' | 'bad-source';

export interface FeedbackInput {
  brief_id: string;
  action: FeedbackAction;
}
export type FeedbackRequest = FeedbackInput;

export interface Feedback {
  id: number;
  brief_id: string;
  action: FeedbackAction;
  created_at: string;
}
export type FeedbackResponse = Feedback;

// ==========================================
// 6. Handoffs (OpenAPI: Handoff, HandoffSelection, HandoffMessage)
// ==========================================

export interface HandoffSelection {
  brief_id: string;
}

export interface HandoffMessage {
  message: string;
}

export interface Handoff {
  id: string;
  brief_id: string;
  dedup_key: string;
  status: HandoffStatus;
  external_id: string | null;
  last_error: string | null;
  selected_at: string;
  sent_at: string | null;
  acknowledged_at: string | null;
  created_at: string;
  updated_at: string;

  // UI-enriched fields joined from ContentBrief
  title_vi?: string;
  platform?: string;
  priority?: Priority;
  virality_score?: number;
  handoff_status?: HandoffStatus;
  error_message?: string | null;
  retry_count?: number;
}
export type HandoffItem = Handoff;

// ==========================================
// 7. Sources (OpenAPI: Source, SourceInput, SourceChange, ConnectorHealth)
// ==========================================

export type ConnectorState = 'AVAILABLE' | 'DEGRADED' | 'BLOCKED' | 'UNAVAILABLE';
export type ConnectorStatus = ConnectorState;

export interface SourceInput {
  connector_id: string;
  name: string;
  url: string;
  platform: string;
  enabled?: boolean;
  blocked?: boolean;
  priority?: number;
  reliability?: number | null;
  activity?: number | null;
  content_value?: number | null;
}

export interface SourceChange {
  reason: string;
  source: SourceInput;
}

export interface ReasonInput {
  reason: string;
}

export interface Source {
  id: string;
  connector_id: string;
  name: string;
  url: string;
  platform: string;
  enabled: boolean;
  blocked: boolean;
  priority: number;
  reliability: number | null;
  activity: number | null;
  content_value: number | null;
  created_at: string;
  updated_at: string;

  // UI compatibility aliases
  is_active?: boolean;
  is_blocked?: boolean;
  connector_status?: ConnectorState;
  last_scanned_at?: string | null;
  error_count?: number;
  error_history?: SourceErrorLog[];
}
export type SourceItem = Source;

export interface SourceErrorLog {
  timestamp: string;
  message: string;
}

export interface ConnectorHealth {
  connector_id: string;
  status: ConnectorState;
  checked_at: string;
  last_success_at: string | null;
  last_error: string | null;
}

// ==========================================
// 8. Jobs & System Monitor (OpenAPI: Job, JobAttempt, AIHealth)
// ==========================================

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'dead';
export type WorkerKind = 'claude' | 'codex' | 'gemini' | 'local' | 'collector';
export type QueueName = 'urgent' | 'normal';
export type AttemptOutcome = 'succeeded' | 'failed' | 'expired';
export type JobError =
  | 'ERROR'
  | 'TIMEOUT'
  | 'UNAVAILABLE'
  | 'AUTH_LOST'
  | 'QUOTA_EXHAUSTED'
  | 'LEASE_EXPIRED'
  | 'POLICY_BLOCKED';

export interface Job {
  id: string;
  idempotency_key: string;
  kind: string;
  worker: WorkerKind;
  queue: QueueName;
  payload?: Record<string, unknown>;
  status: JobStatus;
  attempt_count: number;
  available_at: string;
  lease_expires_at: string | null;
  last_error: JobError | null;
  created_at: string;
  updated_at: string;

  // UI aliases
  task_type?: string;
  started_at?: string;
  retry_count?: number;
  timeout_seconds?: number;
}
export type RunningJob = Job;

export interface JobAttempt {
  job_id: string;
  number: number;
  worker_id: string;
  created_at: string;
  finished_at: string | null;
  outcome: AttemptOutcome | null;
  error_code: JobError | null;
}

export type AIName = 'claude' | 'codex' | 'gemini' | 'local';
export type AIStatus =
  | 'OK'
  | 'AUTH_LOST'
  | 'QUOTA_EXHAUSTED'
  | 'TIMEOUT'
  | 'UNAVAILABLE'
  | 'ERROR';
export type AIWorkerStatus = AIStatus;

export interface AIHealth {
  name: AIName;
  status: AIStatus;
  available: boolean;
  quota_exhausted: boolean;
  last_error: string | null;
  checked_at: string;
}

export interface AIWorkerInfo {
  name: string;
  status: AIStatus;
  active_jobs: number;
  max_jobs: number;
  quota_status: string;
  last_heartbeat: string;
}

export interface SystemErrorItem {
  id: string;
  timestamp: string;
  worker?: string;
  error: string;
  retry_count: number;
}

export interface SystemMonitor {
  ai_workers: AIWorkerInfo[];
  running_jobs: Job[];
  queues: {
    urgent: number;
    normal: number;
    dead_letter: number;
  };
  timeouts_count: number;
  retries_count: number;
  quota_errors_count: number;
  recent_errors: SystemErrorItem[];
  dead_letter_jobs: Job[];
}

export interface OverviewStats {
  new_items_count: number;
  p1_candidates_count: number;
  waiting_claude_count: number;
  approved_count: number;
  handed_off_count: number;
  source_status_summary: {
    total: number;
    active: number;
    warning: number;
    error: number;
  };
  ai_status_summary: {
    claude: AIWorkerStatus;
    codex: AIWorkerStatus;
    gemini: AIWorkerStatus;
    local: AIWorkerStatus;
  };
  queue_health: {
    urgent: number;
    normal: number;
    status: 'healthy' | 'congested' | 'stalled';
  };
  recent_errors: SystemErrorItem[];
}

// ==========================================
// 9. Settings & Audit (OpenAPI: PublicSettings, DashboardSettings, AuditRecord)
// ==========================================

export type SettingKey =
  | 'p1_threshold'
  | 'scan_intervals_minutes'
  | 'priority_topics'
  | 'excluded_topics'
  | 'telegram_enabled';

export interface DashboardSettings {
  p1_threshold: number;
  scan_intervals_minutes?: Record<string, number>;
  priority_topics: string[];
  excluded_topics: string[];
  telegram_enabled: boolean;
}

export interface BudgetSettings {
  allow_paid_api: false;
}

export interface QueueSettings {
  lease_seconds: number;
  retry_base_seconds: number;
  claude: number;
  codex: number;
  gemini: number;
  local: number;
  collector: number;
}

export interface RetentionSettings {
  days: number;
}

export interface PublicSettings {
  preferences: DashboardSettings;
  budget: BudgetSettings;
  queue: QueueSettings;
  retention: RetentionSettings;
}
export type SystemSettings = PublicSettings;

export interface SettingChange {
  reason: string;
  value: unknown;
}

export interface AuditRecord {
  id: number;
  entity: 'source' | 'setting';
  entity_key: string;
  action: 'create' | 'update' | 'adjust' | 'undo';
  actor: 'admin' | 'automation';
  reason: string;
  before: unknown;
  after: unknown;
  undoes_id: number | null;
  created_at: string;
}
