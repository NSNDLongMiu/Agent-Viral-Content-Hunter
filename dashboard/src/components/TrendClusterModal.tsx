import React from 'react';

interface TrendClusterModalProps {
  clusterId: string | null;
  onClose: () => void;
}

export const TrendClusterModal: React.FC<TrendClusterModalProps> = ({ clusterId, onClose }) => {
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
        style={{ maxWidth: '560px' }}
      >
        <div className="modal-header">
          <h3 id="cluster-modal-title" style={{ margin: 0, fontSize: '16px' }}>
            🔥 Cụm xu hướng (Trend Cluster) #{clusterId}
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
          <div className="notice-box notice-warning" style={{ margin: '8px 0' }}>
            <span>ℹ️</span>
            <div>
              <strong>Chưa hỗ trợ API:</strong> Hiện tại backend chưa xuất bản endpoint API cho
              tính năng <em>Trend Cluster</em> (thuộc phạm vi gói T4 - brief generation & clustering).
              Dữ liệu cụm xu hướng đang được xử lý trong cơ sở dữ liệu SQLite nhưng chưa có router
              công khai theo tài liệu <code>docs/openapi.json</code>.
            </div>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '12px' }}>
            Khi T4 hoàn thành các router nhóm cụm và liên kết hồ sơ, chi tiết các nguồn tin cậy
            cùng các bài viết liên quan sẽ được tự động kết nối và hiển thị tại đây.
          </p>
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
