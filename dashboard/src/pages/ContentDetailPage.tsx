import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getBriefDetail,
  exportBriefMarkdown,
  exportBriefJson,
  submitFeedback,
  approveHandoff,
} from '../api/endpoints';
import { FeedbackAction } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';
import { ConfirmModal } from '../components/ConfirmModal';

export const ContentDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const [confirmHandoffOpen, setConfirmHandoffOpen] = useState(false);
  const [feedbackNotice, setFeedbackNotice] = useState<string | null>(null);

  const {
    data: brief,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['briefDetail', id],
    queryFn: () => getBriefDetail(id!),
    enabled: !!id,
  });

  // Export handlers
  const handleExportMarkdown = async () => {
    if (!brief) return;
    try {
      await exportBriefMarkdown(brief.id, brief.title_vi);
    } catch {
      setFeedbackNotice('Không thể tải tệp Markdown.');
    }
  };

  const handleExportJson = async () => {
    if (!brief) return;
    try {
      await exportBriefJson(brief.id, brief.title_vi);
    } catch {
      setFeedbackNotice('Không thể tải tệp JSON.');
    }
  };

  // Feedback mutation
  const feedbackMutation = useMutation({
    mutationFn: submitFeedback,
    onSuccess: (_, variables) => {
      const actionLabels: Record<FeedbackAction, string> = {
        good: 'Tin tốt',
        irrelevant: 'Không phù hợp',
        duplicate: 'Trùng nội dung',
        bad_source: 'Thiếu hoặc sai nguồn',
      };
      setFeedbackNotice(`Đã ghi nhận đánh giá: "${actionLabels[variables.action]}"`);
      setTimeout(() => setFeedbackNotice(null), 3000);
      queryClient.invalidateQueries({ queryKey: ['briefDetail', id] });
    },
  });

  // Handoff approval mutation
  const handoffMutation = useMutation({
    mutationFn: approveHandoff,
    onSuccess: () => {
      setConfirmHandoffOpen(false);
      setFeedbackNotice('Đã gửi thông báo bàn giao qua Telegram thành công!');
      setTimeout(() => setFeedbackNotice(null), 4000);
      queryClient.invalidateQueries({ queryKey: ['briefDetail', id] });
    },
    onError: () => {
      setConfirmHandoffOpen(false);
      setFeedbackNotice('Gửi bàn giao Telegram thất bại. Vui lòng kiểm tra cấu hình.');
      setTimeout(() => setFeedbackNotice(null), 5000);
    },
  });

  if (isLoading) {
    return <LoadingState message="Đang tải toàn bộ hồ sơ Content Brief..." />;
  }

  if (error || !brief) {
    return (
      <ErrorState
        title="Không tìm thấy Content Brief"
        message="Hồ sơ không tồn tại hoặc đã bị xóa theo chính sách lưu trữ."
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Confirm Handoff Modal */}
      <ConfirmModal
        isOpen={confirmHandoffOpen}
        title="Xác nhận bàn giao sang Telegram"
        message={`Bạn có chắc chắn muốn phê duyệt và bàn giao nội dung "${brief.title_vi}" cho đội sản xuất qua Telegram?`}
        confirmText="Bàn giao ngay"
        isLoading={handoffMutation.isPending}
        onConfirm={() => handoffMutation.mutate(brief.id)}
        onCancel={() => setConfirmHandoffOpen(false)}
      />

      {/* Breadcrumb & Navigation */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
          <Link to="/inbox">← Quay lại Hộp thư khám phá</Link> / <span>Hồ sơ #{brief.id}</span>
        </div>

        {/* Export Buttons */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleExportMarkdown}>
            📄 Xuất Markdown
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={handleExportJson}>
            📦 Xuất JSON
          </button>
        </div>
      </div>

      {feedbackNotice && (
        <div className="notice-box notice-info" role="status">
          <span>ℹ️</span>
          <div>{feedbackNotice}</div>
        </div>
      )}

      {/* Prominent Warning if Summary Generated from Metadata Only (idead.md §10) */}
      {brief.is_metadata_only_summary && (
        <div className="notice-box notice-warning" style={{ fontSize: '14px', padding: '14px' }}>
          <span style={{ fontSize: '20px' }}>⚠️</span>
          <div>
            <strong>LƯU Ý QUAN TRỌNG:</strong> Tóm tắt nội dung này được tạo hoàn toàn từ{' '}
            <strong>metadata</strong> công khai (tiêu đề, thẻ tag, mô tả ngắn). Hệ thống chưa tải
            hoặc phân tích toàn bộ nội dung video gốc. Vui lòng kiểm tra lại link nguồn trước khi
            sản xuất.
          </div>
        </div>
      )}

      {/* Header Info */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' }}>
              <StatusBadge type="priority" value={brief.priority} />
              <StatusBadge type="review" value={brief.review_status} />
              <span className="badge badge-info">{brief.platform}</span>
              <span className="badge badge-p3">Ngôn ngữ gốc: {brief.original_language}</span>
              <span className="badge badge-p3">Loại: {brief.content_type}</span>
            </div>
            <h1 style={{ fontSize: '22px', marginBottom: '4px' }}>{brief.title_vi}</h1>
            <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
              Tiêu đề gốc: <em>{brief.title_original || '(Không có)'}</em>
            </p>
          </div>

          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
              Phát hiện: {new Date(brief.discovered_at).toLocaleString('vi-VN')}
            </div>
            {brief.published_at && (
              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Đăng tải: {new Date(brief.published_at).toLocaleString('vi-VN')}
              </div>
            )}
            {brief.author && (
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Tác giả/Creator: <strong>{brief.author}</strong>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Two-column layout: Left (Brief & Content) + Right (Scores, Metrics & Review) */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '20px' }} className="detail-grid">
        {/* Left Column: Brief details */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Summary */}
          <div className="card">
            <h3 style={{ marginBottom: '8px', color: 'var(--primary-text)' }}>
              Tóm tắt tiếng Việt (50–100 từ)
            </h3>
            <p style={{ fontSize: '14px', lineHeight: 1.6, color: 'var(--text-primary)' }}>
              {brief.summary_vi}
            </p>
          </div>

          {/* Reason Notable */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Lý do nội dung đáng chú ý</h3>
            <p style={{ fontSize: '13px', lineHeight: 1.5, color: 'var(--text-secondary)' }}>
              {brief.notable_reason}
            </p>
          </div>

          {/* Suggested Format & Angles */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Gợi ý định dạng khai thác</h3>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              {brief.suggested_format || 'Chưa có gợi ý cụ thể.'}
            </p>
          </div>

          {/* Verification & Risks */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Mức độ xác minh & Rủi ro</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div>
                <strong>Mức độ xác minh:</strong>{' '}
                <span className="badge badge-info">{brief.verification_level}</span>
              </div>
              <div>
                <strong>Rủi ro và lưu ý:</strong>
                <p style={{ marginTop: '4px', color: 'var(--danger-text)' }}>
                  {brief.risks_and_notes || 'Không phát hiện rủi ro đặc biệt.'}
                </p>
              </div>
            </div>
          </div>

          {/* Sources and URLs */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Nguồn tham chiếu</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div>
                <strong>Link nguồn gốc:</strong>{' '}
                <a href={brief.source_url} target="_blank" rel="noopener noreferrer" style={{ wordBreak: 'break-all' }}>
                  {brief.source_url} ↗
                </a>
              </div>
              {brief.related_urls && brief.related_urls.length > 0 && (
                <div>
                  <strong>Các nguồn liên quan ({brief.related_urls.length}):</strong>
                  <ul style={{ marginTop: '4px', paddingLeft: '20px' }}>
                    {brief.related_urls.map((url, idx) => (
                      <li key={idx}>
                        <a href={url} target="_blank" rel="noopener noreferrer" style={{ wordBreak: 'break-all' }}>
                          {url} ↗
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right Column: Scores Breakdown (SEPARATED) & Metrics */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* SEPARATED SCORE BREAKDOWN (Constraint: Never merged into one number!) */}
          <div className="card">
            <h3 style={{ marginBottom: '12px' }}>Chi tiết điểm số (Thang 100)</h3>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {/* Virality */}
              <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>Virality Score</span>
                  <span className="badge badge-danger" style={{ fontSize: '13px' }}>
                    {brief.virality_score}/100
                  </span>
                </div>
                {brief.scoring_reasons?.virality && (
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    {brief.scoring_reasons.virality}
                  </p>
                )}
              </div>

              {/* Relevance */}
              <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>Relevance Score</span>
                  <span className="badge badge-info" style={{ fontSize: '13px' }}>
                    {brief.relevance_score}/100
                  </span>
                </div>
                {brief.scoring_reasons?.relevance && (
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    {brief.scoring_reasons.relevance}
                  </p>
                )}
              </div>

              {/* Credibility */}
              <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>Credibility Score</span>
                  <span className="badge badge-success" style={{ fontSize: '13px' }}>
                    {brief.credibility_score}/100
                  </span>
                </div>
                {brief.scoring_reasons?.credibility && (
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    {brief.scoring_reasons.credibility}
                  </p>
                )}
              </div>

              {/* Priority */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>Mức ưu tiên</span>
                  <StatusBadge type="priority" value={brief.priority} />
                </div>
                {brief.scoring_reasons?.priority && (
                  <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                    {brief.scoring_reasons.priority}
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* Engagement Metrics Snapshot */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Chỉ số tương tác</h3>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
              Thời điểm ghi nhận:{' '}
              {brief.metrics_recorded_at
                ? new Date(brief.metrics_recorded_at).toLocaleString('vi-VN')
                : 'Cùng lúc phát hiện'}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Lượt xem:</span>
                <strong>{brief.engagement_metrics.views?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Lượt thích:</span>
                <strong>{brief.engagement_metrics.likes?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Bình luận:</span>
                <strong>{brief.engagement_metrics.comments?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Chia sẻ:</span>
                <strong>{brief.engagement_metrics.shares?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
              {brief.engagement_metrics.growth_rate && (
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <span>Tốc độ tăng:</span>
                  <span className="badge badge-warning">{brief.engagement_metrics.growth_rate}</span>
                </div>
              )}
            </div>
          </div>

          {/* Handoff Status & Trigger */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Trạng thái bàn giao</h3>
            <div style={{ marginBottom: '12px' }}>
              <StatusBadge type="handoff" value={brief.handoff_status} />
            </div>
            <button
              type="button"
              className="btn btn-primary"
              style={{ width: '100%' }}
              onClick={() => setConfirmHandoffOpen(true)}
              disabled={brief.handoff_status === 'SENT_TELEGRAM' || brief.handoff_status === 'ACKNOWLEDGED'}
            >
              🚀 Phê duyệt & Bàn giao qua Telegram
            </button>
          </div>

          {/* Review History */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Lịch sử kiểm duyệt Claude</h3>
            {brief.review_history && brief.review_history.length > 0 ? (
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {brief.review_history.map((rev) => (
                  <li
                    key={rev.id}
                    style={{
                      padding: '8px',
                      backgroundColor: 'var(--bg-subtle)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '12px',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '2px' }}>
                      <strong>{rev.reviewer}</strong>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {new Date(rev.timestamp).toLocaleTimeString('vi-VN')}
                      </span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)' }}>Quyết định: {rev.decision}</div>
                    <div style={{ marginTop: '2px', color: 'var(--text-muted)' }}>Lý do: {rev.reason}</div>
                  </li>
                ))}
              </ul>
            ) : (
              <p style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Chưa có lịch sử sửa đổi thêm. Đạt tiêu chuẩn ngay vòng duyệt 1.
              </p>
            )}
          </div>

          {/* Quick Feedback */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Đánh giá nhanh</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => feedbackMutation.mutate({ brief_id: brief.id, action: 'good' })}
              >
                👍 Tin tốt
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => feedbackMutation.mutate({ brief_id: brief.id, action: 'irrelevant' })}
              >
                👎 Không phù hợp
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => feedbackMutation.mutate({ brief_id: brief.id, action: 'duplicate' })}
              >
                🔁 Trùng nội dung
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => feedbackMutation.mutate({ brief_id: brief.id, action: 'bad_source' })}
              >
                ⚠️ Sai nguồn
              </button>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @media (max-width: 900px) {
          .detail-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
};
