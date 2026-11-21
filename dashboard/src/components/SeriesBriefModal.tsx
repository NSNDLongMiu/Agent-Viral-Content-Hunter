import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSeriesBrief } from '../api/endpoints';
import { LoadingState } from './LoadingState';
import { ErrorState } from './ErrorState';

interface SeriesBriefModalProps {
  seriesId: string | null;
  onClose: () => void;
}

export const SeriesBriefModal: React.FC<SeriesBriefModalProps> = ({ seriesId, onClose }) => {
  const { data: series, isLoading, error, refetch } = useQuery({
    queryKey: ['seriesBrief', seriesId],
    queryFn: () => getSeriesBrief(seriesId!),
    enabled: !!seriesId,
  });

  if (!seriesId) return null;

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="series-modal-title"
      onClick={onClose}
    >
      <div
        className="modal-dialog"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '640px' }}
      >
        <div className="modal-header">
          <h3 id="series-modal-title" style={{ margin: 0, fontSize: '16px' }}>
            🎬 Phim ngắn / Micro-Drama: {series?.vietnamese_title || series?.original_title || 'Chi tiết Series'}
          </h3>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={onClose}
            aria-label="Đóng"
            style={{ padding: '2px 8px', border: 'none' }}
          >
            ✕
          </button>
        </div>

        <div className="modal-body">
          {isLoading && <LoadingState message="Đang tải dữ liệu hồ sơ series..." />}

          {error && (
            <ErrorState
              title="Không thể tải Series Brief"
              message="Đã có lỗi xảy ra hoặc hồ sơ phim ngắn không tồn tại."
              onRetry={() => refetch()}
            />
          )}

          {series && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                <span className="badge badge-purple">{series.genre || 'Phim ngắn'}</span>
                {series.is_complete ? (
                  <span className="badge badge-success">Đủ các tập</span>
                ) : (
                  <span className="badge badge-warning">Đang cập nhật / Chưa đủ tập</span>
                )}
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  Tìm thấy: {series.episodes_found} tập
                </span>
              </div>

              <div>
                <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                  Tên gốc / Tác giả:
                </strong>
                <p style={{ marginTop: '2px', fontSize: '13px' }}>
                  {series.original_title} {series.creator ? `— Tác giả/Kênh: ${series.creator}` : ''}
                </p>
              </div>

              <div>
                <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                  Tóm tắt cốt truyện:
                </strong>
                <p style={{ marginTop: '4px', fontSize: '13px', lineHeight: 1.5 }}>
                  {series.plot_summary}
                </p>
              </div>

              {series.rights_info && (
                <div className="notice-box notice-warning">
                  <span>⚠️</span>
                  <div>
                    <strong>Lưu ý bản quyền:</strong> {series.rights_info}
                  </div>
                </div>
              )}

              {series.episodes && series.episodes.length > 0 && (
                <div>
                  <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                    Danh sách các tập ({series.episodes.length}):
                  </strong>
                  <div style={{ marginTop: '8px', maxHeight: '200px', overflowY: 'auto' }}>
                    <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {series.episodes.map((ep, idx) => (
                        <li
                          key={idx}
                          style={{
                            padding: '6px 10px',
                            backgroundColor: 'var(--bg-subtle)',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '12px',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                          }}
                        >
                          <span>
                            Tập {ep.episode_num ?? idx + 1}: {ep.title || 'Video'}
                          </span>
                          <a
                            href={ep.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ fontSize: '12px', wordBreak: 'break-all' }}
                          >
                            Xem nguồn ↗
                          </a>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary btn-sm" onClick={onClose}>
            Đóng
          </button>
        </div>
      </div>
    </div>
  );
};
