/**
 * API Endpoints mapping to backend FastAPI routers.
 * Reconciled against docs/openapi.json and docs/API.md.
 * All HTTP requests in the application go through this module.
 */

import { apiClient } from './client';
import {
  HealthResponse,
  ContentBrief,
  BriefDetail,
  BriefProgress,
  BriefFilterParams,
  BriefStatus,
  TrendCluster,
  SeriesBrief,
  FeedbackInput,
  Feedback,
  Handoff,
  HandoffStatus,
  Source,
  SourceInput,
  ConnectorHealth,
  AuditRecord,
  Job,
  JobAttempt,
  JobStatus,
  AIHealth,
  PublicSettings,
  SettingKey,
  OverviewStats,
  SystemMonitor,
  AIWorkerInfo,
} from './types';

// ==========================================
// 1. Health
// ==========================================

export async function getHealth(): Promise<HealthResponse> {
  return apiClient.get<HealthResponse>('/health');
}

// ==========================================
// 3. Briefs (Discovery Inbox & Content Detail)
// ==========================================

function enrichBrief(b: ContentBrief): ContentBrief {
  return {
    ...b,
    focus_tags: Array.isArray(b.focus_tags) ? b.focus_tags : [],
    ai_production: b.ai_production ?? null,
    author: b.creator,
    source_url: b.original_url,
    title_original: b.original_title,
    notable_reason: b.why_notable,
    credibility_score: b.credibility,
    metrics_recorded_at: b.metrics_snapshot_at,
    is_metadata_only_summary: b.metadata_only,
    suggested_format: b.suggested_formats ? b.suggested_formats.join(', ') : '',
    review_status: b.status,
    scoring_reasons: {
      virality: b.score_explanation || undefined,
      relevance: b.score_explanation || undefined,
      credibility: b.score_explanation || undefined,
      priority: b.score_explanation || undefined,
    },
  };
}

function calculateDiscoveredAfter(timeRange?: string): string | undefined {
  if (!timeRange || timeRange === 'all') return undefined;
  const now = new Date();
  if (timeRange === 'today') {
    now.setUTCHours(0, 0, 0, 0);
    return now.toISOString();
  }
  if (timeRange === '24h') {
    return new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
  }
  if (timeRange === '7d') {
    return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString();
  }
  if (timeRange === '30d') {
    return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString();
  }
  return undefined;
}

export async function getInboxBriefs(params?: BriefFilterParams): Promise<ContentBrief[]> {
  const discoveredAfter = params?.discovered_after || calculateDiscoveredAfter(params?.time_range);
  const searchParam = params?.search || (params?.topic ? params.topic : undefined);
  const priorityParam = params?.priority;

  const rawBriefs = await apiClient.get<ContentBrief[]>('/briefs/inbox', {
    priority: priorityParam,
    platform: params?.platform || undefined,
    content_type: params?.content_type || undefined,
    discovered_after: discoveredAfter || undefined,
    search: searchParam || undefined,
    ai_feasibility: params?.ai_feasibility || undefined,
    focus_tag: params?.focus_tag || undefined,
    limit: params?.limit || 50,
    offset: params?.offset || 0,
  });

  return (rawBriefs || []).map(enrichBrief);
}

export async function getBriefDetail(id: string): Promise<BriefDetail> {
  const detail = await apiClient.get<BriefDetail>(`/briefs/${id}`);
  return {
    brief: enrichBrief(detail.brief),
    review_history: detail.review_history || [],
  };
}

export async function exportBriefMarkdown(id: string, title: string): Promise<void> {
  const safeFilename = `brief-${id}-${title.slice(0, 30).replace(/[^a-z0-9]/gi, '_')}.md`;
  return apiClient.download(`/briefs/${id}/export/md`, safeFilename);
}

export async function exportBriefJson(id: string, title: string): Promise<void> {
  const safeFilename = `brief-${id}-${title.slice(0, 30).replace(/[^a-z0-9]/gi, '_')}.json`;
  return apiClient.download(`/briefs/${id}/export/json`, safeFilename);
}

