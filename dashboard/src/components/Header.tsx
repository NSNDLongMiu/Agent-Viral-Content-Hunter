import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { getHealth } from '../api/endpoints';

interface HeaderProps {
  onToggleSidebar: () => void;
}

export const Header: React.FC<HeaderProps> = ({ onToggleSidebar }) => {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 30000,
    retry: 1,
  });

  const isHealthy = health?.status === 'ok';

  return (
    <header
      style={{
        height: 'var(--header-height)',
        backgroundColor: 'var(--bg-surface)',
        borderBottom: '1px solid var(--border-color)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 20px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button
          type="button"
          onClick={onToggleSidebar}
          aria-label="Mở danh mục điều hướng"
          className="btn btn-secondary btn-sm mobile-menu-btn"
          style={{ display: 'none' }}
        >
          ☰
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              display: 'inline-block',
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: isHealthy ? 'var(--success)' : 'var(--danger)',
            }}
            title={isHealthy ? 'Máy chủ backend hoạt động bình thường' : 'Máy chủ chưa kết nối'}
          />
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {isHealthy ? 'Hệ thống trực tuyến' : 'Đang kiểm tra kết nối...'}
          </span>
        </div>
      </div>

      <style>{`
        @media (max-width: 768px) {
          .mobile-menu-btn {
            display: inline-flex !important;
          }
        }
      `}</style>
    </header>
  );
};
