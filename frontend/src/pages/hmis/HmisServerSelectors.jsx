import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../ui/ToastProvider';
import {
  Server,
  Database,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  ExternalLink,
  Layers,
  MapPin,
  Calendar,
  FileSpreadsheet,
} from 'lucide-react';
import { Button } from '../../ui';

/**
 * HmisConnectionCard
 * Displays active saved server connection with zero manual credential fields.
 * Supports DHIS2 (Online vs Offline toggle) and OpenMRS 3.x with uniform theme styling.
 */
export const HmisConnectionCard = ({
  type = 'dhis2',
  selectedSystem,
  onSystemChange,
  showToggle = true,
}) => {
  const { authHeader } = useAuth();
  const { showToast } = useToast();
  const [connections, setConnections] = useState(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const fetchConnections = useCallback(async () => {
    try {
      const res = await fetch('/api/hmis/connections', { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setConnections(data);
        if (type === 'dhis2_moh' && !selectedSystem && onSystemChange) {
          onSystemChange('dhis2_moh');
        }
      }
    } catch (err) {
      console.warn('Failed to fetch HMIS connections:', err);
    } finally {
      setLoading(false);
    }
  }, [authHeader, type, selectedSystem, onSystemChange]);

  useEffect(() => {
    fetchConnections();
  }, [fetchConnections]);

  const activeConn = useMemo(() => {
    if (!connections) return null;
    if (type === 'openmrs') return connections.openmrs;
    if (type === 'dhis2_moh' || selectedSystem === 'dhis2_moh') return connections.dhis2_moh;
    if (!selectedSystem) return null;
    return selectedSystem === 'dhis2_offline' ? connections.dhis2_offline : connections.dhis2_online;
  }, [connections, type, selectedSystem]);

  const handleTest = async () => {
    if (!activeConn) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch('/api/connections/test', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system: activeConn.system,
          base_url: activeConn.base_url,
          username: activeConn.username,
        }),
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setTestResult({ ok: true, message: data.message || 'Connected successfully' });
        showToast(`Connected to ${activeConn.name} successfully`, 'success');
      } else {
        setTestResult({ ok: false, message: data.detail || data.message || 'Connection test failed' });
        showToast(`Failed connecting to ${activeConn.name}: ${data.detail || data.message}`, 'error');
      }
    } catch (err) {
      setTestResult({ ok: false, message: err.message });
      showToast(err.message, 'error');
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 animate-pulse flex items-center justify-between">
        <div className="h-4 bg-slate-200 dark:bg-slate-800 rounded w-1/3" />
        <div className="h-4 bg-slate-200 dark:bg-slate-800 rounded w-20" />
      </div>
    );
  }

  return (
    <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-3">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 flex items-center justify-center text-teal-600 dark:text-teal-400 shrink-0">
            {type === 'openmrs' ? <Server className="w-5 h-5" /> : <Database className="w-5 h-5" />}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-slate-800 dark:text-slate-100 text-sm">
                {activeConn?.name || (type === 'dhis2_moh' ? 'DHIS2 MOH Central' : type === 'dhis2' ? 'DHIS2 Server' : 'OpenMRS 3.x')}
              </span>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-bold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                Verified
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 font-mono mt-0.5 truncate max-w-md">
              {activeConn?.base_url || 'Vault configured'} <span className="text-slate-400 dark:text-slate-500">• user: {activeConn?.username || 'admin'}</span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5 self-end sm:self-auto">
          {type === 'dhis2' && showToggle && (
            <div className="inline-flex rounded-lg p-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs font-semibold">
              <button
                type="button"
                onClick={() => onSystemChange && onSystemChange('dhis2_online')}
                className={`px-3 py-1 rounded-md text-xs transition-colors ${
                  selectedSystem !== 'dhis2_offline'
                    ? 'bg-white dark:bg-slate-700 text-teal-700 dark:text-teal-300 font-bold shadow-xs'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                Online
              </button>
              <button
                type="button"
                onClick={() => onSystemChange && onSystemChange('dhis2_offline')}
                className={`px-3 py-1 rounded-md text-xs transition-colors ${
                  selectedSystem === 'dhis2_offline'
                    ? 'bg-white dark:bg-slate-700 text-teal-700 dark:text-teal-300 font-bold shadow-xs'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
                }`}
              >
                Offline
              </button>
            </div>
          )}

          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={handleTest}
            disabled={testing}
            className="text-xs font-semibold h-8 px-3"
          >
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${testing ? 'animate-spin' : ''}`} />
            {testing ? 'Testing...' : 'Test'}
          </Button>

          <a
            href="/settings"
            target="_blank"
            rel="noreferrer"
            title="Manage server credentials in Settings"
            className="inline-flex items-center justify-center h-8 px-2.5 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors text-xs"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>

      {testResult && (
        <div
          className={`px-2.5 py-1.5 rounded text-xs flex items-center justify-between ${
            testResult.ok
              ? 'bg-emerald-50 text-emerald-800 border border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800'
              : 'bg-rose-50 text-rose-800 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800'
          }`}
        >
          <div className="flex items-center gap-1.5 truncate">
            {testResult.ok ? <CheckCircle className="w-3.5 h-3.5 shrink-0" /> : <AlertTriangle className="w-3.5 h-3.5 shrink-0" />}
            <span className="truncate">{testResult.message}</span>
          </div>
          <button type="button" onClick={() => setTestResult(null)} className="text-slate-400 hover:text-slate-600 text-xs ml-2">
            ×
          </button>
        </div>
      )}
    </div>
  );
};

/**
 * Dhis2ProgramSelect
 */
export const Dhis2ProgramSelect = ({
  system = 'dhis2_online',
  value,
  onChange,
  filterKeyword = '',
  label = 'Tracker Program',
}) => {
  const { authHeader } = useAuth();
  const [programs, setPrograms] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!system) {
      setPrograms([]);
      return;
    }
    let isMounted = true;
    const fetchPrograms = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/hmis/dhis2/programs?system=${system}`, { headers: authHeader() });
        if (res.ok && isMounted) {
          const data = await res.json();
          const list = data.programs || [];
          setPrograms(list);
          if (list.length > 0 && (!value || !list.some((p) => p.name === value || p.id === value))) {
            const preferred = filterKeyword
              ? list.find((p) => p.name.toLowerCase().includes(filterKeyword.toLowerCase())) || list[0]
              : list[0];
            onChange(preferred.id);
          }
        }
      } catch (err) {
        console.warn('Failed to load DHIS2 programs:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchPrograms();
    return () => {
      isMounted = false;
    };
  }, [system, authHeader, filterKeyword]);

  const selectedProg = useMemo(() => {
    return programs.find((p) => p.id === value || p.name === value);
  }, [programs, value]);

  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-teal-600 dark:text-teal-400" />
          {label}
        </span>
        {loading && <span className="text-xs text-teal-600 dark:text-teal-400 animate-pulse font-medium">Loading...</span>}
      </label>
      <select
        value={selectedProg ? selectedProg.id : (value || '')}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading}
        className="w-full py-2.5 px-3.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg text-sm font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-colors"
      >
        {programs.length === 0 ? (
          <option value={value || ''}>{value || 'Loading programs from server...'}</option>
        ) : (
          programs.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.id})
            </option>
          ))
        )}
      </select>
    </div>
  );
};

/**
 * Dhis2OrgUnitSelect
 */
export const Dhis2OrgUnitSelect = ({
  system = 'dhis2_online',
  value,
  onChange,
  ouMode,
  onOuModeChange,
  label = 'Facility / Hierarchy',
}) => {
  const { authHeader } = useAuth();
  const [orgUnits, setOrgUnits] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (!system) {
      setOrgUnits([]);
      return;
    }
    let isMounted = true;
    const fetchOrgUnits = async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/hmis/dhis2/org-units?system=${system}&limit=1000`, { headers: authHeader() });
        if (res.ok && isMounted) {
          const data = await res.json();
          const list = data.org_units || [];
          setOrgUnits(list);
        }
      } catch (err) {
        console.warn('Failed to load DHIS2 org units:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchOrgUnits();
    return () => {
      isMounted = false;
    };
  }, [system, authHeader]);

  const filtered = useMemo(() => {
    if (!search.trim()) return orgUnits.slice(0, 80);
    const q = search.toLowerCase();
    return orgUnits.filter((o) => o.name.toLowerCase().includes(q) || o.id.toLowerCase().includes(q)).slice(0, 100);
  }, [orgUnits, search]);

  const selectedOu = useMemo(() => {
    return orgUnits.find((o) => o.id === value || o.name === value);
  }, [orgUnits, value]);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center gap-2">
          <MapPin className="w-4 h-4 text-teal-600 dark:text-teal-400" />
          {label}
        </label>
        {onOuModeChange && (
          <div className="flex items-center gap-1.5 text-xs">
            <span className="text-slate-500 dark:text-slate-400 font-semibold">Mode:</span>
            <select
              value={ouMode || 'DESCENDANTS'}
              onChange={(e) => onOuModeChange(e.target.value)}
              className="px-2.5 py-1 bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-md text-xs font-semibold text-slate-700 dark:text-slate-300"
            >
              <option value="DESCENDANTS">Descendants</option>
              <option value="SELECTED">Selected Only</option>
              <option value="ACCESSIBLE">All Accessible</option>
            </select>
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        <div className="relative">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Type to filter facilities..."
            className="w-full pl-9 pr-3.5 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-slate-200 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500"
          />
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
        </div>

        <select
          value={selectedOu ? selectedOu.id : (value || '')}
          onChange={(e) => onChange(e.target.value)}
          disabled={loading}
          className="w-full py-2.5 px-3.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg text-sm font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-colors"
        >
          <option value="">All Accessible Units ({orgUnits.length} loaded)</option>
          {filtered.map((ou) => (
            <option key={ou.id} value={ou.id}>
              {ou.name} {ou.level ? `(L${ou.level})` : ''} ({ou.id})
            </option>
          ))}
        </select>
      </div>
    </div>
  );
};