// Gaps: TrendCluster & SeriesBrief are deferred to T4 (no API endpoint published in openapi.json)
export async function getTrendCluster(clusterId: string): Promise<TrendCluster> {
  throw new Error(`Chức năng Trend Cluster (#${clusterId}) hiện chưa có endpoint API hỗ trợ (thuộc phạm vi T4).`);
}

export async function getSeriesBrief(seriesId: string): Promise<SeriesBrief> {
  throw new Error(`Chức năng Series Brief (#${seriesId}) hiện chưa có endpoint API hỗ trợ (thuộc phạm vi T4).`);
}

// ==========================================
// 4. Feedback (idead.md §14)
// ==========================================

export async function submitFeedback(data: FeedbackInput): Promise<Feedback> {
  return apiClient.post<Feedback>('/feedback', {
    brief_id: data.brief_id,
    action: data.action,
  });
}

export async function getFeedback(params?: {
  brief_id?: string;
  limit?: number;
  offset?: number;
}): Promise<Feedback[]> {
  return apiClient.get<Feedback[]>('/feedback', params);
}

// ==========================================
// 5. Handoffs (idead.md §13)
// ==========================================

export async function getHandoffs(params?: {
  status?: HandoffStatus;
  limit?: number;
  offset?: number;
}): Promise<Handoff[]> {
  const raw = await apiClient.get<Handoff[]>('/handoffs', params);
  return (raw || []).map((h) => ({
    ...h,
    handoff_status: h.status,
    error_message: h.last_error,
  }));
}

export async function selectForHandoff(briefId: string): Promise<Handoff> {
  const res = await apiClient.post<Handoff>('/handoffs', { brief_id: briefId });
  return {
    ...res,
    handoff_status: res.status,
    error_message: res.last_error,
  };
}

export async function getHandoffDetail(handoffId: string): Promise<Handoff> {
  const res = await apiClient.get<Handoff>(`/handoffs/${handoffId}`);
  return {
    ...res,
    handoff_status: res.status,
    error_message: res.last_error,
  };
}

export async function sendHandoff(handoffId: string, message?: string): Promise<Handoff> {
  const res = await apiClient.post<Handoff>(`/handoffs/${handoffId}/send`, {
    message: message || 'Bàn giao hồ sơ nội dung sang Telegram',
  });
  return {
    ...res,
    handoff_status: res.status,
    error_message: res.last_error,
  };
}

export async function checkAckHandoff(handoffId: string): Promise<Handoff> {
  const res = await apiClient.post<Handoff>(`/handoffs/${handoffId}/check-ack`);
  return {
    ...res,
    handoff_status: res.status,
    error_message: res.last_error,
  };
}

// Convenience handoff helpers matching UI actions
export async function approveHandoff(handoffIdOrBriefId: string): Promise<Handoff> {
  try {
    return await sendHandoff(handoffIdOrBriefId);
  } catch {
    const handoff = await selectForHandoff(handoffIdOrBriefId);
    return await sendHandoff(handoff.id);
  }
}

export async function retryHandoff(handoffIdOrBriefId: string): Promise<Handoff> {
  return sendHandoff(handoffIdOrBriefId);
}

export async function acknowledgeHandoff(handoffId: string): Promise<Handoff> {
  return checkAckHandoff(handoffId);
}

// ==========================================
// 6. Sources (idead.md §4.4)
// ==========================================

function enrichSource(s: Source): Source {
  return {
    ...s,
    is_active: s.enabled,
    is_blocked: s.blocked,
    error_count: s.blocked ? 1 : 0,
    error_history: [],
  };
}

export async function getSources(params?: { limit?: number; offset?: number }): Promise<Source[]> {
  const list = await apiClient.get<Source[]>('/sources', params);
  return (list || []).map(enrichSource);
}

