import React from 'react';

interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Đã có lỗi xảy ra',
  message = 'Không thể tải dữ liệu từ API. Vui lòng kiểm tra trạng thái máy chủ backend.',
  onRetry,
}) => {
  return (
    <div
      role="alert"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '36px 20px',
        textAlign: 'center',
        backgroundColor: 'var(--danger-subtle)',
        border: '1px solid var(--danger)',
        borderRadius: 'var(--radius-lg)',
        color: 'var(--danger-text)',
        margin: '16px 0',
      }}
    >
      <div style={{ fontSize: '32px', marginBottom: '8px' }}>⚠️</div>
      <h3 style={{ fontSize: '15px', fontWeight: 600, marginBottom: '6px' }}>{title}</h3>
      <p style={{ fontSize: '13px', maxWidth: '480px', marginBottom: onRetry ? '14px' : '0' }}>
        {message}
      </p>
      {onRetry && (
        <button type="button" className="btn btn-danger btn-sm" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  );
};
