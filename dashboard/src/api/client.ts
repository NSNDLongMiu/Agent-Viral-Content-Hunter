/**
 * Centralized HTTP Client for Viral Content Hunter Dashboard.
 * All HTTP requests in the application MUST go through this module.
 */

import { ApiErrorResponse } from './types';

export class ApiError extends Error {
  public status: number;
  public details?: unknown;
  public code?: string;

  constructor(status: number, message: string, details?: unknown, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
    this.code = code;
  }
}

const API_BASE_URL: string = (import.meta.env.VITE_API_BASE || '/api').replace(/\/+$/, '');

interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined | null>;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, headers, ...restOptions } = options;

  let url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
  if (params) {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        searchParams.append(key, String(value));
      }
    });
    const queryString = searchParams.toString();
    if (queryString) {
      url += (url.includes('?') ? '&' : '?') + queryString;
    }
  }

  const defaultHeaders: Record<string, string> = {
    Accept: 'application/json',
  };

  if (!(restOptions.body instanceof FormData)) {
    defaultHeaders['Content-Type'] = 'application/json';
  }

  const config: RequestInit = {
    credentials: 'include', // Include cookies/session credentials
    headers: {
      ...defaultHeaders,
      ...headers,
    },
    ...restOptions,
  };

  let response: Response;
  try {
    response = await fetch(url, config);
  } catch (error) {
    // Network failure / unreachable API
    throw new ApiError(0, 'Không thể kết nối đến máy chủ backend (Network Error). Vui lòng kiểm tra dịch vụ.');
  }

  // Handle 401 Unauthorized -> redirect to login
  if (response.status === 401) {
    const isLoginRoute = window.location.pathname === '/login';
    if (!isLoginRoute) {
      window.location.href = '/login';
    }
    throw new ApiError(401, 'Phiên đăng nhập đã hết hạn hoặc chưa xác thực.');
  }

  if (!response.ok) {
    let errorData: ApiErrorResponse | null = null;
    try {
      errorData = await response.json();
    } catch {
      // Body not JSON
    }

    const message =
      errorData?.message ||
      (typeof errorData?.detail === 'string' ? errorData.detail : null) ||
      `Lỗi yêu cầu API (${response.status}: ${response.statusText})`;

    throw new ApiError(response.status, message, errorData?.detail, errorData?.code);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export async function downloadBlob(path: string, filename: string): Promise<void> {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
  const response = await fetch(url, {
    credentials: 'include',
  });

  if (!response.ok) {
    throw new ApiError(response.status, `Không thể tải tệp: ${response.statusText}`);
  }

  const blob = await response.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = downloadUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.URL.revokeObjectURL(downloadUrl);
}

// Convenience methods
export const apiClient = {
  get: <T>(path: string, params?: RequestOptions['params']) => request<T>(path, { method: 'GET', params }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  download: downloadBlob,
};
