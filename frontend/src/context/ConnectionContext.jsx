import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';

export const CANONICAL_SYSTEMS = [
  {
    key: 'dhis2_online',
    name: 'DHIS2 Online',
    shortName: 'DHIS2 Online',
    desc: 'National Data Warehouse',
    group: 'DHIS2 Instances',
    category: 'dhis2',
  },
  {
    key: 'dhis2_offline',
    name: 'DHIS2 Offline',
    shortName: 'DHIS2 Offline',
    desc: 'Facility Local Instance',
    group: 'DHIS2 Instances',
    category: 'dhis2',
  },
  {
    key: 'dhis2_moh',
    name: 'DHIS2 MOH Central',
    shortName: 'MOH Central',
    desc: 'National Aggregate Server',
    group: 'DHIS2 Instances',
    category: 'dhis2',
  },
  {
    key: 'openmrs',
    name: 'OpenMRS 3.x',
    shortName: 'OpenMRS 3.x',
    desc: 'Hospital Clinical EMR',
    group: 'Clinical Systems',
    category: 'clinical',
  },
  {
    key: 'bahmni',
    name: 'Bahmni 0.93',
    shortName: 'Bahmni',
    desc: 'Legacy EMR Platform',
    group: 'Clinical Systems',
    category: 'clinical',
  },
  {
    key: 'redcap',
    name: 'REDCap',
    shortName: 'REDCap',
    desc: 'Research Clinical Registry',
    group: 'Clinical Systems',
    category: 'clinical',
  },
  {
    key: 'mediator',
    name: 'Mediator Service',
    shortName: 'Mediator',
    desc: 'FastAPI Microservice',
    group: 'Core Services',
    category: 'core',
  },
];

const ConnectionContext = createContext(null);