/**
 * OpenmrsVisitTypeSelect
 */
export const OpenmrsVisitTypeSelect = ({
  value,
  onChange,
  defaultType = 'Delivery',
  label = 'Visit Type',
}) => {
  const { authHeader } = useAuth();
  const [types, setTypes] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const fetchTypes = async () => {
      setLoading(true);
      try {
        const res = await fetch('/api/hmis/openmrs/visit-types', { headers: authHeader() });
        if (res.ok && isMounted) {
          const data = await res.json();
          const list = data.visit_types || [];
          setTypes(list);
          if (!value && list.length > 0) {
            const match = list.find((t) => t.name.toLowerCase() === defaultType.toLowerCase()) || list[0];
            onChange(match.name);
          }
        }
      } catch (err) {
        console.warn('Failed to load OpenMRS visit types:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchTypes();
    return () => {
      isMounted = false;
    };
  }, [authHeader, defaultType]);

  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <Calendar className="w-4 h-4 text-teal-600 dark:text-teal-400" />
          {label}
        </span>
        {loading && <span className="text-xs text-teal-600 dark:text-teal-400 animate-pulse font-medium">Loading...</span>}
      </label>
      <select
        value={value || defaultType}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading}
        className="w-full py-2.5 px-3.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg text-sm font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-colors"
      >
        {types.length === 0 ? (
          <option value={defaultType}>{defaultType} (Default)</option>
        ) : (
          types.map((t) => (
            <option key={t.uuid || t.name} value={t.name}>
              {t.display || t.name}
            </option>
          ))
        )}
      </select>
    </div>
  );
};

