import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  getHandoffs,
  approveHandoff,
  retryHandoff,
  acknowledgeHandoff,
} from '../api/endpoints';
import { HandoffItem, HandoffStatus } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';
import { ConfirmModal } from '../components/ConfirmModal';

interface HandoffColumnConfig {
  key: HandoffStatus;
  title: string;
  badgeClass: string;
  description: string;
}

const COLUMNS: HandoffColumnConfig[] = [
  {
    key: 'NOT_HANDED_OFF',
    title: 'Chưa bàn giao',
    badgeClass: 'badge-p3',
    description: 'Tin đã duyệt nhưng chưa chọn bàn giao',
  },
  {
    key: 'SELECTED',
    title: 'Đã chọn bàn giao',
    badgeClass: 'badge-purple',
    description: 'Đang chuẩn bị gửi sang Telegram',
  },
  {
    key: 'SENT_TELEGRAM',
    title: 'Đã gửi Telegram',
    badgeClass: 'badge-info',
    description: 'Đã phát cảnh báo, chờ đội nhận bấm xác nhận',
  },
  {
    key: 'ACKNOWLEDGED',
    title: 'Đã xác nhận tiếp nhận',
    badgeClass: 'badge-success',
    description: 'Đội sản xuất đã tiếp nhận thành công',
  },
  {
    key: 'SEND_FAILED',
    title: 'Gửi thất bại',
    badgeClass: 'badge-danger',
    description: 'Lỗi gửi tin hoặc Telegram timeout',
  },
];