export const ConnectionProvider = ({ children }) => {
  const [connections, setConnections] = useState({});
  const [loading, setLoading] = useState(true);
  const [testingMap, setTestingMap] = useState({});
  const [testingAll, setTestingAll] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState(null);
  const [secondsAgo, setSecondsAgo] = useState(0);

  // Load connection statuses
  const fetchStatus = useCallback(async (isBackground = false) => {
    if (!isBackground) setLoading(true);
    try {
      const res = await fetch('/api/connections/status');
      if (res.ok) {
        const data = await res.json();
        setConnections(data || {});
        setLastRefreshed(new Date());
        setSecondsAgo(0);
      }
    } catch (err) {
      console.warn('Failed to fetch connection status:', err);
    } finally {
      if (!isBackground) setLoading(false);
    }
  }, []);

  // Poll connection statuses periodically (every 30 seconds)
  useEffect(() => {
    fetchStatus();
    const interval = setInterval(() => fetchStatus(true), 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // Keep secondsAgo counter updated every second
  useEffect(() => {
    if (!lastRefreshed) return;
    const timer = setInterval(() => {
      const diff = Math.max(0, Math.floor((Date.now() - lastRefreshed.getTime()) / 1000));
      setSecondsAgo(diff);
    }, 1000);
    return () => clearInterval(timer);
  }, [lastRefreshed]);

  // Test single connection
  const testSingle = useCallback(async (systemKey) => {
    const sys = connections[systemKey];
    setTestingMap((prev) => ({ ...prev, [systemKey]: true }));
    try {
      const res = await fetch('/api/connections/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system: systemKey,
          base_url: sys?.configured_url || sys?.base_url || '',
          username: sys?.username || '',
          secret: '',
        }),
      });
      const data = await res.json();
      setConnections((prev) => ({
        ...prev,
        [systemKey]: {
          ...prev[systemKey],
          result: data,
          status: data.ok ? 'connected' : data.status === 'not_configured' ? 'not_configured' : 'unreachable',
        },
      }));
      setLastRefreshed(new Date());
      setSecondsAgo(0);
      return data;
    } catch (err) {
      console.error(`Failed to test connection for ${systemKey}:`, err);
      return { ok: false, error: err.message };
    } finally {
      setTestingMap((prev) => ({ ...prev, [systemKey]: false }));
    }
  }, [connections]);

  // Test all connections in parallel
  const testAll = useCallback(async () => {
    setTestingAll(true);
    const initialMap = {};
    CANONICAL_SYSTEMS.forEach((s) => {
      initialMap[s.key] = true;
    });
    setTestingMap(initialMap);

    try {
      await Promise.all(
        CANONICAL_SYSTEMS.map(async (sys) => {
          const sysData = connections[sys.key];
          try {
            const res = await fetch('/api/connections/test', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                system: sys.key,
                base_url: sysData?.configured_url || sysData?.base_url || '',
                username: sysData?.username || '',
                secret: '',
              }),
            });
            const data = await res.json();
            setConnections((prev) => ({
              ...prev,
              [sys.key]: {
                ...prev[sys.key],
                result: data,
                status: data.ok ? 'connected' : data.status === 'not_configured' ? 'not_configured' : 'unreachable',
              },
            }));
          } catch (e) {
            console.error(`Error testing ${sys.key}:`, e);
          } finally {
            setTestingMap((prev) => ({ ...prev, [sys.key]: false }));
          }
        })
      );
      setLastRefreshed(new Date());
      setSecondsAgo(0);
    } finally {
      setTestingAll(false);
      setTestingMap({});
    }
  }, [connections]);

  // Unified single source of truth calculations
  const summary = useMemo(() => {
    const list = CANONICAL_SYSTEMS.map((sys) => {
      const data = connections[sys.key];
      const isConfigured = data?.configured !== false && data?.status !== 'not_configured';
      const isConnected = isConfigured && (data?.status === 'connected' || data?.result?.ok === true);
      const isTesting = Boolean(testingMap[sys.key]) || testingAll;
      const latencyMs = data?.result?.latency_ms ?? null;
      const effectiveUrl = data?.effective_url || data?.base_url || '';
      const source = data?.source === 'vault' ? 'Vault' : 'Environment';

      let state = 'not_configured';
      if (isTesting) {
        state = 'testing';
      } else if (isConnected) {
        state = 'connected';
      } else if (isConfigured) {
        state = 'unreachable';
      }

      return {
        ...sys,
        data,
        isConfigured,
        isConnected,
        isTesting,
        latencyMs,
        effectiveUrl,
        source,
        state,
        error: data?.result?.error || null,
      };
    });

    const totalCount = list.length; // 7
    const configuredCount = list.filter((s) => s.isConfigured).length;
    const connectedCount = list.filter((s) => s.isConnected).length;
    const offlineCount = configuredCount - connectedCount;
    const notConfiguredCount = totalCount - configuredCount;
    const offlineSystems = list.filter((s) => s.isConfigured && !s.isConnected);

    // Grouping
    const groups = {
      dhis2: {
        title: 'DHIS2 Instances',
        systems: list.filter((s) => s.category === 'dhis2'),
        connected: list.filter((s) => s.category === 'dhis2' && s.isConnected).length,
        total: list.filter((s) => s.category === 'dhis2').length,
      },
      clinical: {
        title: 'Clinical Systems',
        systems: list.filter((s) => s.category === 'clinical'),
        connected: list.filter((s) => s.category === 'clinical' && s.isConnected).length,
        total: list.filter((s) => s.category === 'clinical').length,
      },
      core: {
        title: 'Core Services',
        systems: list.filter((s) => s.category === 'core'),
        connected: list.filter((s) => s.category === 'core' && s.isConnected).length,
        total: list.filter((s) => s.category === 'core').length,
      },
    };

    const isInitialLoading = loading && Object.keys(connections).length === 0;

    let overallHealth = 'operational'; // 'operational' | 'degraded' | 'outage' | 'checking'
    if (isInitialLoading) {
      overallHealth = 'checking';
    } else if (connectedCount === 0 && configuredCount > 0) {
      overallHealth = 'outage';
    } else if (offlineCount > 0) {
      overallHealth = 'degraded';
    }

    return {
      isInitialLoading,
      totalCount,
      configuredCount,
      connectedCount,
      offlineCount,
      notConfiguredCount,
      offlineSystems,
      list,
      systems: list,
      groups,
      overallHealth,
    };
  }, [connections, loading, testingMap, testingAll]);

  const value = {
    connections,
    loading,
    summary,
    testingMap,
    testingAll,
    lastRefreshed,
    secondsAgo,
    fetchStatus,
    testSingle,
    testAll,
  };

  return <ConnectionContext.Provider value={value}>{children}</ConnectionContext.Provider>;
};

export const useConnections = () => {
  const ctx = useContext(ConnectionContext);
  if (!ctx) {
    throw new Error('useConnections must be used within a ConnectionProvider');
  }
  return ctx;
};

export default ConnectionContext;
