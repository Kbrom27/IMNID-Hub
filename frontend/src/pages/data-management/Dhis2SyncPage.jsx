import React, { useState, useEffect, useMemo } from 'react';
import {
  RefreshCw,
  ArrowRightLeft,
  Eye,
  Play,
  Upload,
  Download,
  Search,
  X,
  CheckSquare,
  Square,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardContent,
  Button,
  Select,
  DateInput,
  TextInput,
  Switch,
  JobPanel,
  ConfirmDialog,
  Alert,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

const DEFAULT_PROGRAMS = [
  { id: 'pLk3Ht2XMKl', name: 'Newborn Inpatient Data' },
  { id: 'aLoraiFNkng', name: 'Maternal Inpatient Data' },
  { id: 'QYJKpoUeg9F', name: 'Neonatal Care Form' },
];

/**
 * DHIS2 Direct Synchronization Page
 */
const Dhis2SyncPage = () => {
  const { user } = useAuth();
  const isViewer = user?.role === 'viewer';
  const { showToast } = useToast();
  const {
    authHeader,
    vaultConns,
    subscribeToJob,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    cancelActiveJob,
    resetJob,
  } = useDataManagementJob();

  const [direction, setDirection] = useState(null);

  const [showOverrides, setShowOverrides] = useState(false);
  const [customSourceUrl, setCustomSourceUrl] = useState('');
  const [customSourceUser, setCustomSourceUser] = useState('');
  const [customSourcePass, setCustomSourcePass] = useState('');
  const [customTargetUrl, setCustomTargetUrl] = useState('');
  const [customTargetUser, setCustomTargetUser] = useState('');
  const [customTargetPass, setCustomTargetPass] = useState('');

  const [programs, setPrograms] = useState([]);
  const [selectedPrograms, setSelectedPrograms] = useState([]);
  const [orgUnits, setOrgUnits] = useState([]);
  const [orgSearchQuery, setOrgSearchQuery] = useState('');
  const [loadingMetadata, setLoadingMetadata] = useState(false);
  const [metadataError, setMetadataError] = useState('');

  const [orgMode, setOrgMode] = useState('ALL');
  const [orgUnitId, setOrgUnitId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const sourceSystemKey = direction === 'offline_to_online' ? 'dhis2_offline' : direction === 'online_to_offline' ? 'dhis2_online' : null;

  const sourceInfo =
    direction === 'offline_to_online'
      ? vaultConns?.offline || { base_url: 'http://localhost:8080', username: 'admin' }
      : vaultConns?.online || { base_url: 'https://central.dhis2.org', username: 'admin' };

  const targetInfo =
    direction === 'offline_to_online'
      ? vaultConns?.online || { base_url: 'https://central.dhis2.org', username: 'admin' }
      : vaultConns?.offline || { base_url: 'http://localhost:8080', username: 'admin' };

  const fetchMetadata = async (systemKey) => {
    setLoadingMetadata(true);
    setMetadataError('');
    try {
      const pRes = await fetch(`/api/data-management/dhis2/programs?system=${systemKey}`, {
        headers: authHeader(),
      });
      if (pRes.ok) {
        const pData = await pRes.json();
        if (pData.programs && pData.programs.length > 0) {
          setPrograms(pData.programs);
          setSelectedPrograms((prev) => {
            if (prev.length > 0 && pData.programs.some((p) => prev.includes(p.id))) {
              return prev.filter((id) => pData.programs.some((p) => p.id === id));
            }
            return [pData.programs[0].id];
          });
        } else {
          setPrograms([]);
          setSelectedPrograms([]);
        }
      } else {
        setPrograms([]);
        setSelectedPrograms([]);
      }

      const ouRes = await fetch(`/api/data-management/dhis2/org-units?system=${systemKey}`, {
        headers: authHeader(),
      });
      if (ouRes.ok) {
        const ouData = await ouRes.json();
        const ous = ouData.org_units || [];
        setOrgUnits(ous);
        if (ous.length > 0 && !ous.some((ou) => ou.id === orgUnitId)) {
          setOrgUnitId(ous[0].id);
        }
      }
    } catch (err) {
      console.warn('Failed to load DHIS2 sync metadata:', err);
      setMetadataError('Could not fetch live metadata from selected source.');
      setPrograms([]);
      setSelectedPrograms([]);
    } finally {
      setLoadingMetadata(false);
    }
  };

  useEffect(() => {
    if (sourceSystemKey) {
      fetchMetadata(sourceSystemKey);
    } else {
      setPrograms([]);
      setSelectedPrograms([]);
      setOrgUnits([]);
      setOrgUnitId('');
    }
  }, [direction, sourceSystemKey]);

  const filteredOrgUnits = useMemo(() => {
    if (!orgSearchQuery.trim()) return orgUnits;
    const q = orgSearchQuery.toLowerCase().trim();
    return orgUnits.filter((ou) => {
      const name = (ou.name || ou.displayName || ou.display || '').toLowerCase();
      const id = (ou.id || '').toLowerCase();
      return name.includes(q) || id.includes(q);
    });
  }, [orgUnits, orgSearchQuery]);

  const handleSwap = () => {
    setDirection((prev) => (prev === 'offline_to_online' ? 'online_to_offline' : 'offline_to_online'));
  };

  const toggleProgram = (id) => {
    setSelectedPrograms((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    );
  };

  const selectAllPrograms = () => {
    setSelectedPrograms(programs.map((p) => p.id));
  };

  const deselectAllPrograms = () => {
    setSelectedPrograms([]);
  };

  const applyDatePreset = (preset) => {
    const today = new Date();
    const fmt = (d) => d.toISOString().split('T')[0];
    if (preset === 'all') {
      setStartDate('');
      setEndDate('');
    } else if (preset === 'last30') {
      const d = new Date();
      d.setDate(today.getDate() - 30);
      setStartDate(fmt(d));
      setEndDate(fmt(today));
    } else if (preset === 'month') {
      const d = new Date(today.getFullYear(), today.getMonth(), 1);
      setStartDate(fmt(d));
      setEndDate(fmt(today));
    } else if (preset === 'year') {
      const d = new Date(today.getFullYear(), 0, 1);
      setStartDate(fmt(d));
      setEndDate(fmt(today));
    }
  };

  const validateInputs = () => {
    if (!direction) {
      showToast('Please select a synchronization direction.', 'warning');
      return false;
    }
    if (selectedPrograms.length === 0) {
      showToast('Please select at least one tracker program to synchronize.', 'warning');
      return false;
    }
    if (orgMode === 'SPECIFIC' && !orgUnitId) {
      showToast('Please select a specific organization unit from the list.', 'warning');
      return false;
    }
    if (startDate && endDate && startDate > endDate) {
      showToast('Start date cannot be after End date.', 'warning');
      return false;
    }
    return true;
  };

  const buildPayload = () => {
    const selectedOu = orgMode === 'ALL' ? 'ALL' : orgUnitId;
    const primaryProgram = selectedPrograms[0] || '';
    const payload = {
      direction,
      org_unit_id: selectedOu,
      program_id: primaryProgram,
      program_ids: selectedPrograms,
      start_date: startDate,
      end_date: endDate,
    };
    if (showOverrides) {
      if (customSourceUrl) payload.source_url = customSourceUrl;
      if (customSourceUser) payload.source_user = customSourceUser;
      if (customSourcePass) payload.source_pass = customSourcePass;
      if (customTargetUrl) payload.target_url = customTargetUrl;
      if (customTargetUser) payload.target_user = customTargetUser;
      if (customTargetPass) payload.target_pass = customTargetPass;
    }
    return payload;
  };

  const handleDryRun = async () => {
    if (!validateInputs()) return;
    setLoading(true);
    try {
      const payload = buildPayload();
      const res = await fetch('/api/data-management/dhis2-sync/dry-run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Dry-run validation failed'));
      subscribeToJob(data.job_id);
      showToast(`Validating sync plan with dry-run #${data.job_id}`, 'info');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleCommit = async () => {
    if (!validateInputs()) return;
    setLoading(true);
    try {
      const payload = buildPayload();
      const res = await fetch('/api/data-management/dhis2-sync/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Sync failed to start'));
      subscribeToJob(data.job_id);
      showToast(`Started DHIS2 direct sync job #${data.job_id}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
      setShowConfirm(false);
    }
  };

  const dirLabel = direction === 'offline_to_online' ? 'Offline to Online DHIS2' : 'Online to Offline DHIS2';

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="DHIS2 Direct Synchronization"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'DHIS2 Direct Sync' },
        ]}
      />

      {metadataError && (
        <Alert variant="warning" title="Metadata Discovery Warning">
          {metadataError} Using default program and facility mappings.
        </Alert>
      )}

      <Card>
        <CardContent className="space-y-6">
          {/* Topology Direction Selector */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
                Synchronization Direction
              </label>
              <Button
                variant="ghost"
                size="sm"
                icon={<ArrowRightLeft className="w-4 h-4" />}
                onClick={handleSwap}
                className="text-xs h-8"
              >
                Swap Direction
              </Button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setDirection('offline_to_online')}
                className={`p-3 rounded-lg border text-left transition-all ${
                  direction === 'offline_to_online'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                    <Upload className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />
                    Push: Offline → Online
                  </span>
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                    Push
                  </span>
                </div>
                <div className="text-[11px] font-mono text-slate-500 truncate">
                  {vaultConns?.offline?.effective_url || 'http://localhost:8080'} → {vaultConns?.online?.effective_url || 'https://central.dhis2.org'}
                </div>
              </button>

              <button
                type="button"
                onClick={() => setDirection('online_to_offline')}
                className={`p-3 rounded-lg border text-left transition-all ${
                  direction === 'online_to_offline'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                    <Download className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />
                    Pull: Online → Offline
                  </span>
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                    Pull
                  </span>
                </div>
                <div className="text-[11px] font-mono text-slate-500 truncate">
                  {vaultConns?.online?.effective_url || 'https://central.dhis2.org'} → {vaultConns?.offline?.effective_url || 'http://localhost:8080'}
                </div>
              </button>
            </div>
          </div>

          {/* Program Checklist */}
          <div className="space-y-1.5 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
                Programs to Sync ({selectedPrograms.length} of {programs.length})
              </label>
              {programs.length > 0 && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={selectAllPrograms}
                    className="text-xs text-teal-600 dark:text-teal-400 hover:underline font-medium"
                  >
                    All
                  </button>
                  <span className="text-slate-300 dark:text-slate-700">|</span>
                  <button
                    type="button"
                    onClick={deselectAllPrograms}
                    className="text-xs text-slate-400 hover:underline"
                  >
                    Clear
                  </button>
                </div>
              )}
            </div>

            {!sourceSystemKey ? (
              <div className="text-xs text-slate-500 italic p-3 text-center border border-dashed border-slate-200 dark:border-slate-800 rounded-lg">
                Select a synchronization direction above to load programs from the source instance
              </div>
            ) : loadingMetadata ? (
              <div className="text-xs text-slate-500 p-3 text-center animate-pulse">
                Loading programs from source DHIS2 instance...
              </div>
            ) : programs.length === 0 ? (
              <div className="text-xs text-slate-500 p-3 text-center border border-slate-200 dark:border-slate-800 rounded-lg">
                No tracker programs found on the selected source instance.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
                {programs.map((p) => {
                  const isChecked = selectedPrograms.includes(p.id);
                  return (
                    <div
                      key={p.id}
                      onClick={() => toggleProgram(p.id)}
                      className={`flex items-center gap-2 p-2 rounded-md border cursor-pointer transition text-left ${
                        isChecked
                          ? 'border-teal-500 bg-teal-50/40 dark:bg-teal-950/20 text-slate-900 dark:text-slate-100'
                          : 'border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/40'
                      }`}
                    >
                      <div className="flex-shrink-0">
                        {isChecked ? (
                          <CheckSquare className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />
                        ) : (
                          <Square className="w-3.5 h-3.5 text-slate-400" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1 truncate">
                        <span className="text-xs font-semibold truncate block">{p.displayName || p.name}</span>
                        <span className="text-[10px] font-mono text-slate-400 block">{p.id}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Org Unit & Dates */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <Select
              label="Organisation Unit Scope"
              value={orgMode}
              onChange={(e) => setOrgMode(e.target.value)}
              options={[
                { value: 'ALL', label: 'All Accessible Units' },
                { value: 'SPECIFIC', label: 'Specific Facility' },
              ]}
            />

            {orgMode === 'SPECIFIC' && (
              <TextInput
                id="sync_facility_search"
                label="Filter Facilities"
                placeholder="Type to filter..."
                leadingIcon={<Search className="w-3.5 h-3.5 text-slate-400" />}
                trailingIcon={
                  orgSearchQuery ? (
                    <button
                      type="button"
                      onClick={() => setOrgSearchQuery('')}
                      className="text-slate-400 hover:text-slate-600 p-0.5"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  ) : null
                }
                value={orgSearchQuery}
                onChange={(e) => setOrgSearchQuery(e.target.value)}
                disabled={loadingMetadata}
              />
            )}

            {orgMode === 'SPECIFIC' && (
              <div className="md:col-span-2">
                <Select
                  label={`Target Facility (${filteredOrgUnits.length} matches)`}
                  value={orgUnitId}
                  onChange={(e) => setOrgUnitId(e.target.value)}
                  options={
                    filteredOrgUnits.length > 0
                      ? filteredOrgUnits.map((o) => ({
                          value: o.id,
                          label: `${o.display || o.displayName || o.name} (${o.id})`,
                        }))
                      : [{ value: '', label: loadingMetadata ? 'Loading...' : 'No matches' }]
                  }
                />
              </div>
            )}

            <DateInput
              label="Enrollment Start Date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
            <DateInput
              label="Enrollment End Date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>

          <div className="flex flex-wrap gap-1.5 text-xs">
            <span className="text-slate-400 py-0.5 text-[11px] font-medium">Quick presets:</span>
            {['all', 'last30', 'month', 'year'].map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => applyDatePreset(p)}
                className="px-2 py-0.5 rounded text-[11px] bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 transition"
              >
                {p === 'all' ? 'All Time' : p === 'last30' ? 'Last 30 Days' : p === 'month' ? 'This Month' : 'This Year'}
              </button>
            ))}
          </div>

          <div className="pt-2 border-t border-slate-100 dark:border-slate-800">
            <Switch
              label="Custom connection overrides"
              checked={showOverrides}
              onChange={setShowOverrides}
            />
          </div>

          {showOverrides && (
            <div className="p-3 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <TextInput
                  label="Source URL"
                  value={customSourceUrl}
                  onChange={(e) => setCustomSourceUrl(e.target.value)}
                  placeholder="http://source:8080"
                />
                <TextInput
                  label="Source User"
                  value={customSourceUser}
                  onChange={(e) => setCustomSourceUser(e.target.value)}
                  placeholder="admin"
                />
                <TextInput
                  label="Source Pass"
                  type="password"
                  value={customSourcePass}
                  onChange={(e) => setCustomSourcePass(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <TextInput
                  label="Target URL"
                  value={customTargetUrl}
                  onChange={(e) => setCustomTargetUrl(e.target.value)}
                  placeholder="https://central:8080"
                />
                <TextInput
                  label="Target User"
                  value={customTargetUser}
                  onChange={(e) => setCustomTargetUser(e.target.value)}
                  placeholder="admin"
                />
                <TextInput
                  label="Target Pass"
                  type="password"
                  value={customTargetPass}
                  onChange={(e) => setCustomTargetPass(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className="flex items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="secondary"
              icon={<Eye className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={isViewer || !direction}
              onClick={handleDryRun}
            >
              Validate & Preview (Dry-Run)
            </Button>
            <Button
              variant="primary"
              icon={<Play className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={isViewer || !direction}
              onClick={() => setShowConfirm(true)}
            >
              Start Direct Synchronization
            </Button>
          </div>
        </CardContent>
      </Card>

      <JobPanel
        jobId={activeJobId}
        jobState={jobState}
        logs={liveLogs}
        isStreaming={isStreaming}
        onCancel={cancelActiveJob}
        onReset={resetJob}
        title="Sync Execution Progress"
      />

      <ConfirmDialog
        open={showConfirm}
        targetSystem={direction === 'online_to_offline' ? 'dhis2_offline' : 'dhis2_online'}
        title="Execute Real DHIS2 Direct Synchronization?"
        message={`This will execute real synchronization (${dirLabel}) between ${sourceInfo?.effective_url || sourceInfo?.base_url} and ${targetInfo?.effective_url || targetInfo?.base_url}. Records will be committed directly.`}
        confirmText="Confirm & Synchronize"
        onConfirm={handleCommit}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default Dhis2SyncPage;
