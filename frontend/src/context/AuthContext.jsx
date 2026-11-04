import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [token, setToken] = useState(() => localStorage.getItem('imnid_token'));
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('imnid_user');
    return saved ? JSON.parse(saved) : null;
  });
  const [loading, setLoading] = useState(true);

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
  }, [token]);

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

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('imnid_token');
    localStorage.removeItem('imnid_user');
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
