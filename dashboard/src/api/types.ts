/**
 * DTO and Data Models for Viral Content Hunter Admin Dashboard.
 * All DTO types reside in this file.
 * Any guessed schema shape is marked with // TODO(reconcile with docs/openapi.json).
 */

// ==========================================
// 1. Common & Health
// ==========================================

// TODO(reconcile with docs/openapi.json)
export interface HealthStatus {
  status: 'ok' | 'degraded' | 'error';
  version: string;
  uptime_seconds?: number;
  timestamp: string;
}

// TODO(reconcile with docs/openapi.json)
export interface ApiErrorResponse {
  message: string;
  detail?: string | Record<string, unknown> | Array<{ loc?: string[]; msg?: string; type?: string }>;
  code?: string;
}

// ==========================================
// 2. Auth (Login / Logout / Me)
// ==========================================

// TODO(reconcile with docs/openapi.json)
export interface LoginRequest {
  username: string;
  password: string;
}

// TODO(reconcile with docs/openapi.json)
export interface LoginResponse {
  success: boolean;
  user: User;
  token?: string; // Token optional if session cookies are used
}

// TODO(reconcile with docs/openapi.json)
export interface User {
  id: string;
  username: string;
  role: 'admin'; // Single admin group; no RBAC (idead.md §12)
}

// ==========================================
// 3. Content Brief (idead.md §10 & Review Workflow §11)
// ==========================================

export type ReviewStatus =
  | 'COLLECTED'
  | 'PREPROCESSED'
  | 'PROCESSING'
  | 'PENDING_CLAUDE_REVIEW'
  | 'APPROVED_BY_CLAUDE'
  | 'REVISION_REQUIRED'
  | 'REJECTED_BY_CLAUDE'
  | 'REVIEW_FAILED';

export type HandoffStatus =
  | 'NOT_HANDED_OFF'
  | 'SELECTED'
  | 'SENT_TELEGRAM'
  | 'ACKNOWLEDGED'
  | 'SEND_FAILED';

export type PriorityLevel = 'P1' | 'P2' | 'P3';

export interface EngagementMetrics {
  views?: number | null;
  likes?: number | null;
  shares?: number | null;
  comments?: number | null;
  growth_rate?: string | null;
  [key: string]: unknown;
}

export interface ScoringReasons {
  virality?: string;
  relevance?: string;
  credibility?: string;
  priority?: string;
}

export interface ReviewHistoryEntry {
  id: string;
  decision: ReviewStatus | string;
  reason: string;
  timestamp: string;
  reviewer: string; // e.g. "Claude Leader"
}

// TODO(reconcile with docs/openapi.json)
export interface ContentBrief {
  // Field 1: ID hồ sơ
  id: string;
  // Field 2: Tiêu đề tiếng Việt
  title_vi: string;
  // Field 3: Tiêu đề gốc
  title_original: string;
  // Field 4: Loại nội dung
  content_type: string;
  // Field 5: Nền tảng
  platform: string;
  // Field 6: Ngôn ngữ gốc
  original_language: string;
  // Field 7: Thời gian đăng nếu biết
  published_at?: string | null;
  // Field 8: Thời gian phát hiện
  discovered_at: string;
  // Field 9: Creator/tác giả nếu biết
  author?: string | null;
  // Field 10: Tóm tắt 50–100 từ
  summary_vi: string;
  // Field 11: Lý do nội dung đáng chú ý
  notable_reason: string;
  // Field 12: Virality Score (0-100)
  virality_score: number;
  // Field 13: Relevance Score (0-100)
  relevance_score: number;
  // Field 14: Credibility (0-100)
  credibility_score: number;
  // Field 15: Priority (P1/P2/P3)
  priority: PriorityLevel;
  // Field 16: URL nguồn gốc
  source_url: string;
  // Field 17: URL nguồn liên quan
  related_urls: string[];
  // Field 18: Chỉ số tương tác có thể thu thập
  engagement_metrics: EngagementMetrics;
  // Field 19: Thời điểm ghi nhận chỉ số
  metrics_recorded_at?: string | null;
  // Field 20: Mức độ xác minh
  verification_level: string;
  // Field 21: Rủi ro và lưu ý
  risks_and_notes: string;
  // Field 22: Gợi ý định dạng khai thác
  suggested_format: string;
  // Field 23: Trạng thái kiểm duyệt
  review_status: ReviewStatus;
  // Field 24: Trạng thái bàn giao
  handoff_status: HandoffStatus;

  // Additional metadata required by idead.md §10 & §12:
  // If summary was generated from metadata only, show prominently
  is_metadata_only_summary: boolean;
  // Scores must be shown separately with reasons
  scoring_reasons?: ScoringReasons;
  // Review history (decisions + reasons)
  review_history?: ReviewHistoryEntry[];
  // Trend Cluster & Series Group associations
  cluster_id?: string | null;
  series_id?: string | null;
}

// TODO(reconcile with docs/openapi.json)
export interface BriefFilterParams {
  platform?: string;
  topic?: string;
  time_range?: 'today' | '24h' | '7d' | '30d' | 'all';
  priority?: PriorityLevel | 'all';
  search?: string;
  limit?: number;
  offset?: number;
}

