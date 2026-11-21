import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getTrendCluster } from '../api/endpoints';
import { LoadingState } from './LoadingState';
import { ErrorState } from './ErrorState';
import { StatusBadge } from './StatusBadge';
import { Link } from 'react-router-dom';

interface TrendClusterModalProps {
  clusterId: string | null;
  onClose: () => void;
}

export const TrendClusterModal: React.FC<TrendClusterModalProps> = ({ clusterId, onClose }) => {
  const { data: cluster, isLoading, error, refetch } = useQuery({
    queryKey: ['trendCluster', clusterId],
    queryFn: () => getTrendCluster(clusterId!),
    enabled: !!clusterId,
  });

  if (!clusterId) return null;

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="cluster-modal-title"
      onClick={onClose}
    >
      <div
        className="modal-dialog"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: '640px' }}
      >
        <div className="modal-header">
          <h3 id="cluster-modal-title" style={{ margin: 0, fontSize: '16px' }}>
            🔥 Trend Cluster: {cluster?.main_topic || 'Chi tiết cụm xu hướng'}
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
          {isLoading && <LoadingState message="Đang tải dữ liệu cụm xu hướng..." />}

          {error && (
            <ErrorState
              title="Không thể tải Trend Cluster"
              message="Đã có lỗi xảy ra hoặc cụm xu hướng không tồn tại."
              onRetry={() => refetch()}
            />
          )}

          {cluster && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                <span className="badge badge-purple">{cluster.status}</span>
                <span className="badge badge-info">{cluster.sources_count} nguồn thảo luận</span>
                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  Phát hiện lúc: {new Date(cluster.discovered_at).toLocaleString('vi-VN')}
                </span>
              </div>

              <div>
                <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                  Tín hiệu viral:
                </strong>
                <p style={{ marginTop: '4px', fontSize: '13px' }}>{cluster.viral_signal}</p>
              </div>

              <div>
                <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                  Nguồn tin cậy / đại diện:
                </strong>
                <p style={{ marginTop: '4px', fontSize: '13px' }}>{cluster.credible_source}</p>
              </div>

              {cluster.representative_brief_id && (
                <div style={{ padding: '10px', backgroundColor: 'var(--bg-subtle)', borderRadius: 'var(--radius-md)' }}>
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Hồ sơ đại diện:</span>{' '}
                  <Link
                    to={`/briefs/${cluster.representative_brief_id}`}
                    onClick={onClose}
                    style={{ fontWeight: 600, fontSize: '13px' }}
                  >
                    Xem hồ sơ #{cluster.representative_brief_id} →
                  </Link>
                </div>
              )}

              {cluster.briefs && cluster.briefs.length > 0 && (
                <div>
                  <strong style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                    Các bài viết trong cụm ({cluster.briefs.length}):
                  </strong>
                  <ul style={{ marginTop: '6px', listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {cluster.briefs.map((brief) => (
                      <li
                        key={brief.id}
                        style={{
                          padding: '8px 10px',
                          border: '1px solid var(--border-subtle)',
                          borderRadius: 'var(--radius-md)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: '8px',
                        }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <Link
                            to={`/briefs/${brief.id}`}
                            onClick={onClose}
                            style={{ fontSize: '13px', fontWeight: 500 }}
                          >
                            {brief.title_vi || brief.title_original}
                          </Link>
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                            {brief.platform} • {brief.content_type}
                          </div>
                        </div>
                        <StatusBadge type="priority" value={brief.priority} />
                      </li>
                    ))}
                  </ul>
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
