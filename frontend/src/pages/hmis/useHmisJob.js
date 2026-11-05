import { useState, useRef, useEffect, useCallback } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../ui/ToastProvider';

export function gregorianToEthiopian(date = new Date()) {
  const gy = date.getFullYear();
  const gm = date.getMonth() + 1;
  const gd = date.getDate();

  const ethiopianToGregorianDays = (ey, em, ed) => {
    const epoch = new Date(0);
    epoch.setUTCFullYear(8, 7, 27);
    epoch.setUTCHours(0, 0, 0, 0);
    const days = 365 * (ey - 1) + Math.floor((ey - 1) / 4) + 30 * (em - 1) + (ed - 1);
    return epoch.getTime() + days * 86400000;
  };

  const targetUtc = Date.UTC(gy, gm - 1, gd);
  let ey = gy - 8;
  for (const candidate of [gy - 9, gy - 8, gy - 7]) {
    const ny = ethiopianToGregorianDays(candidate, 1, 1);
    if (ny <= targetUtc) {
      ey = candidate;
    }
  }

  const daysDiff = Math.round((targetUtc - ethiopianToGregorianDays(ey, 1, 1)) / 86400000);
  let em;
  if (daysDiff < 360) {
    em = Math.floor(daysDiff / 30) + 1;
  } else {
    em = 13;
  }
  return { year: ey, month: em };
}

/**
 * useHmisJob Hook
 * Manages Ethiopian calendar conversion, DHIS2 discovery connect, file uploads, and SSE execution for HMIS reporting.
 */
