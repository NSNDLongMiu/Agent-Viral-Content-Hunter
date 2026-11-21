import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSources, getSourceHealth, toggleSource } from '../api/endpoints';
import { Source, ConnectorHealth } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';
import { ConfirmModal } from '../components/ConfirmModal';

export const SourcesPage: React.FC = () => {
  const queryClient = useQueryClient();

  // Selected source to view error / diagnostic history
  const [selectedSourceForErrors, setSelectedSourceForErrors] = useState<{
    source: Source;
    health?: ConnectorHealth;
  } | null>(null);

  // Toggle modal
  const [toggleConfirmSource, setToggleConfirmSource] = useState<Source | null>(null);

  const [notification, setNotification] = useState<string | null>(null);

  const {
    data: sources,
    isLoading: isSourcesLoading,
    error: sourcesError,
    refetch: refetchSources,
  } = useQuery({
    queryKey: ['sources'],
    queryFn: () => getSources(),
  });

  const { data: healthList } = useQuery({
    queryKey: ['sourcesHealth'],
    queryFn: () => getSourceHealth(),
  });

  const healthMap = React.useMemo(() => {
    const map = new Map<string, ConnectorHealth>();
    (healthList || []).forEach((h) => map.set(h.connector_id, h));
    return map;
  }, [healthList]);

  const toggleMutation = useMutation({
    mutationFn: ({ source, active }: { source: Source; active: boolean }) =>
      toggleSource(source, active),
    onSuccess: (updated) => {
      setToggleConfirmSource(null);
      setNotification(`Đã ${updated.enabled ? 'bật' : 'tắt'} theo dõi nguồn: ${updated.name}`);
      setTimeout(() => setNotification(null), 3000);
      queryClient.invalidateQueries({ queryKey: ['sources'] });
    },
    onError: () => {
      setToggleConfirmSource(null);
      setNotification('Không thể cập nhật trạng thái nguồn.');
      setTimeout(() => setNotification(null), 4000);
    },
  });

  if (isSourcesLoading) {
    return <LoadingState message="Đang tải danh sách nguồn dữ liệu..." />;
  }

  if (sourcesError || !sources) {
    return (
      <ErrorState
        title="Không thể tải danh sách nguồn"
        message="Lỗi kết nối hoặc dịch vụ quản lý nguồn chưa phản hồi."
        onRetry={() => refetchSources()}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Toggle Confirm Modal */}
      {toggleConfirmSource && (
        <ConfirmModal
          isOpen={true}
          title={toggleConfirmSource.enabled ? 'Tắt theo dõi nguồn' : 'Bật theo dõi nguồn'}
          message={`Bạn có chắc muốn ${
            toggleConfirmSource.enabled ? 'tạm dừng quét' : 'kích hoạt lại'
          } nguồn "${toggleConfirmSource.name}"?`}
          confirmText={toggleConfirmSource.enabled ? 'Tắt nguồn' : 'Bật nguồn'}
          confirmVariant={toggleConfirmSource.enabled ? 'danger' : 'primary'}
          isLoading={toggleMutation.isPending}
          onConfirm={() =>
            toggleMutation.mutate({
              source: toggleConfirmSource,
              active: !toggleConfirmSource.enabled,
            })
          }
          onCancel={() => setToggleConfirmSource(null)}
        />
      )}

      {/* Error / Diagnostic Modal */}
      {selectedSourceForErrors && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          onClick={() => setSelectedSourceForErrors(null)}
        >
          <div
            className="modal-dialog"
            onClick={(e) => e.stopPropagation()}
            style={{ maxWidth: '600px' }}
          >
            <div className="modal-header">
              <h3 style={{ margin: 0, fontSize: '16px' }}>
                Thông tin Connector: {selectedSourceForErrors.source.name}
              </h3>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setSelectedSourceForErrors(null)}
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '13px' }}>
                <div>
                  <strong>Mã Connector:</strong> <code>{selectedSourceForErrors.source.connector_id}</code>
                </div>
                <div>
                  <strong>Trạng thái:</strong>{' '}
                  <StatusBadge
                    type="connector"
                    value={selectedSourceForErrors.health?.status || 'AVAILABLE'}
                  />
                </div>
                {selectedSourceForErrors.health?.last_success_at && (
                  <div>
                    <strong>Lần quét thành công gần nhất:</strong>{' '}
                    {new Date(selectedSourceForErrors.health.last_success_at).toLocaleString('vi-VN')}
                  </div>
                )}
                {selectedSourceForErrors.health?.last_error ? (
                  <div className="notice-box notice-danger">
                    <span>⚠️</span>
                    <div>
                      <strong>Lỗi ghi nhận gần nhất:</strong>
                      <div style={{ fontFamily: 'var(--font-mono)', fontSize: '12px', marginTop: '4px' }}>
                        {selectedSourceForErrors.health.last_error}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="notice-box notice-info">
                    <span>ℹ️</span>
                    <div>Không có lỗi nào được ghi nhận cho connector này.</div>
                  </div>
                )}
              </div>
            </div>
            <div className="modal-footer">
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setSelectedSourceForErrors(null)}
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>Quản lý nguồn (Source Manager)</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '2px' }}>
            Giám sát độ tin cậy, lần quét gần nhất, tình trạng connector và lỗi kết nối
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => refetchSources()}>
          🔄 Làm mới
        </button>
      </div>

      {notification && (
        <div className="notice-box notice-info" role="status">
          <span>ℹ️</span>
          <div>{notification}</div>
        </div>
      )}

      {/* Sources Table */}
      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Tên nguồn & Đường dẫn</th>
              <th>Nền tảng</th>
              <th>Mức ưu tiên</th>
              <th>Trạng thái Connector</th>
              <th style={{ textAlign: 'center' }}>Chẩn đoán</th>
              <th style={{ textAlign: 'right' }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((src) => {
              const health = healthMap.get(src.connector_id);
              const connectorStatus = health?.status || (src.blocked ? 'BLOCKED' : 'AVAILABLE');

              return (
                <tr key={src.id} style={{ opacity: src.enabled ? 1 : 0.6 }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{src.name}</div>
                    <a
                      href={src.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ fontSize: '11px', color: 'var(--text-muted)', wordBreak: 'break-all' }}
                    >
                      {src.url} ↗
                    </a>
                  </td>
                  <td>
                    <span className="badge badge-info">{src.platform}</span>
                  </td>
                  <td>
                    <span className="badge badge-p3">Mức {src.priority}</span>
                  </td>
                  <td>
                    <StatusBadge type="connector" value={connectorStatus} />
                    {src.blocked && (
                      <span className="badge badge-danger" style={{ marginLeft: '6px' }}>
                        Bị chặn
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={() => setSelectedSourceForErrors({ source: src, health })}
                      style={{ padding: '2px 8px', fontSize: '11px' }}
                    >
                      {health?.last_error ? '⚠️ Xem lỗi' : 'ℹ️ Chi tiết'}
                    </button>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <button
                      type="button"
                      className={`btn ${src.enabled ? 'btn-secondary' : 'btn-primary'} btn-sm`}
                      onClick={() => setToggleConfirmSource(src)}
                    >
                      {src.enabled ? 'Tạm dừng' : 'Kích hoạt'}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
