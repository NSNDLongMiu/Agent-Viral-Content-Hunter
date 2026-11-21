import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getInboxBriefs, submitFeedback, selectForHandoff } from '../api/endpoints';
import { BriefFilterParams, ContentBrief, FeedbackAction, Priority } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { EmptyState } from '../components/EmptyState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';
import { TrendClusterModal } from '../components/TrendClusterModal';
import { SeriesBriefModal } from '../components/SeriesBriefModal';

export const InboxPage: React.FC = () => {
  const queryClient = useQueryClient();

  // Filters state
  const [platform, setPlatform] = useState<string>('');
  const [topic, setTopic] = useState<string>('');
  const [priority, setPriority] = useState<Priority | 'all'>('all');
  const [timeRange, setTimeRange] = useState<BriefFilterParams['time_range']>('all');
  const [search, setSearch] = useState<string>('');

  // Modals state
  const [activeClusterId, setActiveClusterId] = useState<string | null>(null);
  const [activeSeriesId, setActiveSeriesId] = useState<string | null>(null);

  // Notification / Feedback alert
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const filterParams: BriefFilterParams = {
    platform: platform || undefined,
    topic: topic || undefined,
    priority: priority === 'all' ? undefined : priority,
    time_range: timeRange,
    search: search.trim() || undefined,
  };

  const {
    data: briefs,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['inboxBriefs', filterParams],
    queryFn: () => getInboxBriefs(filterParams),
  });

  // Feedback mutation
  const feedbackMutation = useMutation({
    mutationFn: submitFeedback,
    onSuccess: (_, variables) => {
      const actionLabels: Record<FeedbackAction, string> = {
        good: 'Tin tốt',
        irrelevant: 'Không phù hợp',
        duplicate: 'Trùng nội dung',
        'bad-source': 'Thiếu hoặc sai nguồn',
      };
      setActionNotice(`Đã ghi nhận đánh giá: "${actionLabels[variables.action]}"`);
      setTimeout(() => setActionNotice(null), 3000);
      queryClient.invalidateQueries({ queryKey: ['inboxBriefs'] });
    },
    onError: () => {
      setActionNotice('Không thể gửi đánh giá phản hồi. Vui lòng thử lại.');
      setTimeout(() => setActionNotice(null), 4000);
    },
  });

  // Handoff select mutation
  const selectHandoffMutation = useMutation({
    mutationFn: selectForHandoff,
    onSuccess: () => {
      setActionNotice('Đã chuyển hồ sơ vào danh sách chờ bàn giao (SELECTED).');
      setTimeout(() => setActionNotice(null), 3500);
      queryClient.invalidateQueries({ queryKey: ['inboxBriefs'] });
      queryClient.invalidateQueries({ queryKey: ['handoffs'] });
    },
    onError: () => {
      setActionNotice('Không thể chọn bàn giao hồ sơ.');
      setTimeout(() => setActionNotice(null), 4000);
    },
  });

  const handleFeedback = (briefId: string, action: FeedbackAction) => {
    feedbackMutation.mutate({ brief_id: briefId, action });
  };

  const handleSelectHandoff = (briefId: string) => {
    selectHandoffMutation.mutate(briefId);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Modals */}
      <TrendClusterModal clusterId={activeClusterId} onClose={() => setActiveClusterId(null)} />
      <SeriesBriefModal seriesId={activeSeriesId} onClose={() => setActiveSeriesId(null)} />

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1>Hộp thư khám phá (Discovery Inbox)</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '2px' }}>
            Chỉ hiển thị các hồ sơ đã được Claude kiểm duyệt và phê duyệt (APPROVED_BY_CLAUDE)
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => refetch()}>
          🔄 Làm mới danh sách
        </button>
      </div>

      {/* Feedback / Action Notice */}
      {actionNotice && (
        <div className="notice-box notice-info" role="status">
          <span>ℹ️</span>
          <div>{actionNotice}</div>
        </div>
      )}

      {/* Filter Bar */}
      <div className="card" style={{ padding: '14px' }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '12px',
            alignItems: 'flex-end',
          }}
        >
          {/* Text Search */}
          <div>
            <label className="form-label" htmlFor="search-input">
              Tìm kiếm từ khóa
            </label>
            <input
              id="search-input"
              type="text"
              className="form-control"
              placeholder="Nhập tiêu đề hoặc nội dung..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>

          {/* Platform */}
          <div>
            <label className="form-label" htmlFor="platform-select">
              Nền tảng
            </label>
            <select
              id="platform-select"
              className="form-control"
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
            >
              <option value="">Tất cả nền tảng</option>
              <option value="douyin">Douyin</option>
              <option value="tiktok">TikTok</option>
              <option value="youtube_shorts">YouTube Shorts</option>
              <option value="reels">Instagram Reels</option>
              <option value="weibo">Weibo</option>
              <option value="web">Web / Báo chí</option>
            </select>
          </div>

          {/* Priority */}
          <div>
            <label className="form-label" htmlFor="priority-select">
              Mức ưu tiên
            </label>
            <select
              id="priority-select"
              className="form-control"
              value={priority}
              onChange={(e) => setPriority(e.target.value as Priority | 'all')}
            >
              <option value="all">Tất cả mức ưu tiên</option>
              <option value="P1">P1 (Ưu tiên cao nhất)</option>
              <option value="P2">P2 (Tiềm năng)</option>
              <option value="P3">P3 (Tham khảo)</option>
            </select>
          </div>

          {/* Time Range */}
          <div>
            <label className="form-label" htmlFor="time-range-select">
              Thời gian
            </label>
            <select
              id="time-range-select"
              className="form-control"
              value={timeRange}
              onChange={(e) => setTimeRange(e.target.value as BriefFilterParams['time_range'])}
            >
              <option value="all">Toàn bộ thời gian</option>
              <option value="24h">24 giờ qua</option>
              <option value="7d">7 ngày qua</option>
              <option value="30d">30 ngày qua</option>
            </select>
          </div>

          {/* Reset Filters Button */}
          <div>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ width: '100%' }}
              onClick={() => {
                setPlatform('');
                setTopic('');
                setPriority('all');
                setTimeRange('all');
                setSearch('');
              }}
            >
              Đặt lại bộ lọc
            </button>
          </div>
        </div>
      </div>

      {/* Briefs Content List */}
      {isLoading && <LoadingState message="Đang tải các hồ sơ đã duyệt..." />}

      {error && (
        <ErrorState
          title="Không thể tải hồ sơ khám phá"
          message="Lỗi kết nối đến máy chủ hoặc chưa có dữ liệu hợp lệ."
          onRetry={() => refetch()}
        />
      )}

      {briefs && briefs.length === 0 && (
        <EmptyState
          title="Không tìm thấy hồ sơ nào"
          message="Chưa có tin nào được Claude duyệt phù hợp với các tiêu chí lọc hiện tại."
          actionText="Xóa bộ lọc"
          onAction={() => {
            setPlatform('');
            setTopic('');
            setPriority('all');
            setTimeRange('all');
            setSearch('');
          }}
        />
      )}

      {briefs && briefs.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {briefs.map((brief: ContentBrief) => (
            <div
              key={brief.id}
              className="card"
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
                borderLeft: brief.priority === 'P1' ? '4px solid var(--danger)' : undefined,
              }}
            >
              {/* Card Header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                  <StatusBadge type="priority" value={brief.priority} />
                  <span className="badge badge-info">{brief.platform}</span>
                  <span className="badge badge-p3">{brief.content_type}</span>
                  {brief.cluster_id && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setActiveClusterId(brief.cluster_id!)}
                      style={{ fontSize: '11px', padding: '1px 6px' }}
                    >
                      🔥 Xem Trend Cluster
                    </button>
                  )}
                  {brief.series_id && (
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setActiveSeriesId(brief.series_id!)}
                      style={{ fontSize: '11px', padding: '1px 6px' }}
                    >
                      🎬 Xem Series Brief
                    </button>
                  )}
                </div>

                <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  Phát hiện: {new Date(brief.discovered_at).toLocaleString('vi-VN')}
                </div>
              </div>

              {/* Title & Detail Link */}
              <div>
                <Link
                  to={`/briefs/${brief.id}`}
                  style={{
                    fontSize: '16px',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                    display: 'inline-block',
                    marginBottom: '4px',
                  }}
                >
                  {brief.title_vi}
                </Link>
                {brief.original_title && brief.original_title !== brief.title_vi && (
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    Tiêu đề gốc: {brief.original_title}
                  </div>
                )}
              </div>

              {/* Summary (50-100 words) */}
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                {brief.summary_vi}
              </p>

              {/* Notice if generated from metadata only */}
              {brief.metadata_only && (
                <div className="notice-box notice-warning" style={{ padding: '6px 10px', margin: 0, fontSize: '12px' }}>
                  <span>⚠️</span>
                  <div>Tóm tắt được tạo từ metadata (chưa cào được toàn bộ nội dung gốc).</div>
                </div>
              )}

              {/* Scores breakdown shown separately */}
              <div
                style={{
                  display: 'flex',
                  gap: '16px',
                  padding: '8px 12px',
                  backgroundColor: 'var(--bg-subtle)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: '12px',
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Virality: </span>
                  <strong style={{ color: 'var(--danger-text)' }}>{brief.virality_score}/100</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Relevance: </span>
                  <strong>{brief.relevance_score}/100</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Credibility: </span>
                  <strong>{brief.credibility}/100</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Bàn giao: </span>
                  <StatusBadge type="handoff" value={brief.handoff_status} />
                </div>
              </div>

              {/* Footer Actions: 4 Quick Feedback buttons + Select Handoff */}
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  gap: '10px',
                  borderTop: '1px solid var(--border-subtle)',
                  paddingTop: '10px',
                }}
              >
                {/* 4 Quick Feedback Buttons (idead.md §14) */}
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleFeedback(brief.id, 'good')}
                    title="Đánh giá tin tốt, tăng trọng số"
                  >
                    👍 Tin tốt
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleFeedback(brief.id, 'irrelevant')}
                    title="Đánh giá không phù hợp nhu cầu"
                  >
                    👎 Không phù hợp
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleFeedback(brief.id, 'duplicate')}
                    title="Nội dung đã trùng lặp"
                  >
                    🔁 Trùng nội dung
                  </button>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleFeedback(brief.id, 'bad-source')}
                    title="Nguồn thiếu chính xác hoặc sai lệch"
                  >
                    ⚠️ Thiếu/sai nguồn
                  </button>
                </div>

                {/* Handoff and Details buttons */}
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={() => handleSelectHandoff(brief.id)}
                    disabled={brief.handoff_status !== 'NOT_HANDED_OFF'}
                  >
                    {brief.handoff_status === 'NOT_HANDED_OFF' ? 'Chọn bàn giao' : 'Đã chọn bàn giao'}
                  </button>
                  <Link to={`/briefs/${brief.id}`} className="btn btn-secondary btn-sm">
                    Chi tiết đầy đủ →
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