export const useHmisJob = () => {
  const { authHeader } = useAuth();
  const { showToast } = useToast();

  // Ethiopian Calendar State (dynamically computed from current date)
  const initialEth = gregorianToEthiopian(new Date());
  const [ethYear, setEthYear] = useState(initialEth.year);
  const [ethMonth, setEthMonth] = useState(initialEth.month);
  const [calendarInfo, setCalendarInfo] = useState(null);

  // Connection & Discovery State (HM-01)
  const [dhis2Url, setDhis2Url] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isConnecting, setIsConnecting] = useState(false);
  const [discoveryData, setDiscoveryData] = useState(null);
  const [discoveryError, setDiscoveryError] = useState(null);

  // Job & SSE Streaming State
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobState, setJobState] = useState(null);
  const [liveLogs, setLiveLogs] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [outputArtifacts, setOutputArtifacts] = useState(null);
  const [computedIndicators, setComputedIndicators] = useState(null);

  const eventSourceRef = useRef(null);

  const fetchCalendar = useCallback(async (y, m) => {
    try {
      const res = await fetch(`/api/hmis/ethiopian-calendar?year=${y}&month=${m}`, {
        headers: authHeader(),
      });
      if (res.ok) {
        const data = await res.json();
        setCalendarInfo(data);
        return data;
      }
    } catch (err) {
      console.error('Failed to load Ethiopian calendar:', err);
    }
    return null;
  }, [authHeader]);

  useEffect(() => {
    fetchCalendar(ethYear, ethMonth);
  }, [ethYear, ethMonth, fetchCalendar]);

  const handleYearMonthChange = (y, m) => {
    setEthYear(y);
    setEthMonth(m);
  };

  // Connect to DHIS2 and discover metadata (HM-01)
  const handleConnectDhis2 = async () => {
    setIsConnecting(true);
    setDiscoveryError(null);
    try {
      const res = await fetch('/api/hmis/connect', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dhis2_url: dhis2Url || undefined,
          username: username || undefined,
          password: password || undefined,
          verify_ssl: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Connection failed');
      setDiscoveryData(data.discovery);
      showToast('Connected to DHIS2 and discovered programs', 'success');
      return data.discovery;
    } catch (err) {
      setDiscoveryError(err.message);
      showToast(err.message, 'error');
    } finally {
      setIsConnecting(false);
    }
  };

  // Upload helper
  const handleFileUpload = async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/hmis/upload', {
        method: 'POST',
        headers: authHeader(),
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`Uploaded "${file.name}"`, 'success');
        return data.filepath;
      } else {
        showToast(data.detail || 'Upload failed', 'error');
      }
    } catch (err) {
      showToast('Upload failed: ' + err.message, 'error');
    }
    return null;
  };

  const subscribeToJob = useCallback((jobId) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    setActiveJobId(jobId);
    setLiveLogs([]);
    setIsStreaming(true);
    setOutputArtifacts(null);
    setComputedIndicators(null);

    const token = localStorage.getItem('imnid_token');
    const sseUrl = `/api/jobs/${jobId}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

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
        console.error('Progress error:', err);
      }
    });

    es.addEventListener('status', (e) => {
      try {
        const data = JSON.parse(e.data);
        setJobState((prev) => ({ ...prev, ...data }));
        if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
          setIsStreaming(false);
          es.close();

          // Refresh job details to capture artifacts, result_file, and tallies
          fetch(`/api/jobs/${jobId}`, { headers: authHeader() })
            .then((r) => r.json())
            .then((j) => {
              const resFile =
                j.result_file ||
                j.artifacts?.output_xlsx ||
                j.artifacts?.output_file ||
                j.artifacts?.filename ||
                j.result?.output_xlsx ||
                j.result?.output_file ||
                j.result?.filename;

              setJobState((prev) => ({
                ...prev,
                ...j,
                status: j.status || prev?.status || 'completed',
                result_file: resFile || prev?.result_file,
                artifacts: { ...prev?.artifacts, ...j.artifacts, ...j.result },
              }));

              const combined = { ...j.artifacts, ...j.result };
              const newArtifacts = [];
              if (combined.output_file) {
                newArtifacts.push(j.filename || combined.filename || 'register_output.xlsx');
              }
              if (combined.output_xlsx) {
                newArtifacts.push(j.filename || combined.filename || 'aggregate_export.xlsx');
              }
              if (combined.output_csv) {
                newArtifacts.push(j.csv_filename || combined.csv_filename || 'aggregate_export.csv');
              }
              if (combined.preview_file) {
                newArtifacts.push(combined.preview_file.split('/').pop());
              }
              if (combined.export_json_file) {
                newArtifacts.push(combined.export_json_file.split('/').pop());
              }
              if (newArtifacts.length > 0) {
                setOutputArtifacts((prev) => [...new Set([...(prev || []), ...newArtifacts])]);
              }
              if (combined.values) {
                setComputedIndicators(combined.values);
              }
              if (combined.tallies) {
                setComputedIndicators(combined.tallies);
              }
            })
            .catch((err) => console.error('Failed to get job detail:', err));
        }
      } catch (err) {
        console.error('Status error:', err);
      }
    });

    es.onerror = () => {
      setIsStreaming(false);
      es.close();
    };
  }, [authHeader]);

  const handleSubmitJob = useCallback(async (endpoint, payload) => {
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Job submission failed');
      if (data.job_id) {
        subscribeToJob(data.job_id);
        showToast(`Started reporting job #${data.job_id}`, 'success');
      }
      return data;
    } catch (err) {
      showToast(`Error submitting job: ${err.message}`, 'error');
    }
  }, [authHeader, showToast, subscribeToJob]);

  const handleCancelJob = useCallback(async () => {
    if (!activeJobId) return;
    try {
      await fetch(`/api/jobs/${activeJobId}/cancel`, {
        method: 'POST',
        headers: authHeader(),
      });
      setIsStreaming(false);
      setLiveLogs((prev) => [...prev, '>>> Job cancellation requested by user...']);
    } catch (err) {
      console.error('Cancel error:', err);
    }
  }, [activeJobId, authHeader]);

  const resetJob = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    setActiveJobId(null);
    setJobState(null);
    setLiveLogs([]);
    setIsStreaming(false);
    setOutputArtifacts(null);
    setComputedIndicators(null);
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
    ethYear,
    ethMonth,
    calendarInfo,
    handleYearMonthChange,
    dhis2Url,
    setDhis2Url,
    username,
    setUsername,
    password,
    setPassword,
    isConnecting,
    discoveryData,
    discoveryError,
    handleConnectDhis2,
    handleFileUpload,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    outputArtifacts,
    computedIndicators,
    handleSubmitJob,
    handleCancelJob,
    resetJob,
  };
};

export default useHmisJob;
