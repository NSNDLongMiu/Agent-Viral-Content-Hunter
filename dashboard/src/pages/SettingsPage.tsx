import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSettings, updateSettings } from '../api/endpoints';
import { SystemSettings } from '../api/types';
import { LoadingState } from '../components/LoadingState';
import { ErrorState } from '../components/ErrorState';
import { ConfirmModal } from '../components/ConfirmModal';

export const SettingsPage: React.FC = () => {
  const queryClient = useQueryClient();

  const [formData, setFormData] = useState<SystemSettings | null>(null);
  const [telegramTokenInput, setTelegramTokenInput] = useState<string>('');
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);

  const {
    data: settings,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['settings'],
    queryFn: getSettings,
  });

  useEffect(() => {
    if (settings) {
      setFormData(settings);
    }
  }, [settings]);

  const updateMutation = useMutation({
    mutationFn: (updated: Partial<SystemSettings>) => updateSettings(updated),
    onSuccess: () => {
      setConfirmOpen(false);
      setTelegramTokenInput(''); // Clear write-only field
      setSaveNotice('Đã lưu cấu hình hệ thống thành công!');
      setTimeout(() => setSaveNotice(null), 4000);
      queryClient.invalidateQueries({ queryKey: ['settings'] });
    },
    onError: () => {
      setConfirmOpen(false);
      setSaveNotice('Không thể lưu cài đặt. Vui lòng kiểm tra lại dịch vụ.');
      setTimeout(() => setSaveNotice(null), 5000);
    },
  });

  if (isLoading) {
    return <LoadingState message="Đang tải cấu hình hệ thống..." />;
  }

  if (error || !formData) {
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

    // Prepare payload, including write-only telegram token if provided
    const payload: Partial<SystemSettings> = {
      ...formData,
      telegram: {
        ...formData.telegram,
        ...(telegramTokenInput ? { bot_token: telegramTokenInput } : {}),
      },
    };

    // Budget policy is read-only by design (0 VND, no paid services): never send it back.
    delete payload.budget_policy;

    updateMutation.mutate(payload);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '1000px' }}>
      {/* Confirm Save Modal */}
      <ConfirmModal
        isOpen={confirmOpen}
        title="Xác nhận lưu thay đổi cài đặt"
        message="Bạn có chắc chắn muốn cập nhật các thông số vận hành của hệ thống?"
        confirmText="Lưu thay đổi"
        isLoading={updateMutation.isPending}
        onConfirm={handleSave}
        onCancel={() => setConfirmOpen(false)}
      />

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
            <strong>Quy tắc bất biến:</strong> {formData.budget_policy?.description || 'Hệ thống tuân thủ chính sách ngân sách phát sinh 0 VNĐ/tháng. Tuyệt đối không tự kích hoạt API trả phí theo token, proxy trả phí, captcha trả phí hoặc cloud VPS.'}
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
              value="Vô hiệu hóa vĩnh viễn"
              readOnly
              disabled
            />
          </div>
          <div>
            <label className="form-label">Chính sách khi hết Quota</label>
            <input
              type="text"
              className="form-control"
              value="Fail closed / Giảm tải chờ hồi phục"
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
            <div className="form-help">Mặc định: 85. Điểm từ ngưỡng này trở lên sẽ được xem xét thành P1.</div>
          </div>

          <div>
            <label className="form-label" htmlFor="retention-days">
              Thời gian lưu trữ hồ sơ (Retention)
            </label>
            <input
              id="retention-days"
              type="number"
              className="form-control"
              value={formData.retention_days}
              readOnly
              disabled
            />
            <div className="form-help">Mặc định 90 ngày (Cố định theo idead.md §18, tự động dọn dẹp sau 90 ngày).</div>
          </div>
        </div>
      </div>

      {/* 3. Scan Schedule (Adaptive Scheduler idead.md §5) */}
      <div className="card">
        <div className="card-header">
          <h3>Lịch quét dữ liệu (Adaptive Scheduler)</h3>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px' }}>
          <div>
            <label className="form-label">Tin nóng (Phút)</label>
            <input
              type="number"
              className="form-control"
              value={formData.scan_schedule.breaking_news_interval_minutes}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  scan_schedule: {
                    ...formData.scan_schedule,
                    breaking_news_interval_minutes: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Đề xuất: 5–10 phút</div>
          </div>

          <div>
            <label className="form-label">Trending / Hashtag (Phút)</label>
            <input
              type="number"
              className="form-control"
              value={formData.scan_schedule.trending_interval_minutes}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  scan_schedule: {
                    ...formData.scan_schedule,
                    trending_interval_minutes: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Đề xuất: 15–30 phút</div>
          </div>

          <div>
            <label className="form-label">Creator ưu tiên (Phút)</label>
            <input
              type="number"
              className="form-control"
              value={formData.scan_schedule.priority_creator_interval_minutes}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  scan_schedule: {
                    ...formData.scan_schedule,
                    priority_creator_interval_minutes: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Đề xuất: 30–60 phút</div>
          </div>

          <div>
            <label className="form-label">Nguồn thông thường (Giờ)</label>
            <input
              type="number"
              className="form-control"
              value={formData.scan_schedule.normal_interval_hours}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  scan_schedule: {
                    ...formData.scan_schedule,
                    normal_interval_hours: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Đề xuất: 2–4 giờ</div>
          </div>
        </div>
      </div>

      {/* 4. Telegram Integration (WRITE-ONLY TOKEN per spec) */}
      <div className="card">
        <div className="card-header">
          <h3>Tích hợp Telegram (Cảnh báo P1 & Bàn giao)</h3>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div className="grid-2">
            <div>
              <label className="form-label" htmlFor="telegram-token">
                Bot Token (Write-only / Chỉ ghi)
              </label>
              <input
                id="telegram-token"
                type="password"
                className="form-control"
                placeholder={
                  formData.telegram.configured
                    ? '•••••••••••••••• (Đã cấu hình, nhập mới để đổi)'
                    : 'Nhập Telegram Bot Token...'
                }
                value={telegramTokenInput}
                onChange={(e) => setTelegramTokenInput(e.target.value)}
                autoComplete="new-password"
              />
              <div className="form-help">
                Vì an toàn bảo mật, hệ thống không bao giờ hiển thị lại token sau khi lưu.
              </div>
            </div>

            <div>
              <label className="form-label" htmlFor="telegram-chat-id">
                Telegram Chat ID / Channel ID
              </label>
              <input
                id="telegram-chat-id"
                type="text"
                className="form-control"
                placeholder="@my_channel hoặc -100123456789"
                value={formData.telegram.chat_id}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    telegram: {
                      ...formData.telegram,
                      chat_id: e.target.value,
                    },
                  })
                }
              />
            </div>
          </div>

          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={formData.telegram.alert_p1_enabled}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    telegram: {
                      ...formData.telegram,
                      alert_p1_enabled: e.target.checked,
                    },
                  })
                }
              />
              <span>Tự động phát cảnh báo P1 qua Telegram</span>
            </label>

            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={formData.telegram.handoff_enabled}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    telegram: {
                      ...formData.telegram,
                      handoff_enabled: e.target.checked,
                    },
                  })
                }
              />
              <span>Cho phép bàn giao nội dung sang đội sản xuất qua Telegram</span>
            </label>
          </div>
        </div>
      </div>

      {/* 5. Job Concurrency Limits (idead.md §7) */}
      <div className="card">
        <div className="card-header">
          <h3>Giới hạn tác vụ đồng thời (Job Limits)</h3>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '14px' }}>
          <div>
            <label className="form-label">Claude Leader</label>
            <input
              type="number"
              className="form-control"
              value={formData.job_limits.claude_sessions}
              readOnly
              disabled
            />
            <div className="form-help">Cố định: 1 phiên</div>
          </div>

          <div>
            <label className="form-label">Codex Max Jobs</label>
            <input
              type="number"
              className="form-control"
              value={formData.job_limits.codex_max_concurrency}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  job_limits: {
                    ...formData.job_limits,
                    codex_max_concurrency: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Mặc định: 2 jobs</div>
          </div>

          <div>
            <label className="form-label">Gemini Max Jobs</label>
            <input
              type="number"
              className="form-control"
              value={formData.job_limits.gemini_max_concurrency}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  job_limits: {
                    ...formData.job_limits,
                    gemini_max_concurrency: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Mặc định: 2 jobs</div>
          </div>

          <div>
            <label className="form-label">Collector Nguồn</label>
            <input
              type="number"
              className="form-control"
              value={formData.job_limits.collector_max_concurrency}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  job_limits: {
                    ...formData.job_limits,
                    collector_max_concurrency: Number(e.target.value),
                  },
                })
              }
            />
            <div className="form-help">Số nguồn quét song song</div>
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