export async function getSourceHealth(): Promise<ConnectorHealth[]> {
  return apiClient.get<ConnectorHealth[]>('/sources/health');
}

export async function getSource(sourceId: string): Promise<Source> {
  const s = await apiClient.get<Source>(`/sources/${sourceId}`);
  return enrichSource(s);
}

export async function addSource(source: SourceInput, reason?: string): Promise<Source> {
  const s = await apiClient.post<Source>('/sources', {
    reason: reason || 'Thêm nguồn mới qua giao diện quản trị',
    source,
  });
  return enrichSource(s);
}

export async function updateSource(sourceId: string, source: SourceInput, reason?: string): Promise<Source> {
  const s = await apiClient.put<Source>(`/sources/${sourceId}`, {
    reason: reason || 'Cập nhật nguồn qua giao diện quản trị',
    source,
  });
  return enrichSource(s);
}

export async function toggleSource(sourceOrId: Source | string, active: boolean): Promise<Source> {
  if (typeof sourceOrId === 'string') {
    const existing = await getSource(sourceOrId);
    return updateSource(
      sourceOrId,
      {
        connector_id: existing.connector_id,
        name: existing.name,
        url: existing.url,
        platform: existing.platform,
        enabled: active,
        blocked: existing.blocked,
        priority: existing.priority,
        reliability: existing.reliability,
        activity: existing.activity,
        content_value: existing.content_value,
      },
      `Thay đổi trạng thái kích hoạt nguồn: ${active ? 'Bật' : 'Tắt'}`
    );
  }

  return updateSource(
    sourceOrId.id,
    {
      connector_id: sourceOrId.connector_id,
      name: sourceOrId.name,
      url: sourceOrId.url,
      platform: sourceOrId.platform,
      enabled: active,
      blocked: sourceOrId.blocked,
      priority: sourceOrId.priority,
      reliability: sourceOrId.reliability,
      activity: sourceOrId.activity,
      content_value: sourceOrId.content_value,
    },
    `Thay đổi trạng thái kích hoạt nguồn: ${active ? 'Bật' : 'Tắt'}`
  );
}

export async function removeSource(sourceId: string, reason?: string): Promise<AuditRecord> {
  return apiClient.post<AuditRecord>(`/sources/${sourceId}/remove`, {
    reason: reason || 'Gỡ bỏ nguồn qua giao diện quản trị',
  });
}

// ==========================================
// 7. Jobs (idead.md §7)
// ==========================================

export async function getJobs(params?: {
  status?: JobStatus;
  limit?: number;
  offset?: number;
}): Promise<Job[]> {
  const list = await apiClient.get<Job[]>('/jobs', params);
  return (list || []).map((j) => ({
    ...j,
    task_type: j.kind,
    started_at: j.created_at,
    retry_count: j.attempt_count > 1 ? j.attempt_count - 1 : 0,
    timeout_seconds: 60,
  }));
}

export async function getJob(jobId: string): Promise<Job> {
  const j = await apiClient.get<Job>(`/jobs/${jobId}`);
  return {
    ...j,
    task_type: j.kind,
    started_at: j.created_at,
    retry_count: j.attempt_count > 1 ? j.attempt_count - 1 : 0,
    timeout_seconds: 60,
  };
}

export async function getJobAttempts(jobId: string): Promise<JobAttempt[]> {
  return apiClient.get<JobAttempt[]>(`/jobs/${jobId}/attempts`);
}

// ==========================================
// 8. Monitor & Real Operational Status
// ==========================================

export async function getMonitorAi(): Promise<AIHealth[]> {
  return apiClient.get<AIHealth[]>('/monitor/ai');
}

export async function getMonitorQueues(): Promise<Record<string, Record<string, number>>> {
  return apiClient.get<Record<string, Record<string, number>>>('/monitor/queues');
}

export async function getMonitorErrors(params?: { limit?: number; offset?: number }): Promise<JobAttempt[]> {
  return apiClient.get<JobAttempt[]>('/monitor/errors', params);
}