export const HandoffPage: React.FC = () => {
  const queryClient = useQueryClient();

  // Modals for sensitive actions (handoff send, retry)
  const [modalAction, setModalAction] = useState<{
    type: 'approve' | 'retry';
    item: HandoffItem;
  } | null>(null);

  const [notification, setNotification] = useState<string | null>(null);

  const {
    data: handoffs,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['handoffs'],
    queryFn: getHandoffs,
    refetchInterval: 10000,
  });

  const approveMutation = useMutation({
    mutationFn: approveHandoff,
    onSuccess: (updated) => {
      setModalAction(null);
      setNotification(`Đã gửi bàn giao "${updated.title_vi}" sang Telegram.`);
      setTimeout(() => setNotification(null), 3500);
      queryClient.invalidateQueries({ queryKey: ['handoffs'] });
    },
    onError: () => {
      setModalAction(null);
      setNotification('Không thể gửi bàn giao qua Telegram. Vui lòng kiểm tra lại dịch vụ.');
      setTimeout(() => setNotification(null), 4000);
    },
  });

  const retryMutation = useMutation({
    mutationFn: retryHandoff,
    onSuccess: (updated) => {
      setModalAction(null);
      setNotification(`Đang thử gửi lại "${updated.title_vi}"...`);
      setTimeout(() => setNotification(null), 3500);
      queryClient.invalidateQueries({ queryKey: ['handoffs'] });
    },
    onError: () => {
      setModalAction(null);
      setNotification('Thử gửi lại thất bại.');
      setTimeout(() => setNotification(null), 4000);
    },
  });

  const acknowledgeMutation = useMutation({
    mutationFn: acknowledgeHandoff,
    onSuccess: (updated) => {
      setNotification(`Đã đánh dấu tiếp nhận thành công: "${updated.title_vi}"`);
      setTimeout(() => setNotification(null), 3500);
      queryClient.invalidateQueries({ queryKey: ['handoffs'] });
    },
  });

  if (isLoading) {
    return <LoadingState message="Đang tải bảng theo dõi bàn giao..." />;
  }

  if (error || !handoffs) {
    return (
      <ErrorState
        title="Không thể tải bảng bàn giao"
        message="Không thể kết nối đến máy chủ hoặc chưa lấy được dữ liệu bàn giao."
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Confirm Modal */}
      {modalAction && (
        <ConfirmModal
          isOpen={true}
          title={modalAction.type === 'approve' ? 'Xác nhận gửi bàn giao' : 'Thử lại gửi Telegram'}
          message={
            modalAction.type === 'approve'
              ? `Bạn có chắc chắn muốn gửi nội dung "${modalAction.item.title_vi}" sang Telegram cho đội sản xuất?`
              : `Thử gửi lại tin "${modalAction.item.title_vi}" sang Telegram?`
          }
          confirmText={modalAction.type === 'approve' ? 'Gửi Telegram' : 'Thử lại'}
          isLoading={approveMutation.isPending || retryMutation.isPending}
          onConfirm={() => {
            if (modalAction.type === 'approve') {
              approveMutation.mutate(modalAction.item.brief_id);
            } else {
              retryMutation.mutate(modalAction.item.brief_id);
            }
          }}
          onCancel={() => setModalAction(null)}
        />
      )}

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>Bảng bàn giao (Handoff Board)</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '2px' }}>
            Phân biệt rõ ràng giữa "Đã gửi Telegram" và "Đã xác nhận tiếp nhận"
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => refetch()}>
          🔄 Làm mới bảng
        </button>
      </div>

      {notification && (
        <div className="notice-box notice-info" role="status">
          <span>ℹ️</span>
          <div>{notification}</div>
        </div>
      )}

      {/* Kanban-style 5 Columns */}
      <div
        className="handoff-board"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(5, minmax(220px, 1fr))',
          gap: '14px',
          alignItems: 'flex-start',
          overflowX: 'auto',
          paddingBottom: '16px',
        }}
      >
        {COLUMNS.map((col) => {
          const itemsInCol = handoffs.filter((h) => h.handoff_status === col.key);

          return (
            <div
              key={col.key}
              style={{
                backgroundColor: 'var(--bg-subtle)',
                borderRadius: 'var(--radius-lg)',
                border: '1px solid var(--border-color)',
                display: 'flex',
                flexDirection: 'column',
                minHeight: '400px',
              }}
            >
              {/* Column Header */}
              <div
                style={{
                  padding: '12px',
                  borderBottom: '1px solid var(--border-subtle)',
                  backgroundColor: 'var(--bg-surface)',
                  borderTopLeftRadius: 'var(--radius-lg)',
                  borderTopRightRadius: 'var(--radius-lg)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <strong style={{ fontSize: '13px' }}>{col.title}</strong>
                  <span className={`badge ${col.badgeClass}`}>{itemsInCol.length}</span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                  {col.description}
                </div>
              </div>

              {/* Items Container */}
              <div style={{ padding: '10px', display: 'flex', flexDirection: 'column', gap: '10px', flex: 1 }}>
                {itemsInCol.length === 0 ? (
                  <div
                    style={{
                      padding: '24px 12px',
                      textAlign: 'center',
                      color: 'var(--text-muted)',
                      fontSize: '12px',
                      fontStyle: 'italic',
                    }}
                  >
                    Trống
                  </div>
                ) : (
                  itemsInCol.map((item) => (
                    <div
                      key={item.id}
                      className="card"
                      style={{
                        padding: '12px',
                        backgroundColor: 'var(--bg-surface)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '8px',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <StatusBadge type="priority" value={item.priority} />
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{item.platform}</span>
                      </div>

                      <Link
                        to={`/briefs/${item.brief_id}`}
                        style={{
                          fontSize: '13px',
                          fontWeight: 600,
                          color: 'var(--text-primary)',
                          lineHeight: 1.4,
                        }}
                      >
                        {item.title_vi}
                      </Link>

                      <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                        Điểm viral: <strong style={{ color: 'var(--danger-text)' }}>{item.virality_score}</strong>
                      </div>

                      {/* Timestamps or Error */}
                      {item.sent_at && (
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                          Gửi lúc: {new Date(item.sent_at).toLocaleTimeString('vi-VN')} {new Date(item.sent_at).toLocaleDateString('vi-VN')}
                        </div>
                      )}
                      {item.acknowledged_at && (
                        <div style={{ fontSize: '10px', color: 'var(--success-text)' }}>
                          Tiếp nhận: {new Date(item.acknowledged_at).toLocaleTimeString('vi-VN')}
                        </div>
                      )}
                      {item.error_message && (
                        <div style={{ fontSize: '11px', color: 'var(--danger-text)' }}>
                          ⚠️ {item.error_message}
                        </div>
                      )}

                      {/* Column-specific actions */}
                      <div style={{ marginTop: '4px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {item.handoff_status === 'SELECTED' && (
                          <button
                            type="button"
                            className="btn btn-primary btn-sm"
                            style={{ width: '100%' }}
                            onClick={() => setModalAction({ type: 'approve', item })}
                          >
                            🚀 Phê duyệt & Gửi
                          </button>
                        )}

                        {item.handoff_status === 'SENT_TELEGRAM' && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            style={{ width: '100%' }}
                            onClick={() => acknowledgeMutation.mutate(item.brief_id)}
                            title="Xác nhận người nhận đã đọc và tiếp nhận"
                          >
                            ✓ Đánh dấu đã tiếp nhận
                          </button>
                        )}

                        {item.handoff_status === 'SEND_FAILED' && (
                          <button
                            type="button"
                            className="btn btn-danger btn-sm"
                            style={{ width: '100%' }}
                            onClick={() => setModalAction({ type: 'retry', item })}
                          >
                            🔄 Thử gửi lại
                          </button>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>

      <style>{`
        @media (max-width: 1200px) {
          .handoff-board {
            display: flex !important;
            flex-direction: column !important;
          }
        }
      `}</style>
    </div>
  );
};
