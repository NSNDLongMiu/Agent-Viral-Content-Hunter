import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { User, LoginRequest } from '../api/types';
import { login as apiLogin, logout as apiLogout, getSettings } from '../api/endpoints';
import { getAuthToken, clearAuthToken } from '../api/client';

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (credentials: LoginRequest) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Check auth session on mount
  useEffect(() => {
    let isMounted = true;

    async function checkAuth() {
      const token = getAuthToken();
      if (!token) {
        if (isMounted) {
          setUser(null);
          setIsLoading(false);
        }
        return;
      }

      try {
        // Validate session token with a protected endpoint
        // Restarting the API process invalidates server sessions -> will throw 401
        await getSettings();
        if (isMounted) {
          setUser({ username: 'admin', role: 'admin' });
        }
      } catch {
        if (isMounted) {
          clearAuthToken();
          setUser(null);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    checkAuth();
    return () => {
      isMounted = false;
    };
  }, []);

  const login = useCallback(async (credentials: LoginRequest) => {
    await apiLogin(credentials);
    setUser({ username: 'admin', role: 'admin' });
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      clearAuthToken();
      setUser(null);
      window.location.href = '/login';
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
