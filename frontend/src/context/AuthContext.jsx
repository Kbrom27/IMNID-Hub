import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';

const AuthContext = createContext(null);

// 10 minutes of user inactivity timeout
const INACTIVITY_TIMEOUT_MS = 10 * 60 * 1000;

export const AuthProvider = ({ children }) => {
  const [token, setToken] = useState(() => localStorage.getItem('imnid_token'));
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('imnid_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [loading, setLoading] = useState(true);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  const logout = useCallback((reason) => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('imnid_token');
    localStorage.removeItem('imnid_user');
    localStorage.removeItem('imnid_last_activity');
    if (reason) {
      localStorage.setItem('imnid_session_reason', reason);
    } else {
      localStorage.removeItem('imnid_session_reason');
    }
  }, []);

  useEffect(() => {
    if (token) {
      fetch('/api/auth/me', {
        headers: { 'Authorization': `Bearer ${token}` }
      })
        .then(res => {
          if (!res.ok) throw new Error('Unauthorized');
          return res.json();
        })
        .then(data => {
          setUser(data.user);
          localStorage.setItem('imnid_user', JSON.stringify(data.user));
        })
        .catch(() => {
          logout();
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [token, logout]);

  // 10-Minute Inactivity Auto-Logout Monitor
  useEffect(() => {
    if (!token) return;

    const recordActivity = () => {
      localStorage.setItem('imnid_last_activity', Date.now().toString());
    };

    // Initialize activity timestamp
    recordActivity();

    // Check every 10 seconds if user has been inactive for 10 minutes
    const checkInterval = setInterval(() => {
      const now = Date.now();
      const lastActivity = parseInt(localStorage.getItem('imnid_last_activity') || `${now}`, 10);
      if (now - lastActivity >= INACTIVITY_TIMEOUT_MS) {
        logout('Your session has expired due to 10 minutes of inactivity. Please sign in again.');
      }
    }, 10000);

    // Activity events to track
    const events = ['mousedown', 'keydown', 'touchstart', 'scroll', 'click'];
    const handleActivity = () => {
      recordActivity();
    };

    events.forEach((evt) => window.addEventListener(evt, handleActivity, { passive: true }));

    // Periodic token refresh while user remains active (every 5 minutes)
    const refreshInterval = setInterval(() => {
      const now = Date.now();
      const lastActivity = parseInt(localStorage.getItem('imnid_last_activity') || `${now}`, 10);
      if (now - lastActivity < INACTIVITY_TIMEOUT_MS && tokenRef.current) {
        fetch('/api/auth/refresh', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${tokenRef.current}`
          }
        })
          .then(res => res.ok ? res.json() : null)
          .then(data => {
            if (data?.access_token) {
              setToken(data.access_token);
              localStorage.setItem('imnid_token', data.access_token);
            }
          })
          .catch(() => {});
      }
    }, 5 * 60 * 1000);

    return () => {
      clearInterval(checkInterval);
      clearInterval(refreshInterval);
      events.forEach((evt) => window.removeEventListener(evt, handleActivity));
    };
  }, [token, logout]);

  const login = async (username, password) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to login');
    }

    const data = await res.json();
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem('imnid_token', data.access_token);
    localStorage.setItem('imnid_user', JSON.stringify(data.user));
    localStorage.setItem('imnid_last_activity', Date.now().toString());
    localStorage.removeItem('imnid_session_reason');
    return data;
  };

  const changePassword = async (currentPassword, newPassword) => {
    const res = await fetch('/api/auth/change-password', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || 'Failed to update password');
    }
    const updated = { ...user, must_change_password: false };
    setUser(updated);
    localStorage.setItem('imnid_user', JSON.stringify(updated));
    return true;
  };

  const authHeader = () => token ? { 'Authorization': `Bearer ${token}` } : {};

  return (
    <AuthContext.Provider value={{
      token,
      user,
      loading,
      login,
      changePassword,
      logout,
      authHeader,
      isAdmin: user?.role === 'admin',
      isOperator: user?.role === 'operator' || user?.role === 'admin',
      isViewer: user?.role === 'viewer'
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
