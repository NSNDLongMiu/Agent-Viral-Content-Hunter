import React from 'react';
import { NavLink } from 'react-router-dom';

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ isOpen, onClose }) => {
  const navItems = [
    { to: '/', label: 'Tổng quan', icon: '📊' },
    { to: '/inbox', label: 'Hộp thư khám phá', icon: '📥' },
    { to: '/handoff', label: 'Bảng bàn giao', icon: '🚀' },
    { to: '/sources', label: 'Quản lý nguồn', icon: '🌐' },
    { to: '/monitor', label: 'Giám sát hệ thống', icon: '⚡' },
    { to: '/settings', label: 'Cài đặt', icon: '⚙️' },
  ];

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          role="presentation"
          onClick={onClose}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.4)',
            zIndex: 90,
            display: 'none',
          }}
          className="mobile-overlay"
        />
      )}

      <aside
        className={`sidebar ${isOpen ? 'sidebar-open' : ''}`}
        style={{
          width: 'var(--sidebar-width)',
          backgroundColor: 'var(--bg-surface)',
          borderRight: '1px solid var(--border-color)',
          display: 'flex',
          flexDirection: 'column',
          position: 'fixed',
          top: 0,
          bottom: 0,
          left: 0,
          zIndex: 100,
          transition: 'transform 0.2s ease',
        }}
      >
        {/* Brand / Logo */}
        <div
          style={{
            height: 'var(--header-height)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 16px',
            borderBottom: '1px solid var(--border-color)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '20px' }}>🎯</span>
            <span style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)' }}>
              Viral Hunter
            </span>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-sm mobile-close-btn"
            onClick={onClose}
            aria-label="Đóng bảng điều hướng"
            style={{ display: 'none', padding: '2px 6px' }}
          >
            ✕
          </button>
        </div>

        {/* Navigation items */}
        <nav style={{ flex: 1, padding: '12px 8px', overflowY: 'auto' }}>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {navItems.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === '/'}
                  onClick={onClose}
                  style={({ isActive }) => ({
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    padding: '8px 12px',
                    borderRadius: 'var(--radius-md)',
                    fontSize: '13px',
                    fontWeight: 500,
                    textDecoration: 'none',
                    color: isActive ? 'var(--primary-text)' : 'var(--text-secondary)',
                    backgroundColor: isActive ? 'var(--primary-subtle)' : 'transparent',
                  })}
                >
                  <span style={{ fontSize: '16px' }}>{item.icon}</span>
                  <span>{item.label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        {/* Footer info: 0 VND Budget Policy */}
        <div
          style={{
            padding: '12px 16px',
            borderTop: '1px solid var(--border-color)',
            backgroundColor: 'var(--bg-subtle)',
            fontSize: '11px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' }}>
            <span className="badge badge-success" style={{ fontSize: '10px' }}>
              0 VNĐ / tháng
            </span>
          </div>
          <div style={{ color: 'var(--text-muted)' }}>Chính sách ngân sách: 0đ</div>
          <div style={{ color: 'var(--text-muted)', fontSize: '10px', marginTop: '2px' }}>
            Paid APIs: Vô hiệu hóa
          </div>
        </div>
      </aside>

      <style>{`
        @media (max-width: 768px) {
          .sidebar {
            transform: translateX(-100%);
          }
          .sidebar-open {
            transform: translateX(0) !important;
          }
          .mobile-overlay {
            display: block !important;
          }
          .mobile-close-btn {
            display: inline-flex !important;
          }
        }
      `}</style>
    </>
  );
};
