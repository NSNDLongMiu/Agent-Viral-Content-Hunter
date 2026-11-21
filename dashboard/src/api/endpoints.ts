/**
 * API Endpoints mapping to backend routers.
 * All functions are typed. Guessed endpoints and query parameters are marked with
 * // TODO(reconcile with docs/openapi.json).
 */

import { apiClient } from './client';
import {
  HealthStatus,
  LoginRequest,
  LoginResponse,
  User,
  ContentBrief,
  BriefFilterParams,
  TrendCluster,
  SeriesBrief,
  FeedbackRequest,
  FeedbackResponse,
  HandoffItem,
  SourceItem,
  SystemMonitor,
  OverviewStats,
  SystemSettings,
  RunningJob,
} from './types';

// ==========================================
// 1. Health
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function getHealth(): Promise<HealthStatus> {
  return apiClient.get<HealthStatus>('/health');
}

// ==========================================
// 2. Auth
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function login(data: LoginRequest): Promise<LoginResponse> {
  return apiClient.post<LoginResponse>('/auth/login', data);
}

// TODO(reconcile with docs/openapi.json)
export async function logout(): Promise<{ success: boolean }> {
  return apiClient.post<{ success: boolean }>('/auth/logout');
}

// TODO(reconcile with docs/openapi.json)
export async function getMe(): Promise<User> {
  return apiClient.get<User>('/auth/me');
}

// ==========================================
// 3. Briefs (Discovery Inbox & Content Detail)
// ==========================================
// idead.md §11 & §12: Discovery Inbox only displays APPROVED_BY_CLAUDE
// TODO(reconcile with docs/openapi.json)
export async function getInboxBriefs(params?: BriefFilterParams): Promise<ContentBrief[]> {
  return apiClient.get<ContentBrief[]>('/briefs', {
    review_status: 'APPROVED_BY_CLAUDE',
    platform: params?.platform,
    topic: params?.topic,
    time_range: params?.time_range,
    priority: params?.priority === 'all' ? undefined : params?.priority,
    search: params?.search,
    limit: params?.limit,
    offset: params?.offset,
  });
}

// TODO(reconcile with docs/openapi.json)
export async function getBriefDetail(id: string): Promise<ContentBrief> {
  return apiClient.get<ContentBrief>(`/briefs/${id}`);
}

// TODO(reconcile with docs/openapi.json)
export async function exportBriefMarkdown(id: string, title: string): Promise<void> {
  const safeFilename = `brief-${id}-${title.slice(0, 30).replace(/[^a-z0-9]/gi, '_')}.md`;
  return apiClient.download(`/briefs/${id}/export/md`, safeFilename);
}

// TODO(reconcile with docs/openapi.json)
export async function exportBriefJson(id: string, title: string): Promise<void> {
  const safeFilename = `brief-${id}-${title.slice(0, 30).replace(/[^a-z0-9]/gi, '_')}.json`;
  return apiClient.download(`/briefs/${id}/export/json`, safeFilename);
}

// TODO(reconcile with docs/openapi.json)
export async function getTrendCluster(clusterId: string): Promise<TrendCluster> {
  return apiClient.get<TrendCluster>(`/briefs/clusters/${clusterId}`);
}

// TODO(reconcile with docs/openapi.json)
export async function getSeriesBrief(seriesId: string): Promise<SeriesBrief> {
  return apiClient.get<SeriesBrief>(`/briefs/series/${seriesId}`);
}

// ==========================================
// 4. Feedback (idead.md §14)
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function submitFeedback(data: FeedbackRequest): Promise<FeedbackResponse> {
  return apiClient.post<FeedbackResponse>('/feedback', data);
}

// ==========================================
// 5. Handoffs (idead.md §13)
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function getHandoffs(): Promise<HandoffItem[]> {
  return apiClient.get<HandoffItem[]>('/handoffs');
}

// TODO(reconcile with docs/openapi.json)
export async function selectForHandoff(briefId: string): Promise<HandoffItem> {
  return apiClient.post<HandoffItem>('/handoffs/select', { brief_id: briefId });
}

// TODO(reconcile with docs/openapi.json)
export async function approveHandoff(briefId: string): Promise<HandoffItem> {
  return apiClient.post<HandoffItem>('/handoffs/approve', { brief_id: briefId });
}

// TODO(reconcile with docs/openapi.json)
export async function retryHandoff(briefId: string): Promise<HandoffItem> {
  return apiClient.post<HandoffItem>('/handoffs/retry', { brief_id: briefId });
}

// TODO(reconcile with docs/openapi.json)
export async function acknowledgeHandoff(briefId: string): Promise<HandoffItem> {
  return apiClient.post<HandoffItem>('/handoffs/acknowledge', { brief_id: briefId });
}

// ==========================================
// 6. Sources (idead.md §4.4)
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function getSources(): Promise<SourceItem[]> {
  return apiClient.get<SourceItem[]>('/sources');
}

// TODO(reconcile with docs/openapi.json)
export async function toggleSource(id: string, active: boolean): Promise<SourceItem> {
  return apiClient.patch<SourceItem>(`/sources/${id}/status`, { is_active: active });
}

// ==========================================
// 7. Jobs (idead.md §7)
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function getJobs(): Promise<RunningJob[]> {
  return apiClient.get<RunningJob[]>('/jobs');
}

// ==========================================
// 8. Monitor & Overview (idead.md §7 & §12)
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function getOverviewStats(): Promise<OverviewStats> {
  return apiClient.get<OverviewStats>('/monitor/overview');
}

// TODO(reconcile with docs/openapi.json)
export async function getMonitorStatus(): Promise<SystemMonitor> {
  return apiClient.get<SystemMonitor>('/monitor');
}

// ==========================================
// 9. Settings (idead.md §12 & §17)
// ==========================================
// TODO(reconcile with docs/openapi.json)
export async function getSettings(): Promise<SystemSettings> {
  return apiClient.get<SystemSettings>('/settings');
}

// TODO(reconcile with docs/openapi.json)
export async function updateSettings(data: Partial<SystemSettings>): Promise<SystemSettings> {
  return apiClient.put<SystemSettings>('/settings', data);
}
