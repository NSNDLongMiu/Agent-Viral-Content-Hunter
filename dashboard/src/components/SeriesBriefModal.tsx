import React from 'react';

interface SeriesBriefModalProps {
  seriesId: string | null;
  onClose: () => void;
}

export const SeriesBriefModal: React.FC<SeriesBriefModalProps> = ({ seriesId, onClose }) => {
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
        style={{ maxWidth: '560px' }}
      >
        <div className="modal-header">
          <h3 id="series-modal-title" style={{ margin: 0, fontSize: '16px' }}>
            🎬 Phim ngắn / Micro-Drama Series #{seriesId}
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
              tính năng <em>Series Brief / Phim ngắn tập</em> (thuộc phạm vi gói T4 - brief generation & series grouping).
              Dữ liệu chuỗi tập đang được lưu trữ trong cơ sở dữ liệu SQLite nhưng chưa có router
              công khai theo tài liệu <code>docs/openapi.json</code>.
            </div>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '12px' }}>
            Khi T4 hoàn thành các router quản lý series và danh sách các tập, thông tin cốt truyện,
            trạng thái bản quyền và các tập phim sẽ được tự động hiển thị tại đây.
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
