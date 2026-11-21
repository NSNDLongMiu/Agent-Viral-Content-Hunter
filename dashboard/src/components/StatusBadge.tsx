import React from 'react';
import {
  PriorityLevel,
  ReviewStatus,
  HandoffStatus,
  AIWorkerStatus,
  ConnectorStatus,
} from '../api/types';

interface StatusBadgeProps {
  type: 'priority' | 'review' | 'handoff' | 'ai' | 'connector';
  value: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ type, value }) => {
  if (type === 'priority') {
    const priority = value as PriorityLevel;
    let badgeClass = 'badge-p3';
    if (priority === 'P1') badgeClass = 'badge-p1';
    else if (priority === 'P2') badgeClass = 'badge-p2';

    return <span className={`badge ${badgeClass}`}>{priority || 'P3'}</span>;
  }

  if (type === 'review') {
    const status = value as ReviewStatus;
    switch (status) {
      case 'APPROVED_BY_CLAUDE':
        return <span className="badge badge-success">Claude đã duyệt</span>;
      case 'PENDING_CLAUDE_REVIEW':
        return <span className="badge badge-warning">Chờ Claude duyệt</span>;
      case 'REVISION_REQUIRED':
        return <span className="badge badge-warning">Yêu cầu sửa</span>;
      case 'REJECTED_BY_CLAUDE':
        return <span className="badge badge-danger">Claude từ chối</span>;
      case 'REVIEW_FAILED':
        return <span className="badge badge-danger">Duyệt thất bại (hết lượt)</span>;
      case 'PROCESSING':
        return <span className="badge badge-info">Đang xử lý</span>;
      case 'PREPROCESSED':
        return <span className="badge badge-info">Tiền xử lý</span>;
      case 'COLLECTED':
      default:
        return <span className="badge badge-p3">Đã thu thập</span>;
    }
  }

  if (type === 'handoff') {
    const status = value as HandoffStatus;
    switch (status) {
      case 'ACKNOWLEDGED':
        return <span className="badge badge-success">Đã xác nhận tiếp nhận</span>;
      case 'SENT_TELEGRAM':
        return <span className="badge badge-info">Đã gửi Telegram</span>;
      case 'SELECTED':
        return <span className="badge badge-purple">Đã chọn bàn giao</span>;
      case 'SEND_FAILED':
        return <span className="badge badge-danger">Gửi thất bại</span>;
      case 'NOT_HANDED_OFF':
      default:
        return <span className="badge badge-p3">Chưa bàn giao</span>;
    }
  }

  if (type === 'ai') {
    const status = value as AIWorkerStatus;
    switch (status) {
      case 'ONLINE':
        return <span className="badge badge-success">Sẵn sàng</span>;
      case 'RATE_LIMITED':
        return <span className="badge badge-warning">Hết quota (chờ)</span>;
      case 'DEGRADED':
        return <span className="badge badge-warning">Giảm tải</span>;
      case 'OFFLINE':
      default:
        return <span className="badge badge-danger">Ngoại tuyến</span>;
    }
  }

  if (type === 'connector') {
    const status = value as ConnectorStatus;
    switch (status) {
      case 'HEALTHY':
        return <span className="badge badge-success">Bình thường</span>;
      case 'WARNING':
        return <span className="badge badge-warning">Cảnh báo</span>;
      case 'ERROR':
        return <span className="badge badge-danger">Lỗi kết nối</span>;
      case 'OFFLINE':
      default:
        return <span className="badge badge-p3">Tạm dừng</span>;
    }
  }

  return <span className="badge badge-p3">{value}</span>;
};
