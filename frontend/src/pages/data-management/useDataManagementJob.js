import { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';

/**
 * useDataManagementJob Hook
 * Manages background execution, SSE logs, cancel, upload and vault connections for Data Management.
 */
export const useDataManagementJob = () => {
  const { authHeader } = useAuth();
  const [vaultConns, setVaultConns] = useState({ offline: null, online: null, redcap: null });

  useEffect(() => {
    const fetchVault = async () => {
      try {
        const res = await fetch('/api/settings/connections', { headers: authHeader() });
        if (res.ok) {
          const list = await res.json();
          const offline = list.find((c) => c.system === 'dhis2_offline');
          const online = list.find((c) => c.system === 'dhis2_online' || c.system === 'dhis2');
          const redcap = list.find((c) => c.system === 'redcap');
          setVaultConns({ offline, online, redcap });
        }
      } catch (e) {
        console.error('Failed to load connection settings:', e);
      }
    };
    fetchVault();
  }, [authHeader]);

  // Shared Job and SSE State
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobState, setJobState] = useState(null);
  const [liveLogs, setLiveLogs] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const eventSourceRef = useRef(null);

  const fetchLatestJobState = useCallback(async (jobId) => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`, { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setJobState(data);
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'canceled') {
          setIsStreaming(false);
        }
      }
    } catch (err) {
      console.error('Failed to fetch latest job state:', err);
    }
  }, [authHeader]);

  // Subscribe to Job SSE logs
  const subscribeToJob = useCallback((jobId) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    setActiveJobId(jobId);
    setLiveLogs([]);
    setIsStreaming(true);
    setJobState({ status: 'running', progress: 0, message: 'Job initialized...' });

    const token = localStorage.getItem('imnid_token');
    const sseUrl = `/api/jobs/${jobId}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    const handlePayload = (parsed) => {
      if (!parsed) return;
      if (parsed.type === 'log') {
        const line = typeof parsed.data === 'string' ? parsed.data : parsed.data?.line || JSON.stringify(parsed.data);
        setLiveLogs((prev) => [...prev, line]);
      } else if (parsed.type === 'progress') {
        setJobState((prev) => ({ ...prev, ...(parsed.data || parsed) }));
      } else if (parsed.type === 'status' || parsed.type === 'state') {
        const stateData = parsed.data || parsed;
        setJobState((prev) => ({ ...prev, ...stateData }));
        if (stateData.status === 'completed' || stateData.status === 'failed' || stateData.status === 'canceled') {
          setIsStreaming(false);
          es.close();
          fetchLatestJobState(jobId);
        }
      }
    };

    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data);
        handlePayload(parsed);
      } catch {
        if (e.data) setLiveLogs((prev) => [...prev, e.data]);
      }
    };

    es.addEventListener('log', (e) => {
      try {
        const data = JSON.parse(e.data);
        setLiveLogs((prev) => [...prev, data.line || e.data]);
      } catch {
        setLiveLogs((prev) => [...prev, e.data]);
      }
    });

    es.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse(e.data);
        setJobState((prev) => ({ ...prev, ...data }));
      } catch (err) {
        console.error('Progress event parse error:', err);
      }
    });

    es.addEventListener('status', (e) => {
      try {
        const data = JSON.parse(e.data);
        setJobState((prev) => ({ ...prev, ...data }));
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'canceled') {
          setIsStreaming(false);
          es.close();
          fetchLatestJobState(jobId);
        }
      } catch (err) {
        console.error('Status event parse error:', err);
      }
    });

    es.onerror = () => {
      setIsStreaming(false);
      es.close();
      fetchLatestJobState(jobId);
    };
  }, [fetchLatestJobState]);

  const cancelActiveJob = useCallback(async () => {
    if (!activeJobId) return;
    try {
      await fetch(`/api/jobs/${activeJobId}/cancel`, {
        method: 'POST',
        headers: authHeader(),
      });
      setIsStreaming(false);
      setJobState((prev) => (prev ? { ...prev, status: 'canceled', message: 'Canceled by user' } : null));
    } catch (err) {
      console.error('Cancel job error:', err);
    }
  }, [activeJobId, authHeader]);

  // Upload helper
  const uploadFile = useCallback(async (fileObj) => {
    const formData = new FormData();
    formData.append('file', fileObj);
    const res = await fetch('/api/data-management/upload', {
      method: 'POST',
      headers: authHeader(),
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || (res.status === 413 ? 'File too large for web server limit (413)' : `Upload failed (HTTP ${res.status})`));
    }
    return await res.json();
  }, [authHeader]);

  const resetJob = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    setActiveJobId(null);
    setJobState(null);
    setLiveLogs([]);
    setIsStreaming(false);
  }, []);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  return {
    authHeader,
    vaultConns,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    subscribeToJob,
    cancelActiveJob,
    uploadFile,
    resetJob,
  };
};

export default useDataManagementJob;
