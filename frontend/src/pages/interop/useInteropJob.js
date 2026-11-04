import { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../ui/ToastProvider';

/**
 * useInteropJob Hook
 * Manages background execution, SSE logs, cancel, and facilities/vault for Interoperability.
 */
export const useInteropJob = () => {
  const { authHeader } = useAuth();
  const { showToast } = useToast();

  const [facilities, setFacilities] = useState([]);
  const [vaultConns, setVaultConns] = useState({ bahmni: null, o3: null, online: null, offline: null });

  useEffect(() => {
    fetch('/api/v1/interop/facilities', { headers: authHeader() })
      .then((res) => res.json())
      .then((data) => {
        if (data && data.facilities) setFacilities(data.facilities);
      })
      .catch((err) => console.error('Failed to load facilities:', err));

    fetch('/api/settings/connections', { headers: authHeader() })
      .then((res) => res.json())
      .then((list) => {
        if (Array.isArray(list)) {
          const b = list.find((c) => c.system === 'bahmni');
          const o = list.find((c) => c.system === 'openmrs' || c.system === 'o3');
          const onl = list.find((c) => c.system === 'dhis2_online' || c.system === 'dhis2');
          const offl = list.find((c) => c.system === 'dhis2_offline');
          setVaultConns({ bahmni: b, o3: o, online: onl, offline: offl });
        }
      })
      .catch((err) => console.error('Failed to load connection settings:', err));
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
      setLiveLogs((prev) => [...prev, '>>> Cancellation requested by user...']);
    } catch (err) {
      console.error('Cancel job error:', err);
    }
  }, [activeJobId, authHeader]);

  const executeApiJob = useCallback(async (endpoint, payload) => {
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(`Failed to launch operation: ${err.detail || 'Server error'}`, 'error');
        return false;
      }

      const data = await res.json();
      subscribeToJob(data.job_id);
      showToast(`Started operation #${data.job_id}`, 'success');
      return data;
    } catch (err) {
      showToast(`Submission error: ${String(err)}`, 'error');
      return false;
    }
  }, [authHeader, showToast, subscribeToJob]);

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
    facilities,
    vaultConns,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    subscribeToJob,
    cancelActiveJob,
    executeApiJob,
    resetJob,
  };
};

export default useInteropJob;