/**
 * OpenmrsLocationSelect
 */
export const OpenmrsLocationSelect = ({
  value,
  onChange,
  label = 'Location / Ward (Optional)',
}) => {
  const { authHeader } = useAuth();
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let isMounted = true;
    const fetchLocations = async () => {
      setLoading(true);
      try {
        const res = await fetch('/api/hmis/openmrs/locations', { headers: authHeader() });
        if (res.ok && isMounted) {
          const data = await res.json();
          const list = data.locations || [];
          setLocations(list);
        }
      } catch (err) {
        console.warn('Failed to load OpenMRS locations:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchLocations();
    return () => {
      isMounted = false;
    };
  }, [authHeader]);

  return (
    <div className="space-y-1.5">
      <label className="block text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <MapPin className="w-4 h-4 text-teal-600 dark:text-teal-400" />
          {label}
        </span>
        {loading && <span className="text-xs text-teal-600 dark:text-teal-400 animate-pulse font-medium">Loading...</span>}
      </label>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading}
        className="w-full py-2.5 px-3.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg text-sm font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-colors"
      >
        <option value="">All Locations / Entire Facility ({locations.length} available)</option>
        {locations.map((loc) => (
          <option key={loc.uuid} value={loc.name}>
            {loc.display || loc.name}
          </option>
        ))}
      </select>
    </div>
  );
};

