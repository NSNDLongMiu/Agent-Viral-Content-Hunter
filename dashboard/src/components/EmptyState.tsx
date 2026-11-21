import React from 'react';

interface EmptyStateProps {
  title?: string;
  message?: string;
  actionText?: string;
  onAction?: () => void;
  icon?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  title = 'Không có dữ liệu',
  message = 'Chưa có thông tin hoặc bản ghi nào phù hợp.',
  actionText,
  onAction,
  icon = '📭',
}) => {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48px 24px',
        textAlign: 'center',
        backgroundColor: 'var(--bg-surface)',
        border: '1px dashed var(--border-color)',
        borderRadius: 'var(--radius-lg)',
        margin: '16px 0',
      }}
    >
      <div style={{ fontSize: '36px', marginBottom: '8px' }}>{icon}</div>
      <h3 style={{ fontSize: '15px', color: 'var(--text-primary)', marginBottom: '4px' }}>{title}</h3>
      <p style={{ fontSize: '13px', color: 'var(--text-muted)', maxWidth: '400px', marginBottom: actionText ? '16px' : '0' }}>
        {message}
      </p>
      {actionText && onAction && (
        <button type="button" className="btn btn-secondary btn-sm" onClick={onAction}>
          {actionText}
        </button>
      )}
    </div>
  );
};
