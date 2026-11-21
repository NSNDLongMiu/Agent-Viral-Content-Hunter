import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { ApiError } from '../api/client';

export const LoginPage: React.FC = () => {
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // If already authenticated, redirect
  React.useEffect(() => {
    if (isAuthenticated) {
      const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/';
      navigate(from, { replace: true });
    }
  }, [isAuthenticated, navigate, location]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) {
      setError('Vui lòng nhập mật khẩu quản trị.');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      // POST /auth/login accepts {"password": "..."}
      await login({ password });
      const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/';
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('Đăng nhập không thành công. Vui lòng kiểm tra lại mật khẩu.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px',
        backgroundColor: 'var(--bg-app)',
      }}
    >
      <div
        className="card"
        style={{
          width: '100%',
          maxWidth: '400px',
          padding: '32px 24px',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: '24px' }}>
          <div style={{ fontSize: '40px', marginBottom: '8px' }}>🎯</div>
          <h1 style={{ fontSize: '20px', color: 'var(--text-primary)' }}>Viral Content Hunter</h1>
          <p style={{ fontSize: '13px', color: 'var(--text-muted)', marginTop: '4px' }}>
            Hệ thống Quản trị & Săn tin Tự động
          </p>
        </div>

        {error && (
          <div className="notice-box notice-danger" role="alert" style={{ marginBottom: '16px' }}>
            <span>⚠️</span>
            <div>{error}</div>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="username">
              Tài khoản quản trị
            </label>
            <input
              id="username"
              type="text"
              className="form-control"
              value="admin"
              disabled
              readOnly
            />
          </div>

          <div className="form-group" style={{ marginBottom: '20px' }}>
            <label className="form-label" htmlFor="password">
              Mật khẩu quản trị (Admin Password)
            </label>
            <input
              id="password"
              type="password"
              className="form-control"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Nhập mật khẩu..."
              disabled={isSubmitting}
              autoComplete="current-password"
              required
              autoFocus
            />
          </div>

          <button
            type="submit"
            className="btn btn-primary btn-lg"
            style={{ width: '100%' }}
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Đang xác thực...' : 'Đăng nhập'}
          </button>
        </form>

        <div
          style={{
            marginTop: '24px',
            textAlign: 'center',
            fontSize: '11px',
            color: 'var(--text-muted)',
            borderTop: '1px solid var(--border-subtle)',
            paddingTop: '16px',
          }}
        >
          Nhóm quản trị duy nhất • Ngân sách hệ thống 0 VNĐ
        </div>
      </div>
    </div>
  );
};