export async function getMonitorBriefs(params?: {
  status?: BriefStatus;
  limit?: number;
  offset?: number;
}): Promise<BriefProgress[]> {
  return apiClient.get<BriefProgress[]>('/monitor/briefs', params);
}

export async function getMonitorBriefDetail(briefId: string): Promise<BriefDetail> {
  return apiClient.get<BriefDetail>(`/monitor/briefs/${briefId}`);
}

// High-level aggregator for Overview screen using real API endpoints
export async function getOverviewStats(): Promise<OverviewStats> {
  const [briefsProgress, approvedBriefs, handoffs, sources, aiHealth, queues, errors] =
    await Promise.allSettled([
      getMonitorBriefs(),
      getInboxBriefs({ limit: 200 }),
      getHandoffs({ limit: 200 }),
      getSources(),
      getMonitorAi(),
      getMonitorQueues(),
      getMonitorErrors({ limit: 10 }),
    ]);

  const briefList = briefsProgress.status === 'fulfilled' ? briefsProgress.value : [];
  const approvedList = approvedBriefs.status === 'fulfilled' ? approvedBriefs.value : [];
  const handoffList = handoffs.status === 'fulfilled' ? handoffs.value : [];
  const sourceList = sources.status === 'fulfilled' ? sources.value : [];
  const aiList = aiHealth.status === 'fulfilled' ? aiHealth.value : [];
  const queueData = queues.status === 'fulfilled' ? queues.value : {};
  const errorList = errors.status === 'fulfilled' ? errors.value : [];

  // Metrics calculation from verified facts
  const newItemsCount = briefList.filter((b) => b.status === 'COLLECTED').length;
  const p1CandidatesCount = approvedList.filter((b) => b.priority === 'P1').length;
  const waitingClaudeCount = briefList.filter((b) => b.status === 'PENDING_CLAUDE_REVIEW').length;
  const approvedCount = approvedList.length;
  const handedOffCount = handoffList.filter(
    (h) => h.status === 'SENT' || h.status === 'ACKNOWLEDGED'
  ).length;

  const activeSources = sourceList.filter((s) => s.enabled && !s.blocked).length;
  const warningSources = sourceList.filter((s) => s.blocked).length;

  const findAiStatus = (name: string): AIHealth['status'] => {
    const item = aiList.find((a) => a.name.toLowerCase() === name.toLowerCase());
    return item ? item.status : 'UNAVAILABLE';
  };

  const urgentQueueTotal = Object.values(queueData.urgent || {}).reduce((acc, v) => acc + v, 0);
  const normalQueueTotal = Object.values(queueData.normal || {}).reduce((acc, v) => acc + v, 0);

  return {
    new_items_count: newItemsCount,
    p1_candidates_count: p1CandidatesCount,
    waiting_claude_count: waitingClaudeCount,
    approved_count: approvedCount,
    handed_off_count: handedOffCount,
    source_status_summary: {
      total: sourceList.length,
      active: activeSources,
      warning: warningSources,
      error: warningSources,
    },
    ai_status_summary: {
      claude: findAiStatus('claude'),
      codex: findAiStatus('codex'),
      gemini: findAiStatus('gemini'),
      local: findAiStatus('local'),
    },
    queue_health: {
      urgent: urgentQueueTotal,
      normal: normalQueueTotal,
      status: urgentQueueTotal > 20 ? 'congested' : 'healthy',
    },
    recent_errors: errorList.map((e, idx) => ({
      id: `${e.job_id}-${e.number}-${idx}`,
      timestamp: e.created_at,
      worker: e.worker_id,
      error: e.error_code || 'Lỗi xử lý tác vụ',
      retry_count: e.number,
    })),
  };
}

