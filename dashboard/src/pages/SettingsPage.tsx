import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  getSettings,
  updateSettings,
  getSettingsAudit,
  undoSettingsChange,
} from '../api/endpoints';
import { DashboardSettings, AuditRecord } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { ConfirmModal } from '../components/ConfirmModal';

export const SettingsPage: React.FC = () => {
  const queryClient = useQueryClient();

  const [formData, setFormData] = useState<DashboardSettings | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);
  const [undoRecord, setUndoRecord] = useState<AuditRecord | null>(null);

  const {
    data: settings,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  });

  const { data: auditLog } = useQuery({
    queryKey: ['settingsAudit'],
    queryFn: () => getSettingsAudit({ limit: 10 }),
  });

  useEffect(() => {
    if (settings) {
      setFormData(settings.preferences);
    }
  }, [settings]);

  const updateMutation = useMutation({
    mutationFn: (prefs: DashboardSettings) =>
      updateSettings(prefs, 'Cập nhật cấu hình dashboard qua giao diện quản trị'),
    onSuccess: () => {
      setConfirmOpen(false);
      setSaveNotice('Đã lưu cấu hình hệ thống thành công!');
      setTimeout(() => setSaveNotice(null), 4000);
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['settingsAudit'] });
    },
    onError: () => {
      setConfirmOpen(false);
      setSaveNotice('Không thể lưu cài đặt. Vui lòng kiểm tra lại dịch vụ.');
      setTimeout(() => setSaveNotice(null), 5000);
    },
  });

  const undoMutation = useMutation({
    mutationFn: (recordId: number) =>
      undoSettingsChange(recordId, 'Hoàn tác thay đổi qua giao diện quản trị'),
    onSuccess: () => {
      setUndoRecord(null);
      setSaveNotice('Đã hoàn tác thay đổi thành công!');
      setTimeout(() => setSaveNotice(null), 4000);
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['settingsAudit'] });
    },
    onError: () => {
      setUndoRecord(null);
      setSaveNotice('Không thể hoàn tác thay đổi này.');
      setTimeout(() => setSaveNotice(null), 4000);
    },
  });

  if (isLoading) {
    return <LoadingState message="Đang tải cấu hình hệ thống..." />;
  }

  if (error || !formData || !settings) {
    return (
      <ErrorState
        title="Không thể tải cài đặt"
        message="Không thể kết nối đến máy chủ hoặc dịch vụ cấu hình."
        onRetry={() => refetch()}
      />
    );
  }

  const handleSave = () => {
    if (!formData) return;
    updateMutation.mutate(formData);
  };

  const scanIntervals = formData.scan_intervals_minutes || {};

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '1000px' }}>
      {/* Confirm Save Modal */}
      <ConfirmModal
        isOpen={confirmOpen}
        title="Xác nhận lưu thay đổi cài đặt"
        message="Bạn có chắc chắn muốn cập nhật các tùy chọn vận hành của hệ thống?"
        confirmText="Lưu thay đổi"
        isLoading={updateMutation.isPending}
        onConfirm={handleSave}
        onCancel={() => setConfirmOpen(false)}
      />

      {/* Confirm Undo Modal */}
      {undoRecord && (
        <ConfirmModal
          isOpen={true}
          title="Xác nhận hoàn tác thay đổi"
          message={`Bạn có chắc muốn hoàn tác thay đổi #${undoRecord.id} (${undoRecord.entity_key}: ${undoRecord.action})?`}
          confirmText="Hoàn tác ngay"
          confirmVariant="danger"
          isLoading={undoMutation.isPending}
          onConfirm={() => undoMutation.mutate(undoRecord.id)}
          onCancel={() => setUndoRecord(null)}
        />
      )}

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>Cài đặt hệ thống (Settings)</h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '13px', marginTop: '2px' }}>
            Cấu hình ngưỡng P1, lịch quét, giới hạn tác vụ và chính sách ngân sách 0đ
          </p>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setConfirmOpen(true)}
          disabled={updateMutation.isPending}
        >
          💾 Lưu cài đặt
        </button>
      </div>

      {saveNotice && (
        <div className="notice-box notice-info" role="status">
          <span>ℹ️</span>
          <div>{saveNotice}</div>
        </div>
      )}

      {/* 1. BUDGET POLICY (READ-ONLY: 0 VND BUDGET, NO PAID SERVICES PER idead.md §17) */}
      <div className="card" style={{ borderLeft: '4px solid var(--success)' }}>
        <div className="card-header">
          <h3 style={{ color: 'var(--success-text)' }}>Chính sách ngân sách (0 VNĐ / Tháng)</h3>
          <span className="badge badge-success">CHỈ ĐỌC (READ-ONLY)</span>
        </div>
        <div className="notice-box notice-info" style={{ marginBottom: '12px' }}>
          <span>ℹ️</span>
          <div>
            <strong>Quy tắc bất biến:</strong> Hệ thống tuân thủ nghiêm ngặt chính sách ngân sách phát sinh 0 VNĐ/tháng.
            Giá trị <code>budget.allow_paid_api</code> luôn khóa ở mức <code>false</code>. Tuyệt đối không sử dụng API trả phí
            theo lượt, proxy trả phí, dịch vụ giải mã captcha hay máy chủ đám mây tính phí.
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
          <div>
            <label className="form-label">Ngân sách hàng tháng</label>
            <input
              type="text"
              className="form-control"
              value="0 VNĐ / tháng"
              readOnly
              disabled
            />
          </div>
          <div>
            <label className="form-label">Dịch vụ API trả phí (Paid APIs)</label>
            <input
              type="text"
              className="form-control"
              value={settings.budget.allow_paid_api ? 'Đang bật' : 'Vô hiệu hóa vĩnh viễn (false)'}
              readOnly
              disabled
            />
          </div>
          <div>
            <label className="form-label">Chính sách khi hết Quota</label>
            <input
              type="text"
              className="form-control"
              value="Fail closed / Chờ hạn ngạch tự nhiên"
              readOnly
              disabled
            />
          </div>
        </div>
      </div>

      {/* 2. P1 Threshold & Retention */}
      <div className="card">
        <div className="card-header">
          <h3>Ngưỡng chấm điểm P1 & Chính sách lưu trữ</h3>
        </div>
        <div className="grid-2">
          <div>
            <label className="form-label" htmlFor="p1-threshold">
              Ngưỡng điểm ứng viên P1 (0 - 100)
            </label>
            <input
              id="p1-threshold"
              type="number"
              min="1"
              max="100"
              className="form-control"
              value={formData.p1_threshold}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  p1_threshold: Number(e.target.value),
                })
              }
            />
            <div className="form-help">Mặc định: 85. Điểm từ ngưỡng này trở lên sẽ được đưa vào diện ưu tiên cao.</div>
          </div>

          <div>
            <label className="form-label" htmlFor="retention-days">
              Thời gian lưu trữ hồ sơ (Retention)
            </label>
            <input
              id="retention-days"
              type="number"
              className="form-control"
              value={settings.retention.days}
              readOnly
              disabled
            />
            <div className="form-help">Cấu hình khởi động: {settings.retention.days} ngày (Cố định theo idead.md §18, tự động thanh lọc).</div>
          </div>
        </div>
      </div>

      {/* 3. Scan Schedule (Adaptive Scheduler) */}
      <div className="card">
        <div className="card-header">
          <h3>Chu kỳ quét nguồn (Phút)</h3>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px' }}>
          <div>
            <label className="form-label">Tin nóng (breaking_news)</label>
            <input
              type="number"
              min="1"
              className="form-control"
              value={scanIntervals['breaking_news'] || 10}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  scan_intervals_minutes: {
                    ...scanIntervals,
                    breaking_news: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Đề xuất: 5–15 phút</div>
          </div>

          <div>
            <label className="form-label">Xu hướng (trending)</label>
            <input
              type="number"
              min="1"
              className="form-control"
              value={scanIntervals['trending'] || 30}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  scan_intervals_minutes: {
                    ...scanIntervals,
                    trending: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Đề xuất: 15–60 phút</div>
          </div>

          <div>
            <label className="form-label">Kênh ưu tiên (priority_creator)</label>
            <input
              type="number"
              min="1"
              className="form-control"
              value={scanIntervals['priority_creator'] || 60}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  scan_intervals_minutes: {
                    ...scanIntervals,
                    priority_creator: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Đề xuất: 30–120 phút</div>
          </div>
        </div>
      </div>

      {/* 4. Telegram Integration */}
      <div className="card">
        <div className="card-header">
          <h3>Tích hợp Telegram (Cảnh báo P1 & Bàn giao)</h3>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div className="notice-box notice-info">
            <span>🔒</span>
            <div>
              <strong>Bảo mật Bot Token:</strong> Token Telegram và Chat ID được cấp qua biến môi trường
              (<code>HUNTER_TELEGRAM__BOT_TOKEN</code>) khi khởi động hệ thống và không bao giờ lưu trữ
              trong bảng tùy chọn cơ sở dữ liệu. Bảng điều khiển chỉ cho phép bật/tắt kích hoạt tính năng.
            </div>
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={formData.telegram_enabled}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  telegram_enabled: e.target.checked,
                })
              }
            />
            <span style={{ fontWeight: 600 }}>Kích hoạt tính năng thông báo và bàn giao qua Telegram</span>
          </label>
        </div>
      </div>

      {/* 5. Job Concurrency Limits (Startup Queue Limits - Read Only) */}
      <div className="card">
        <div className="card-header">
          <h3>Giới hạn hàng đợi & tác vụ đồng thời (Startup Queue Limits)</h3>
          <span className="badge badge-p3">CHỈ ĐỌC</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '14px' }}>
          <div>
            <label className="form-label">Claude Leader</label>
            <input
              type="number"
              className="form-control"
              value={settings.queue.claude}
              readOnly
              disabled
            />
            <div className="form-help">Cố định: 1 phiên</div>
          </div>

          <div>
            <label className="form-label">Codex Concurrency</label>
            <input
              type="number"
              className="form-control"
              value={settings.queue.codex}
              readOnly
              disabled
            />
            <div className="form-help">Giới hạn máy: {settings.queue.codex} jobs</div>
          </div>

          <div>
            <label className="form-label">Gemini Concurrency</label>
            <input
              type="number"
              className="form-control"
              value={settings.queue.gemini}
              readOnly
              disabled
            />
            <div className="form-help">Giới hạn máy: {settings.queue.gemini} jobs</div>
          </div>

          <div>
            <label className="form-label">Collector Concurrency</label>
            <input
              type="number"
              className="form-control"
              value={settings.queue.collector}
              readOnly
              disabled
            />
            <div className="form-help">Số nguồn song song</div>
          </div>
        </div>
      </div>

      {/* 6. Topics and Exclusions */}
      <div className="card">
        <div className="card-header">
          <h3>Chủ đề ưu tiên & Chủ đề loại trừ</h3>
        </div>
        <div className="grid-2">
          <div>
            <label className="form-label" htmlFor="priority-topics">
              Chủ đề ưu tiên (Phân tách bằng dấu phẩy)
            </label>
            <textarea
              id="priority-topics"
              className="form-control"
              value={formData.priority_topics.join(', ')}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  priority_topics: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              rows={3}
            />
          </div>

          <div>
            <label className="form-label" htmlFor="excluded-topics">
              Chủ đề loại trừ (Phân tách bằng dấu phẩy)
            </label>
            <textarea
              id="excluded-topics"
              className="form-control"
              value={formData.excluded_topics.join(', ')}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  excluded_topics: e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean),
                })
              }
              rows={3}
            />
          </div>
        </div>
      </div>

      {/* 7. Settings Audit Log */}
      {auditLog && auditLog.length > 0 && (
        <div className="card">
          <div className="card-header">
            <h3>Nhật ký thay đổi cài đặt (Audit Log)</h3>
            <span className="badge badge-info">{auditLog.length} thay đổi gần nhất</span>
          </div>
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Thời gian</th>
                  <th>Khóa</th>
                  <th>Thao tác</th>
                  <th>Tác nhân</th>
                  <th>Lý do</th>
                  <th style={{ textAlign: 'right' }}>Hoàn tác</th>
                </tr>
              </thead>
              <tbody>
                {auditLog.map((record) => (
                  <tr key={record.id}>
                    <td style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                      {new Date(record.created_at).toLocaleString('vi-VN')}
                    </td>
                    <td><code>{record.entity_key}</code></td>
                    <td><span className="badge badge-p3">{record.action}</span></td>
                    <td>{record.actor}</td>
                    <td style={{ fontSize: '12px' }}>{record.reason}</td>
                    <td style={{ textAlign: 'right' }}>
                      <button
                        type="button"
                        className="btn btn-outline-danger btn-sm"
                        style={{ padding: '2px 8px', fontSize: '11px' }}
                        onClick={() => setUndoRecord(record)}
                      >
                        ↩ Hoàn tác
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Save Button Bottom */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '24px' }}>
        <button
          type="button"
          className="btn btn-primary btn-lg"
          onClick={() => setConfirmOpen(true)}
          disabled={updateMutation.isPending}
        >
          {updateMutation.isPending ? 'Đang lưu...' : '💾 Lưu tất cả thay đổi'}
        </button>
      </div>
    </div>
  );
};
