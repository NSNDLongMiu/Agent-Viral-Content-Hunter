import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getOverviewStats } from '../api/endpoints';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';
import { Link } from 'react-router-dom';

export const OverviewPage: React.FC = () => {
  const { data: stats, isLoading, error, refetch } = useQuery({
    queryKey: ['overviewStats'],
    queryFn: getOverviewStats,
    refetchInterval: 15000, // Auto-refresh overview every 15s
  });

  if (isLoading) {
    return <LoadingState message="Đang tải dữ liệu tổng quan hệ thống..." />;
  }

  if (error || !stats) {
    return (
      <ErrorState
        title="Không thể tải tổng quan"
        message="Không thể kết nối đến API tổng quan hoặc dịch vụ backend chưa sẵn sàng."
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Page Title */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>Tổng quan hệ thống</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '2px' }}>
            Theo dõi trạng thái thu thập, kiểm duyệt và điều phối AI
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => refetch()}>
          🔄 Làm mới
        </button>
      </div>

      {/* 1. Metric Counts Cards */}
      <div className="grid-4">
        <div className="card">
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>TIN MỚI THU THẬP</div>
          <div style={{ fontSize: '28px', fontWeight: 700, margin: '8px 0', color: 'var(--text-primary)' }}>
            {stats.new_items_count}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Trong chu kỳ quét gần nhất</div>
        </div>

        <div className="card" style={{ borderLeft: '4px solid var(--danger)' }}>
          <div style={{ fontSize: '12px', color: 'var(--danger-text)', fontWeight: 600 }}>ỨNG VIÊN P1</div>
          <div style={{ fontSize: '28px', fontWeight: 700, margin: '8px 0', color: 'var(--danger-text)' }}>
            {stats.p1_candidates_count}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Điểm ≥ 85, ưu tiên cao</div>
        </div>

        <div className="card" style={{ borderLeft: '4px solid var(--warning)' }}>
          <div style={{ fontSize: '12px', color: 'var(--warning-text)', fontWeight: 600 }}>CHỜ CLAUDE DUYỆT</div>
          <div style={{ fontSize: '28px', fontWeight: 700, margin: '8px 0', color: 'var(--warning-text)' }}>
            {stats.waiting_claude_count}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Hồ sơ đang đợi kiểm duyệt</div>
        </div>

        <div className="card" style={{ borderLeft: '4px solid var(--success)' }}>
          <div style={{ fontSize: '12px', color: 'var(--success-text)', fontWeight: 600 }}>ĐÃ DUYỆT / BÀN GIAO</div>
          <div style={{ fontSize: '28px', fontWeight: 700, margin: '8px 0', color: 'var(--success-text)' }}>
            {stats.approved_count} <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>/ {stats.handed_off_count} đã gửi</span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            <Link to="/inbox">Xem Discovery Inbox →</Link>
          </div>
        </div>
      </div>

      {/* 2. Middle Row: Sources & AI Workers & Queue Health */}
      <div className="grid-3">
        {/* Source Status Summary */}
        <div className="card">
          <div className="card-header">
            <h3>Nguồn dữ liệu</h3>
            <Link to="/sources" className="btn btn-secondary btn-sm">Quản lý</Link>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Tổng số nguồn:</span>
              <strong>{stats.source_status_summary.total}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Đang hoạt động:</span>
              <span className="badge badge-success">{stats.source_status_summary.active}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Cảnh báo:</span>
              <span className="badge badge-warning">{stats.source_status_summary.warning}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Lỗi kết nối:</span>
              <span className="badge badge-danger">{stats.source_status_summary.error}</span>
            </div>
          </div>
        </div>

        {/* AI Worker Status */}
        <div className="card">
          <div className="card-header">
            <h3>Trạng thái AI Workers</h3>
            <Link to="/monitor" className="btn btn-secondary btn-sm">Chi tiết</Link>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Claude (Leader):</span>
              <StatusBadge type="ai" value={stats.ai_status_summary.claude} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Codex (Data Worker):</span>
              <StatusBadge type="ai" value={stats.ai_status_summary.codex} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Gemini (Research Worker):</span>
              <StatusBadge type="ai" value={stats.ai_status_summary.gemini} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Local AI (Lọc nhẹ):</span>
              <StatusBadge type="ai" value={stats.ai_status_summary.local} />
            </div>
          </div>
        </div>

        {/* Queue Health */}
        <div className="card">
          <div className="card-header">
            <h3>Tình trạng hàng đợi</h3>
            <span
              className={`badge ${
                stats.queue_health.status === 'healthy'
                  ? 'badge-success'
                  : stats.queue_health.status === 'congested'
                  ? 'badge-warning'
                  : 'badge-danger'
              }`}
            >
              {stats.queue_health.status === 'healthy'
                ? 'Ổn định'
                : stats.queue_health.status === 'congested'
                ? 'Tắc nghẽn nhẹ'
                : 'Ngừng trệ'}
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Urgent Queue (Tin nóng / P1):</span>
                <strong>{stats.queue_health.urgent} jobs</strong>
              </div>
              <div style={{ height: '6px', backgroundColor: 'var(--bg-subtle)', borderRadius: '3px', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.min(100, stats.queue_health.urgent * 10)}%`,
                    backgroundColor: 'var(--danger)',
                  }}
                />
              </div>
            </div>

            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '4px' }}>
                <span style={{ color: 'var(--text-secondary)' }}>Normal Queue (P2 / P3):</span>
                <strong>{stats.queue_health.normal} jobs</strong>
              </div>
              <div style={{ height: '6px', backgroundColor: 'var(--bg-subtle)', borderRadius: '3px', overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.min(100, stats.queue_health.normal * 5)}%`,
                    backgroundColor: 'var(--primary)',
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Recent Errors Table */}
      <div className="card">
        <div className="card-header">
          <h3>Lỗi gần đây trong hệ thống</h3>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {stats.recent_errors.length} sự cố ghi nhận
          </span>
        </div>

        {stats.recent_errors.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', margin: '8px 0' }}>
            Không có lỗi nào phát sinh gần đây. Hệ thống đang vận hành ổn định.
          </p>
        ) : (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '160px' }}>Thời gian</th>
                  <th style={{ width: '120px' }}>Tác nhân / Worker</th>
                  <th>Nội dung lỗi</th>
                  <th style={{ width: '80px', textAlign: 'center' }}>Số lần thử</th>
                </tr>
              </thead>
              <tbody>
                {stats.recent_errors.map((err) => (
                  <tr key={err.id}>
                    <td style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
                      {new Date(err.timestamp).toLocaleTimeString('vi-VN')} {new Date(err.timestamp).toLocaleDateString('vi-VN')}
                    </td>
                    <td>
                      <span className="badge badge-p3">{err.worker || 'Hệ thống'}</span>
                    </td>
                    <td style={{ color: 'var(--danger-text)', fontFamily: 'var(--font-mono)', fontSize: '12px' }}>
                      {err.error}
                    </td>
                    <td style={{ textAlign: 'center' }}>{err.retry_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