// High-level aggregator for Monitor screen using real API endpoints
export async function getMonitorStatus(): Promise<SystemMonitor> {
  const [aiHealth, queues, runningJobs, errors, deadJobs] = await Promise.allSettled([
    getMonitorAi(),
    getMonitorQueues(),
    getJobs({ status: 'running' }),
    getMonitorErrors({ limit: 20 }),
    getJobs({ status: 'dead' }),
  ]);

  const aiList = aiHealth.status === 'fulfilled' ? aiHealth.value : [];
  const queueData = queues.status === 'fulfilled' ? queues.value : {};
  const runningList = runningJobs.status === 'fulfilled' ? runningJobs.value : [];
  const errorList = errors.status === 'fulfilled' ? errors.value : [];
  const deadList = deadJobs.status === 'fulfilled' ? deadJobs.value : [];

  const aiWorkers: AIWorkerInfo[] = aiList.map((w) => ({
    name: w.name === 'claude' ? 'Claude' : w.name === 'codex' ? 'Codex' : w.name === 'gemini' ? 'Gemini' : 'Local AI',
    status: w.status,
    active_jobs: runningList.filter((j) => j.worker.toLowerCase() === w.name.toLowerCase()).length,
    max_jobs: 2,
    quota_status: w.quota_exhausted ? 'Hết hạn ngạch (Quota Exhausted)' : w.available ? 'Sẵn sàng' : 'Không khả dụng',
    last_heartbeat: w.checked_at,
  }));

  const urgentTotal = Object.values(queueData.urgent || {}).reduce((acc, v) => acc + v, 0);
  const normalTotal = Object.values(queueData.normal || {}).reduce((acc, v) => acc + v, 0);
  const deadTotal = deadList.length;

  const timeoutsCount = errorList.filter((e) => e.error_code === 'TIMEOUT').length;
  const quotaErrorsCount = errorList.filter((e) => e.error_code === 'QUOTA_EXHAUSTED').length;

  return {
    ai_workers: aiWorkers,
    running_jobs: runningList,
    queues: {
      urgent: urgentTotal,
      normal: normalTotal,
      dead_letter: deadTotal,
    },
    timeouts_count: timeoutsCount,
    retries_count: errorList.length,
    quota_errors_count: quotaErrorsCount,
    recent_errors: errorList.map((e, idx) => ({
      id: `${e.job_id}-${idx}`,
      timestamp: e.created_at,
      worker: e.worker_id,
      error: e.error_code || 'Lỗi không xác định',
      retry_count: e.number,
    })),
    dead_letter_jobs: deadList,
  };
}

// ==========================================
// 9. Settings & Audit Log
// ==========================================

export async function getSettings(): Promise<PublicSettings> {
  return apiClient.get<PublicSettings>('/settings');
}

export async function setSettingPreference(
  key: SettingKey,
  value: unknown,
  reason?: string
): Promise<AuditRecord> {
  return apiClient.put<AuditRecord>(`/settings/${key}`, {
    reason: reason || `Cập nhật tùy chọn ${key} qua giao diện quản trị`,
    value,
  });
}

export async function updateSettings(
  changes: Partial<PublicSettings['preferences']>,
  reason?: string
): Promise<void> {
  // Update editable preference keys one by one using PUT /settings/{key}
  const editableKeys: SettingKey[] = [
    'p1_threshold',
    'scan_intervals_minutes',
    'priority_topics',
    'excluded_topics',
    'telegram_enabled',
  ];

  for (const key of editableKeys) {
    if (changes[key] !== undefined) {
      await setSettingPreference(key, changes[key], reason);
    }
  }
}

export async function getSettingsAudit(params?: {
  limit?: number;
  offset?: number;
}): Promise<AuditRecord[]> {
  return apiClient.get<AuditRecord[]>('/settings/audit', params);
}

export async function undoSettingsChange(recordId: number, reason?: string): Promise<AuditRecord> {
  return apiClient.post<AuditRecord>(`/settings/audit/${recordId}/undo`, {
    reason: reason || 'Hoàn tác cài đặt qua giao diện quản trị',
  });
}
