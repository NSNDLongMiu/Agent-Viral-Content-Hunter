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
import { ApiError } from '../api/client';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';
import { FeasibilityBadge } from '../components/FeasibilityBadge';
import { FocusTagChip } from '../components/FocusTagChip';
import { ConfirmModal } from '../components/ConfirmModal';

export const ContentDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const [confirmHandoffOpen, setConfirmHandoffOpen] = useState(false);
  const [feedbackNotice, setFeedbackNotice] = useState<string | null>(null);

  const {
    data: detail,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['briefDetail', id],
    queryFn: () => getBriefDetail(id!),
    enabled: !!id,
  });

  const brief = detail?.brief;
  const reviewHistory = detail?.review_history || [];

  const canHandoff =
    brief?.handoff_status === 'NOT_HANDED_OFF' ||
    brief?.handoff_status === 'SELECTED' ||
    brief?.handoff_status === 'SEND_FAILED';

  // Export handlers
  const handleExportMarkdown = async () => {
    if (!brief) return;
    try {
      await exportBriefMarkdown(brief.id, brief.title_vi);
    } catch (err) {
      if (err instanceof ApiError && err.status === 501) {
        setFeedbackNotice('Chức năng xuất Markdown đang được phát triển bởi gói T4 (501 Not Implemented).');
      } else {
        setFeedbackNotice('Không thể tải tệp Markdown.');
      }
      setTimeout(() => setFeedbackNotice(null), 4000);
    }
  };

  const handleExportJson = async () => {
    if (!brief) return;
    try {
      await exportBriefJson(brief.id, brief.title_vi);
    } catch (err) {
      if (err instanceof ApiError && err.status === 501) {
        setFeedbackNotice('Chức năng xuất JSON đang được phát triển bởi gói T4 (501 Not Implemented).');
      } else {
        setFeedbackNotice('Không thể tải tệp JSON.');
      }
      setTimeout(() => setFeedbackNotice(null), 4000);
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
        'bad-source': 'Thiếu hoặc sai nguồn',
      };
      setFeedbackNotice(`Đã ghi nhận đánh giá: "${actionLabels[variables.action]}"`);
      setTimeout(() => setFeedbackNotice(null), 3000);
      queryClient.invalidateQueries({ queryKey: ['briefDetail', id] });
    },
    onError: () => {
      setFeedbackNotice('Không thể gửi đánh giá phản hồi. Vui lòng thử lại.');
      setTimeout(() => setFeedbackNotice(null), 4000);
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
    onError: (err: unknown) => {
      setConfirmHandoffOpen(false);
      if (err instanceof ApiError && err.status === 501) {
        setFeedbackNotice('Chức năng gửi Telegram chưa cài đặt adapter Telegram (501 Not Implemented - Gói T6).');
      } else {
        setFeedbackNotice('Gửi bàn giao Telegram thất bại. Vui lòng kiểm tra lại trạng thái.');
      }
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
      {brief.metadata_only && (
        <div className="notice-box notice-warning" style={{ fontSize: '14px', padding: '14px' }}>
          <span style={{ fontSize: '20px' }}>⚠️</span>
          <div>
            <strong>LƯU Ý QUAN TRỌNG:</strong> Tóm tắt nội dung này được tạo hoàn toàn từ{' '}
            <strong>metadata</strong> công khai (tiêu đề, thẻ tag, mô tả ngắn). Hệ thống chưa tải
            hoặc phân tích toàn bộ nội dung video gốc.
            {brief.metadata_note_vi && <div style={{ marginTop: '4px' }}>Ghi chú: {brief.metadata_note_vi}</div>}
          </div>
        </div>
      )}

      {/* Header Info */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' }}>
              <StatusBadge type="priority" value={brief.priority} />
              <StatusBadge type="review" value={brief.status} />
              <FeasibilityBadge feasibility={brief.ai_production?.feasibility} />
              <span className="badge badge-info">{brief.platform}</span>
              <span className="badge badge-p3">Ngôn ngữ gốc: {brief.original_language}</span>
              <span className="badge badge-p3">Loại: {brief.content_type}</span>
            </div>
            <h1 style={{ fontSize: '22px', marginBottom: '4px' }}>{brief.title_vi}</h1>
            {Array.isArray(brief.focus_tags) && brief.focus_tags.length > 0 && (
              <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '6px', marginBottom: '6px' }}>
                {brief.focus_tags.map((tag) => (
                  <FocusTagChip key={tag} tag={tag} />
                ))}
              </div>
            )}
            <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
              Tiêu đề gốc: <em>{brief.original_title || '(Không có)'}</em>
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
            {brief.creator && (
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                Tác giả/Creator: <strong>{brief.creator}</strong>
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
              {brief.why_notable}
            </p>
          </div>

          {/* Suggested Format & Angles */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Gợi ý định dạng khai thác</h3>
            {brief.suggested_formats && brief.suggested_formats.length > 0 ? (
              <ul style={{ paddingLeft: '20px', fontSize: '13px', color: 'var(--text-secondary)' }}>
                {brief.suggested_formats.map((fmt, idx) => (
                  <li key={idx}>{fmt}</li>
                ))}
              </ul>
            ) : (
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Chưa có gợi ý cụ thể.</p>
            )}
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
                {brief.risks_and_notes && brief.risks_and_notes.length > 0 ? (
                  <ul style={{ marginTop: '4px', paddingLeft: '20px', color: 'var(--danger-text)' }}>
                    {brief.risks_and_notes.map((risk, idx) => (
                      <li key={idx}>{risk}</li>
                    ))}
                  </ul>
                ) : (
                  <p style={{ marginTop: '4px', color: 'var(--text-secondary)' }}>
                    Không phát hiện rủi ro đặc biệt.
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* AI Production Card (T9d) */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Khả năng làm bằng AI</h3>
            {brief.ai_production ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px' }}>
                <div>
                  <FeasibilityBadge feasibility={brief.ai_production.feasibility} />
                </div>
                <div>
                  <strong style={{ color: 'var(--text-secondary)' }}>Phương án tiếp cận:</strong>
                  <p style={{ marginTop: '4px', lineHeight: 1.5, color: 'var(--text-primary)' }}>
                    {brief.ai_production.approach_vi}
                  </p>
                </div>
                <div>
                  <strong style={{ color: 'var(--text-secondary)' }}>Ràng buộc cần lưu ý:</strong>
                  {Array.isArray(brief.ai_production.constraints_vi) && brief.ai_production.constraints_vi.length > 0 ? (
                    <ul style={{ marginTop: '4px', paddingLeft: '20px', color: 'var(--text-secondary)' }}>
                      {brief.ai_production.constraints_vi.map((constraint, idx) => (
                        <li key={idx}>{constraint}</li>
                      ))}
                    </ul>
                  ) : (
                    <p style={{ marginTop: '4px', color: 'var(--text-muted)' }}>
                      Không có ràng buộc đặc biệt.
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div>
                <div style={{ marginBottom: '8px' }}>
                  <FeasibilityBadge feasibility={null} />
                </div>
                <p style={{ fontSize: '13px', color: 'var(--text-muted)', margin: 0 }}>
                  Chưa đánh giá khả năng làm bằng AI (hồ sơ cũ).
                </p>
              </div>
            )}
          </div>

          {/* Sources and URLs */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Nguồn tham chiếu</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
              <div>
                <strong>Link nguồn gốc:</strong>{' '}
                <a href={brief.original_url} target="_blank" rel="noopener noreferrer" style={{ wordBreak: 'break-all' }}>
                  {brief.original_url} ↗
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
              </div>

              {/* Relevance */}
              <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>Relevance Score</span>
                  <span className="badge badge-info" style={{ fontSize: '13px' }}>
                    {brief.relevance_score}/100
                  </span>
                </div>
              </div>

              {/* Credibility */}
              <div style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: '8px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>Credibility Score</span>
                  <span className="badge badge-success" style={{ fontSize: '13px' }}>
                    {brief.credibility}/100
                  </span>
                </div>
              </div>

              {/* Priority */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontWeight: 600 }}>Mức ưu tiên</span>
                  <StatusBadge type="priority" value={brief.priority} />
                </div>
              </div>

              {/* Score Explanation */}
              {brief.score_explanation && (
                <div style={{ marginTop: '8px', paddingTop: '8px', borderTop: '1px dashed var(--border-subtle)' }}>
                  <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-secondary)' }}>
                    Giải thích điểm:
                  </span>
                  <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '4px', lineHeight: 1.4 }}>
                    {brief.score_explanation}
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* Engagement Metrics Snapshot */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Chỉ số tương tác</h3>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '8px' }}>
              Thời điểm ghi nhận:{' '}
              {brief.metrics_snapshot_at
                ? new Date(brief.metrics_snapshot_at).toLocaleString('vi-VN')
                : 'Cùng lúc phát hiện'}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '13px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Lượt xem:</span>
                <strong>{brief.engagement_metrics?.views?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Lượt thích:</span>
                <strong>{brief.engagement_metrics?.likes?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Bình luận:</span>
                <strong>{brief.engagement_metrics?.comments?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Chia sẻ:</span>
                <strong>{brief.engagement_metrics?.shares?.toLocaleString('vi-VN') || 'N/A'}</strong>
              </div>
            </div>
          </div>

          {/* Handoff Status & Trigger */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Trạng thái bàn giao</h3>
            <div style={{ marginBottom: canHandoff ? '12px' : 0 }}>
              <StatusBadge type="handoff" value={brief.handoff_status} />
            </div>
            {canHandoff && (
              <button
                type="button"
                className="btn btn-primary"
                style={{ width: '100%' }}
                onClick={() => setConfirmHandoffOpen(true)}
              >
                🚀 Phê duyệt & Bàn giao qua Telegram
              </button>
            )}
          </div>

          {/* Review History */}
          <div className="card">
            <h3 style={{ marginBottom: '8px' }}>Lịch sử kiểm duyệt Claude</h3>
            {reviewHistory.length > 0 ? (
              <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {reviewHistory.map((rev) => (
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
                      <strong>Claude Leader (#{rev.expected_revision})</strong>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {new Date(rev.created_at).toLocaleTimeString('vi-VN')} {new Date(rev.created_at).toLocaleDateString('vi-VN')}
                      </span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)' }}>Hành động: {rev.action} → {rev.resulting_status}</div>
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
                onClick={() => feedbackMutation.mutate({ brief_id: brief.id, action: 'bad-source' })}
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
