import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getMonitorStatus } from '../api/endpoints';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { StatusBadge } from '../components/StatusBadge';

export const MonitorPage: React.FC = () => {
  const { data: monitor, isLoading, error, refetch } = useQuery({
    queryKey: ['systemMonitor'],
    queryFn: getMonitorStatus,
    refetchInterval: 8000, // Poll monitor every 8s
  });

  if (isLoading) {
    return <LoadingState message="Đang tải dữ liệu giám sát AI & hệ thống..." />;
  }

  if (error || !monitor) {
    return (
      <ErrorState
        title="Không thể tải thông tin giám sát"
        message="Không thể kết nối tới dịch vụ điều phối (Orchestrator)."
        onRetry={() => refetch()}
      />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>Giám sát AI & Hệ thống (System Monitor)</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '2px' }}>
            Theo dõi trạng thái Claude/Codex/Gemini/Local AI, hàng đợi và xử lý lỗi
          </p>
        </div>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => refetch()}>
          🔄 Làm mới dữ liệu
        </button>
      </div>

      {/* 1. AI Workers Status Grid */}
      <div>
        <h2 style={{ fontSize: '16px', marginBottom: '12px' }}>Trạng thái các Agent / Workers</h2>
        <div className="grid-4">
          {monitor.ai_workers.map((worker) => (
            <div key={worker.name} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ fontSize: '14px' }}>{worker.name}</strong>
                <StatusBadge type="ai" value={worker.status} />
              </div>

              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                Công việc đang chạy: <strong>{worker.active_jobs}</strong> / {worker.max_jobs} max
              </div>

              <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Tình trạng Quota: <span style={{ color: 'var(--text-primary)' }}>{worker.quota_status}</span>
              </div>

              <div style={{ fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid var(--border-subtle)', paddingTop: '6px' }}>
                Heartbeat: {worker.last_heartbeat ? new Date(worker.last_heartbeat).toLocaleTimeString('vi-VN') : 'N/A'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 2. Queues & System Counters */}
      <div className="grid-3">
        {/* Urgent Queue */}
        <div className="card" style={{ borderLeft: '4px solid var(--danger)' }}>
          <div style={{ fontSize: '12px', color: 'var(--danger-text)', fontWeight: 600 }}>URGENT QUEUE</div>
          <div style={{ fontSize: '28px', fontWeight: 700, margin: '8px 0', color: 'var(--danger-text)' }}>
            {monitor.queues.urgent}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Tin nóng, ứng viên P1 & Emerging Viral
          </div>
        </div>

        {/* Normal Queue */}
        <div className="card" style={{ borderLeft: '4px solid var(--primary)' }}>
          <div style={{ fontSize: '12px', color: 'var(--primary-text)', fontWeight: 600 }}>NORMAL QUEUE</div>
          <div style={{ fontSize: '28px', fontWeight: 700, margin: '8px 0', color: 'var(--primary-text)' }}>
            {monitor.queues.normal}
          </div>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            P2/P3, nghiên cứu & quét định kỳ
          </div>
        </div>

        {/* System Error Metrics */}
        <div className="card">
          <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontWeight: 600 }}>CHỈ SỐ SỰ CỐ</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginTop: '10px', fontSize: '13px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Timeouts:</span>
              <strong style={{ color: monitor.timeouts_count > 0 ? 'var(--warning-text)' : 'inherit' }}>
                {monitor.timeouts_count}
              </strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Số lần thử lại (Retries):</span>
              <strong>{monitor.retries_count}</strong>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Lỗi hạn ngạch (Quota):</span>
              <strong style={{ color: monitor.quota_errors_count > 0 ? 'var(--danger-text)' : 'inherit' }}>
                {monitor.quota_errors_count}
              </strong>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Running Jobs Table */}
      <div className="card">
        <div className="card-header">
          <h3>Tiến trình đang thực thi ({monitor.running_jobs.length})</h3>
        </div>

        {monitor.running_jobs.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', margin: '8px 0' }}>
            Hiện tại không có job nào đang chạy.
          </p>
        ) : (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Worker</th>
                  <th>Hàng đợi</th>
                  <th>Loại nhiệm vụ</th>
                  <th>Bắt đầu lúc</th>
                  <th style={{ textAlign: 'center' }}>Số lần thử</th>
                </tr>
              </thead>
              <tbody>
                {monitor.running_jobs.map((job) => (
                  <tr key={job.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>{job.id}</td>
                    <td><span className="badge badge-info">{job.worker}</span></td>
                    <td><span className="badge badge-p3">{job.queue}</span></td>
                    <td>{job.kind}</td>
                    <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      {new Date(job.created_at).toLocaleTimeString('vi-VN')}
                    </td>
                    <td style={{ textAlign: 'center' }}>{job.attempt_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 4. Dead-Letter Jobs Table */}
      <div className="card">
        <div className="card-header">
          <h3 style={{ color: 'var(--danger-text)' }}>Hàng đợi lỗi (Dead-Letter Jobs)</h3>
          <span className="badge badge-danger">{monitor.dead_letter_jobs.length} jobs</span>
        </div>

        {monitor.dead_letter_jobs.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', margin: '8px 0' }}>
            Không có job nào bị chuyển sang hàng đợi lỗi.
          </p>
        ) : (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Worker</th>
                  <th>Loại nhiệm vụ</th>
                  <th>Nguyên nhân lỗi</th>
                  <th>Thời điểm dừng</th>
                  <th style={{ textAlign: 'center' }}>Tổng lần thử</th>
                </tr>
              </thead>
              <tbody>
                {monitor.dead_letter_jobs.map((job) => (
                  <tr key={job.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '12px' }}>{job.id}</td>
                    <td><span className="badge badge-info">{job.worker}</span></td>
                    <td>{job.kind}</td>
                    <td style={{ color: 'var(--danger-text)', fontSize: '12px' }}>
                      {job.last_error || 'POLICY_BLOCKED hoặc vượt quá số lần thử lại'}
                    </td>
                    <td style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                      {new Date(job.updated_at).toLocaleString('vi-VN')}
                    </td>
                    <td style={{ textAlign: 'center' }}>{job.attempt_count}</td>
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
