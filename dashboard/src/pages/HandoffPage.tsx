import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  getHandoffs,
  sendHandoff,
  checkAckHandoff,
  getInboxBriefs,
} from '../api/endpoints';
import { Handoff, HandoffStatus, ContentBrief } from '../api/types';
import { ApiError } from '../api/client';
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
    key: 'SENT',
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

  // Modals for sensitive outward-facing actions (handoff send, retry)
  const [modalAction, setModalAction] = useState<{
    type: 'send' | 'retry';
    item: Handoff;
  } | null>(null);

  const [notification, setNotification] = useState<string | null>(null);

  const {
    data: handoffs,
    isLoading: isHandoffsLoading,
    error: handoffsError,
    refetch,
  } = useQuery({
    queryKey: ['handoffs'],
    queryFn: () => getHandoffs(),
    refetchInterval: 10000,
  });

  const { data: inboxBriefs } = useQuery({
    queryKey: ['inboxBriefsForHandoff'],
    queryFn: () => getInboxBriefs({ limit: 200 }),
  });

  const briefsMap = React.useMemo(() => {
    const map = new Map<string, ContentBrief>();
    (inboxBriefs || []).forEach((b) => map.set(b.id, b));
    return map;
  }, [inboxBriefs]);

  const sendMutation = useMutation({
    mutationFn: (handoffId: string) => sendHandoff(handoffId),
    onSuccess: (updated) => {
      setModalAction(null);
      setNotification(`Đã gửi bàn giao hồ sơ #${updated.brief_id} sang Telegram.`);
      setTimeout(() => setNotification(null), 3500);
      queryClient.invalidateQueries({ queryKey: ['handoffs'] });
    },
    onError: (err: unknown) => {
      setModalAction(null);
      if (err instanceof ApiError && err.status === 501) {
        setNotification('Tính năng gửi Telegram đang chờ cài đặt adapter Telegram (501 Not Implemented - Gói T6).');
      } else {
        setNotification('Không thể gửi bàn giao qua Telegram. Vui lòng kiểm tra lại dịch vụ.');
      }
      setTimeout(() => setNotification(null), 5000);
    },
  });

  const acknowledgeMutation = useMutation({
    mutationFn: (handoffId: string) => checkAckHandoff(handoffId),
    onSuccess: (updated) => {
      setNotification(`Kiểm tra xác nhận hoàn tất: Trạng thái ${updated.status}`);
      setTimeout(() => setNotification(null), 3500);
      queryClient.invalidateQueries({ queryKey: ['handoffs'] });
    },
    onError: (err: unknown) => {
      if (err instanceof ApiError && err.status === 501) {
        setNotification('Chức năng kiểm tra xác nhận chưa có adapter Telegram (501 Not Implemented).');
      } else {
        setNotification('Chưa nhận được phản hồi tiếp nhận từ người nhận.');
      }
      setTimeout(() => setNotification(null), 4000);
    },
  });

  if (isHandoffsLoading) {
    return <LoadingState message="Đang tải bảng theo dõi bàn giao..." />;
  }

  if (handoffsError || !handoffs) {
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
          title={modalAction.type === 'send' ? 'Xác nhận gửi bàn giao' : 'Thử lại gửi Telegram'}
          message={
            modalAction.type === 'send'
              ? `Bạn có chắc chắn muốn gửi hồ sơ #${modalAction.item.brief_id} sang Telegram cho đội sản xuất?`
              : `Thử gửi lại tin hồ sơ #${modalAction.item.brief_id} sang Telegram?`
          }
          confirmText={modalAction.type === 'send' ? 'Gửi Telegram' : 'Thử lại'}
          isLoading={sendMutation.isPending}
          onConfirm={() => sendMutation.mutate(modalAction.item.id)}
          onCancel={() => setModalAction(null)}
        />
      )}

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>Bảng bàn giao (Handoff Board)</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '2px' }}>
            Phân biệt rõ ràng giữa "Đã gửi Telegram (SENT)" và "Đã xác nhận tiếp nhận (ACKNOWLEDGED)"
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
          const itemsInCol = handoffs.filter((h) => h.status === col.key);

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
                  itemsInCol.map((item) => {
                    const brief = briefsMap.get(item.brief_id);
                    const title = brief ? brief.title_vi : `Hồ sơ #${item.brief_id}`;
                    const platform = brief ? brief.platform : 'Chưa rõ';
                    const priority = brief ? brief.priority : 'P3';
                    const virality = brief ? brief.virality_score : null;

                    return (
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
                          <StatusBadge type="priority" value={priority} />
                          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{platform}</span>
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
                          {title}
                        </Link>

                        {virality !== null && (
                          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                            Điểm viral: <strong style={{ color: 'var(--danger-text)' }}>{virality}</strong>
                          </div>
                        )}

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
                        {item.last_error && (
                          <div style={{ fontSize: '11px', color: 'var(--danger-text)' }}>
                            ⚠️ {item.last_error}
                          </div>
                        )}

                        {/* Column-specific actions */}
                        <div style={{ marginTop: '4px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          {item.status === 'SELECTED' && (
                            <button
                              type="button"
                              className="btn btn-primary btn-sm"
                              style={{ width: '100%' }}
                              onClick={() => setModalAction({ type: 'send', item })}
                            >
                              🚀 Phê duyệt & Gửi
                            </button>
                          )}

                          {item.status === 'SENT' && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              style={{ width: '100%' }}
                              onClick={() => acknowledgeMutation.mutate(item.id)}
                              title="Kiểm tra xem người nhận đã bấm tiếp nhận hay chưa"
                            >
                              🔍 Kiểm tra tiếp nhận
                            </button>
                          )}

                          {item.status === 'SEND_FAILED' && (
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
                    );
                  })
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