// ==========================================
// 4. Trend Cluster & Series Group (idead.md §9)
// ==========================================

// TODO(reconcile with docs/openapi.json)
export interface TrendCluster {
  id: string;
  main_topic: string;
  sources_count: number;
  discovered_at: string;
  viral_signal: string;
  credible_source: string;
  status: 'emerging' | 'active' | 'cooling' | string;
  representative_brief_id: string;
  related_brief_ids?: string[];
  briefs?: ContentBrief[];
}

// TODO(reconcile with docs/openapi.json)
export interface SeriesEpisode {
  episode_num?: number;
  title?: string;
  url: string;
}

// TODO(reconcile with docs/openapi.json)
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
// 5. Feedback (idead.md §14)
// ==========================================

export type FeedbackAction = 'good' | 'irrelevant' | 'duplicate' | 'bad_source';

// TODO(reconcile with docs/openapi.json)
export interface FeedbackRequest {
  brief_id: string;
  action: FeedbackAction;
  notes?: string;
}

// TODO(reconcile with docs/openapi.json)
export interface FeedbackResponse {
  success: boolean;
  message: string;
}

// ==========================================
// 6. Handoffs (idead.md §13)
// ==========================================

// TODO(reconcile with docs/openapi.json)
export interface HandoffItem {
  id: string;
  brief_id: string;
  title_vi: string;
  platform: string;
  priority: PriorityLevel;
  virality_score: number;
  handoff_status: HandoffStatus;
  sent_at?: string | null;
  acknowledged_at?: string | null;
  error_message?: string | null;
  retry_count?: number;
}

// ==========================================
// 7. Source Manager (idead.md §4.4 & §12)
// ==========================================

export type ConnectorStatus = 'HEALTHY' | 'WARNING' | 'ERROR' | 'OFFLINE';

export interface SourceErrorLog {
  timestamp: string;
  message: string;
}

// TODO(reconcile with docs/openapi.json)
export interface SourceItem {
  id: string;
  name: string;
  platform: string;
  url: string;
  priority: 'high' | 'medium' | 'low';
  is_active: boolean;
  is_blocked: boolean;
  connector_status: ConnectorStatus;
  last_scanned_at?: string | null;
  error_count: number;
  error_history: SourceErrorLog[];
  reliability_score?: number;
}

// ==========================================
// 8. AI & System Monitor (idead.md §7 & §12)
// ==========================================

export type AIWorkerStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED' | 'RATE_LIMITED';

export interface AIWorkerInfo {
  name: 'Claude' | 'Codex' | 'Gemini' | 'Local AI' | string;
  status: AIWorkerStatus;
  active_jobs: number;
  max_jobs: number;
  quota_status: string; // e.g., "Available", "Rate limited until 14:00"
  last_heartbeat: string;
}

export interface RunningJob {
  id: string;
  worker: string;
  task_type: string;
  target_id?: string;
  started_at: string;
  retry_count: number;
  timeout_seconds: number;
}

export interface DeadLetterJob {
  id: string;
  task_type: string;
  error: string;
  failed_at: string;
  retries: number;
}

export interface SystemErrorItem {
  id: string;
  timestamp: string;
  worker?: string;
  error: string;
  retry_count: number;
}

// TODO(reconcile with docs/openapi.json)
export interface SystemMonitor {
  ai_workers: AIWorkerInfo[];
  running_jobs: RunningJob[];
  queues: {
    urgent: number;
    normal: number;
    dead_letter: number;
  };
  timeouts_count: number;
  retries_count: number;
  quota_errors_count: number;
  recent_errors: SystemErrorItem[];
  dead_letter_jobs: DeadLetterJob[];
}

// ==========================================
// 9. Overview Stats (idead.md §12)
// ==========================================

// TODO(reconcile with docs/openapi.json)
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
// 10. Settings (idead.md §12 & §17)
// ==========================================

export interface ScanScheduleConfig {
  breaking_news_interval_minutes: number;
  trending_interval_minutes: number;
  priority_creator_interval_minutes: number;
  normal_interval_hours: number;
  low_activity_interval_hours: number;
}

export interface JobLimitsConfig {
  claude_sessions: number; // default 1
  codex_max_concurrency: number; // default 2
  gemini_max_concurrency: number; // default 2
  local_max_concurrency: number;
  collector_max_concurrency: number;
}

export interface TelegramConfig {
  configured: boolean;
  chat_id: string;
  alert_p1_enabled: boolean;
  handoff_enabled: boolean;
  bot_token?: string; // WRITE-ONLY; never sent back by API!
}

export interface BudgetPolicyConfig {
  readonly paid_apis_disabled: true; // READ-ONLY: 0 VND policy
  readonly monthly_budget_vnd: 0; // READ-ONLY
  readonly description: string;
}

// TODO(reconcile with docs/openapi.json)
export interface SystemSettings {
  p1_threshold: number; // default 85
  scan_schedule: ScanScheduleConfig;
  watched_sources: string[];
  priority_topics: string[];
  excluded_topics: string[];
  telegram: TelegramConfig;
  job_limits: JobLimitsConfig;
  budget_policy: BudgetPolicyConfig;
  retention_days: number; // default 90 (idead.md §18)
}
