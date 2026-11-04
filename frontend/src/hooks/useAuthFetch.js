import { useCallback } from 'react';

/**
 * Returns authorization headers using active token.
 * Checks both 'imnid_token' and 'access_token' for backward compatibility.
 */
export const getAuthToken = () => {
  return localStorage.getItem('imnid_token') || localStorage.getItem('access_token') || '';
};

export const getAuthHeader = () => {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

/**
 * Hook providing auth headers and authenticated fetch helper.
 */
export const useAuthFetch = () => {
  const authHeader = useCallback(() => {
    return getAuthHeader();
  }, []);

  return { authHeader, token: getAuthToken() };
};

export default useAuthFetch;