/**
 * MohDataElementSelect
 */
export const MohDataElementSelect = ({
  system = 'dhis2_moh',
  value,
  onChange,
  label = 'MOH Aggregate Data Element',
}) => {
  const { authHeader } = useAuth();
  const [elements, setElements] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (!system) {
      setElements([]);
      return;
    }
    let isMounted = true;
    const fetchElements = async () => {
      setLoading(true);
      try {
        const queryParam = search.trim() ? `&query=${encodeURIComponent(search.trim())}` : '';
        const res = await fetch(`/api/hmis/dhis2/data-elements?system=${system}${queryParam}&limit=100`, {
          headers: authHeader(),
        });
        if (res.ok && isMounted) {
          const data = await res.json();
          setElements(data.data_elements || []);
        }
      } catch (err) {
        console.warn('Failed to load DHIS2 data elements:', err);
      } finally {
        if (isMounted) setLoading(false);
      }
    };
    fetchElements();
    return () => {
      isMounted = false;
    };
  }, [system, search, authHeader]);

  return (
    <div className="space-y-2">
      <label className="block text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <Database className="w-4 h-4 text-teal-600 dark:text-teal-400" />
          {label}
        </span>
        {loading && <span className="text-xs text-teal-600 dark:text-teal-400 animate-pulse font-medium">Searching...</span>}
      </label>

      <div className="space-y-2">
        <div className="relative">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search data elements in DHIS2..."
            className="w-full pl-8 pr-3 py-2 bg-slate-50 dark:bg-slate-950 border border-slate-300 dark:border-slate-700 rounded-lg text-xs text-slate-900 dark:text-slate-200 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500"
          />
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" />
        </div>

        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full py-2.5 px-3.5 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-lg text-sm font-medium text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500 transition-colors"
        >
          {value && !elements.find((el) => el.id === value) && (
            <option value={value}>{value} (Selected UID)</option>
          )}
          {elements.map((el) => (
            <option key={el.id} value={el.id}>
              {el.name} ({el.id})
            </option>
          ))}
        </select>
      </div>
    </div>
  );
};

/**
 * MappingFileSelect
 */
export const MappingFileSelect = ({
  value,
  onChange,
  onUploaded,
  label = 'Facility Mapping File',
}) => {
  const { authHeader } = useAuth();
  const { showToast } = useToast();
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  const fetchFiles = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/hmis/mapping-files', { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        const list = data.mapping_files || [];
        setFiles(list);
        if (!value && list.length > 0) {
          const def = list.find((f) => f.is_default) || list[0];
          onChange(def.filename);
        }
      }
    } catch (err) {
      console.warn('Failed to load mapping files:', err);
    } finally {
      setLoading(false);
    }
  }, [authHeader, value, onChange]);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch('/api/hmis/upload', {
        method: 'POST',
        headers: authHeader(),
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      showToast(`Uploaded mapping file: ${data.filename}`, 'success');
      await fetchFiles();
      onChange(data.filename);
      if (onUploaded) onUploaded(data.filename);
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
          <FileSpreadsheet className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />
          {label}
        </label>
        <label className="text-xs text-teal-600 dark:text-teal-400 hover:underline cursor-pointer font-medium">
          {uploading ? 'Uploading...' : '+ Upload Custom'}
          <input
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={handleUpload}
            disabled={uploading}
            className="hidden"
          />
        </label>
      </div>

      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading || uploading}
        className="w-full px-3 py-2 bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 rounded-md text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-teal-500"
      >
        {files.length === 0 ? (
          <option value={value || 'Maternal aggregate.xlsx'}>Maternal aggregate.xlsx (Default)</option>
        ) : (
          files.map((f) => (
            <option key={f.filename} value={f.filename}>
              {f.filename} {f.location === 'template' ? '(Template)' : '(Uploaded)'}
            </option>
          ))
        )}
      </select>
    </div>
  );
};
