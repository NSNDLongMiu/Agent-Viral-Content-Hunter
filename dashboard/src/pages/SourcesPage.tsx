import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSources, toggleSource } from '../api/endpoints';
import { SourceItem } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';
import { ConfirmModal } from '../components/ConfirmModal';

export const SourcesPage: React.FC = () => {
  const queryClient = useQueryClient();

  // Selected source to view error history
  const [selectedSourceForErrors, setSelectedSourceForErrors] = useState<SourceItem | null>(null);

  // Toggle modal
  const [toggleConfirmSource, setToggleConfirmSource] = useState<{
    id: string;
    name: string;
    currentActive: boolean;
  } | null>(null);

  const [notification, setNotification] = useState<string | null>(null);

  const {
    data: sources,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['sources'],
    queryFn: getSources,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => toggleSource(id, active),
    onSuccess: (updated) => {
      setToggleConfirmSource(null);
      setNotification(`Đã ${updated.is_active ? 'bật' : 'tắt'} theo dõi nguồn: ${updated.name}`);
      setTimeout(() => setNotification(null), 3000);
      queryClient.invalidateQueries({ queryKey: ['sources'] });
    },
    onError: () => {
      setToggleConfirmSource(null);
      setNotification('Không thể cập nhật trạng thái nguồn.');
      setTimeout(() => setNotification(null), 4000);
    },
  });

  if (isLoading) {
    return <LoadingState message="Đang tải danh sách nguồn dữ liệu..." />;
  }

  if (error || !sources) {
    return (
      <ErrorState
        title="Không thể tải danh sách nguồn"
        message="Lỗi kết nối hoặc dịch vụ quản lý nguồn chưa phản hồi."
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Toggle Confirm Modal */}
      {toggleConfirmSource && (
        <ConfirmModal
          isOpen={true}
          title={toggleConfirmSource.currentActive ? 'Tắt theo dõi nguồn' : 'Bật theo dõi nguồn'}
          message={`Bạn có chắc muốn ${
            toggleConfirmSource.currentActive ? 'tạm dừng quét' : 'kích hoạt lại'
          } nguồn "${toggleConfirmSource.name}"?`}
          confirmText={toggleConfirmSource.currentActive ? 'Tắt nguồn' : 'Bật nguồn'}
          confirmVariant={toggleConfirmSource.currentActive ? 'danger' : 'primary'}
          isLoading={toggleMutation.isPending}
          onConfirm={() =>
            toggleMutation.mutate({
              id: toggleConfirmSource.id,
              active: !toggleConfirmSource.currentActive,
            })
          }
          onCancel={() => setToggleConfirmSource(null)}
        />
      )}

      {/* Error History Modal */}
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
                Lịch sử lỗi: {selectedSourceForErrors.name}
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
              {selectedSourceForErrors.error_history.length === 0 ? (
                <p style={{ color: 'var(--text-muted)', fontSize: '13px' }}>
                  Không có lịch sử lỗi nào được ghi nhận cho nguồn này.
                </p>
              ) : (
                <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {selectedSourceForErrors.error_history.map((err, idx) => (
                    <li
                      key={idx}
                      style={{
                        padding: '8px 10px',
                        backgroundColor: 'var(--bg-subtle)',
                        borderRadius: 'var(--radius-sm)',
                        fontSize: '12px',
                      }}
                    >
                      <div style={{ color: 'var(--text-muted)', marginBottom: '2px' }}>
                        {new Date(err.timestamp).toLocaleString('vi-VN')}
                      </div>
                      <div style={{ color: 'var(--danger-text)', fontFamily: 'var(--font-mono)' }}>
                        {err.message}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
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
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => refetch()}>
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
              <th>Lần quét gần nhất</th>
              <th style={{ textAlign: 'center' }}>Số lỗi</th>
              <th style={{ textAlign: 'right' }}>Thao tác</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((src) => (
              <tr key={src.id} style={{ opacity: src.is_active ? 1 : 0.6 }}>
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
                  <span className="badge badge-p3">{src.priority}</span>
                </td>
                <td>
                  <StatusBadge type="connector" value={src.connector_status} />
                  {src.is_blocked && (
                    <span className="badge badge-danger" style={{ marginLeft: '6px' }}>
                      Bị chặn
                    </span>
                  )}
                </td>
                <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                  {src.last_scanned_at
                    ? new Date(src.last_scanned_at).toLocaleString('vi-VN')
                    : 'Chưa quét'}
                </td>
                <td style={{ textAlign: 'center' }}>
                  {src.error_count > 0 ? (
                    <button
                      type="button"
                      className="btn btn-outline-danger btn-sm"
                      onClick={() => setSelectedSourceForErrors(src)}
                      style={{ padding: '1px 6px', fontSize: '11px' }}
                    >
                      {src.error_count} lỗi ℹ️
                    </button>
                  ) : (
                    <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>0</span>
                  )}
                </td>
                <td style={{ textAlign: 'right' }}>
                  <button
                    type="button"
                    className={`btn ${src.is_active ? 'btn-secondary' : 'btn-primary'} btn-sm`}
                    onClick={() =>
                      setToggleConfirmSource({
                        id: src.id,
                        name: src.name,
                        currentActive: src.is_active,
                      })
                    }
                  >
                    {src.is_active ? 'Tạm dừng' : 'Kích hoạt'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
