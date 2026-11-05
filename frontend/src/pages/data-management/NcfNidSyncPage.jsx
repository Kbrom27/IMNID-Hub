import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Database,
  Play,
  Eye,
  Search,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  PlusCircle,
  RefreshCw,
  Sliders,
  Calendar,
  Layers,
  ArrowRight,
  HardDrive,
  Globe,
  X,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardContent,
  Button,
  TextInput,
  Select,
  Switch,
  JobPanel,
  ConfirmDialog,
  Badge,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

/**
 * Program Identifiers
 */
const NCF_PROGRAM_ID = 'QYJKpoUeg9F';
const NCF_PROGRAM_NAME = 'Neonatal Care Form (NCF)';
const NID_PROGRAM_ID = 'pLk3Ht2XMKl';
const NID_PROGRAM_NAME = 'Newborn Inpatient Data (NID)';

/**
 * NCF to NID DHIS2 Tracker Sync Page
 * Synchronizes records from Neonatal Care Form (NCF) to Newborn Inpatient Data (NID).
 * Instance selection: Online or Offline (credentials pre-configured in Vault).
 */
const NcfNidSyncPage = () => {
  const { user } = useAuth();
  const isViewer = user?.role === 'viewer';
  const toast = useToast();
  const showToast = useCallback((msg, variant = 'info', title = null) => {
    if (typeof toast?.showToast === 'function') {
      toast.showToast(msg, variant, title);
    } else if (variant === 'error' && typeof toast?.error === 'function') {
      toast.error(msg, title);
    } else if (variant === 'success' && typeof toast?.success === 'function') {
      toast.success(msg, title);
    } else if (variant === 'warning' && typeof toast?.warning === 'function') {
      toast.warning(msg, title);
    } else if (typeof toast?.info === 'function') {
      toast.info(msg, title);
    } else if (typeof toast?.show === 'function') {
      toast.show({ message: msg, variant, title });
    }
  }, [toast]);
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

  // ── Instance selection (Online vs Offline) ─────────────────────
  const [dhis2Instance, setDhis2Instance] = useState(null);
  const [connecting, setConnecting] = useState(false);
  const [connState, setConnState] = useState({
    connected: false,
    user: '',
    server: '',
    error: '',
  });

  const onlineInfo = vaultConns?.online;
  const offlineInfo = vaultConns?.offline;

  // ── Facility Scope & Filters ───────────────────────────────────
  const [orgUnits, setOrgUnits] = useState([]);
  const [orgMode, setOrgMode] = useState('ALL'); // 'ALL' or 'SPECIFIC'
  const [selectedOu, setSelectedOu] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  // ── Options state ─────────────────────────────────────────────
  const [verbose, setVerbose] = useState(false);
  const [showOverrides, setShowOverrides] = useState(false);
  const [customUrl, setCustomUrl] = useState('');
  const [customUser, setCustomUser] = useState('');
  const [customPass, setCustomPass] = useState('');

  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);

  // Connect & Load Org Units for the chosen instance
  const handleLoadOrgUnits = useCallback(async (targetInstance = dhis2Instance) => {
    setConnecting(true);
    setConnState({ connected: false, user: '', server: '', error: '' });

    try {
      const payload = { system: targetInstance };
      if (showOverrides && customUrl) payload.server = customUrl;
      if (showOverrides && customUser) payload.username = customUser;
      if (showOverrides && customPass) payload.password = customPass;

      const res = await fetch('/api/data-management/ncf-nid/connect', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Connection failed');
      }

      const list = data.org_units || [];
      setOrgUnits(list);
      setConnState({
        connected: true,
        user: data.user,
        server: data.server,
        error: '',
      });

      if (list.length > 0) {
        setSelectedOu((prev) => (prev && list.some((ou) => ou.id === prev) ? prev : ''));
      }
    } catch (err) {
      setConnState({
        connected: false,
        user: '',
        server: '',
        error: err.message,
      });
      setOrgUnits([]);
      showToast(err.message, 'error');
    } finally {
      setConnecting(false);
    }
  }, [dhis2Instance, showOverrides, customUrl, customUser, customPass, authHeader, showToast]);

  // Auto-connect and load org units when instance changes (only if selected)
  useEffect(() => {
    if (dhis2Instance) {
      handleLoadOrgUnits(dhis2Instance);
    } else {
      setOrgUnits([]);
      setConnState({ connected: false, user: '', server: '', error: '' });
    }
  }, [dhis2Instance, handleLoadOrgUnits]);

  // Filter org units based on search input
  const filteredOrgUnits = useMemo(() => {
    if (!searchQuery.trim()) return orgUnits;
    const q = searchQuery.toLowerCase();
    return orgUnits.filter(
      (ou) =>
        ou.name?.toLowerCase().includes(q) ||
        ou.displayName?.toLowerCase().includes(q) ||
        ou.id?.toLowerCase().includes(q)
    );
  }, [orgUnits, searchQuery]);

  // Quick Date Range Presets
  const applyDatePreset = (preset) => {
    const today = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    if (preset === 'all') {
      setStartDate('');
      setEndDate('');
    } else if (preset === 'last30') {
      const d = new Date();
      d.setDate(d.getDate() - 30);
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
    if (!dhis2Instance) {
      showToast('Please select a target DHIS2 instance (Online or Offline).', 'warning');
      return false;
    }
    if (orgMode === 'SPECIFIC' && !selectedOu) {
      showToast('Please select a specific organization unit from the list.', 'warning');
      return false;
    }
    if (startDate && endDate && startDate > endDate) {
      showToast('Start Date must be before or equal to End Date', 'error');
      return false;
    }
    return true;
  };

  const executeSync = async (isDryRun) => {
    if (!validateInputs()) return;

    setLoading(true);
    try {
      const endpoint = isDryRun
        ? '/api/data-management/ncf-nid-sync/dry-run'
        : '/api/data-management/ncf-nid-sync/run';

      const targetOu = orgMode === 'ALL' ? null : selectedOu || null;

      const payload = {
        system: dhis2Instance,
        org_unit_id: targetOu,
        start_date: startDate || '',
        end_date: endDate || '',
        dry_run: isDryRun,
        verbose: verbose,
      };

      if (showOverrides) {
        if (customUrl) payload.dhis2_url = customUrl;
        if (customUser) payload.username = customUser;
        if (customPass) payload.password = customPass;
      }

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Failed to submit NCF to NID sync job'));

      subscribeToJob(data.job_id);
      showToast(
        isDryRun
          ? `NCF to NID preview job #${data.job_id} submitted`
          : `Started NCF to NID sync job #${data.job_id}`,
        'info'
      );
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
      setShowConfirm(false);
    }
  };

  const counters = jobState?.meta?.counters || null;
  const activeDhisConn = dhis2Instance === 'dhis2_offline' ? offlineInfo : onlineInfo;
  const instanceName = dhis2Instance === 'dhis2_offline' ? 'Offline DHIS2' : 'Online DHIS2';
  const selectedFacilityObj = orgUnits.find((o) => o.id === selectedOu);
  const facilityDisplayName = orgMode === 'ALL'
    ? 'All Accessible Facilities'
    : selectedFacilityObj?.displayName || selectedFacilityObj?.name || selectedOu;

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="NCF to NID Sync"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'NCF to NID Sync' },
        ]}
      />

      <Card>
        <CardContent className="space-y-6">
          {/* Target Instance Selection Header */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
                DHIS2 Target Instance
              </label>
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw className={`w-3.5 h-3.5 ${connecting ? 'animate-spin' : ''}`} />}
                loading={connecting}
                disabled={connecting || !dhis2Instance}
                onClick={() => dhis2Instance && handleLoadOrgUnits(dhis2Instance)}
                className="text-xs h-7"
              >
                Reload Facilities
              </Button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setDhis2Instance('dhis2_offline')}
                className={`p-3 rounded-lg border text-left flex items-center justify-between transition-all ${
                  dhis2Instance === 'dhis2_offline'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <HardDrive className="w-4 h-4 text-amber-500 shrink-0" />
                  <div>
                    <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 block">Offline DHIS2</span>
                    <span className="font-mono text-[10px] text-slate-500 truncate block max-w-[220px]">
                      {offlineInfo?.effective_url || 'http://localhost:8080'}
                    </span>
                  </div>
                </div>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {offlineInfo?.source === 'env' ? 'Env' : 'Vault'}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setDhis2Instance('dhis2_online')}
                className={`p-3 rounded-lg border text-left flex items-center justify-between transition-all ${
                  dhis2Instance === 'dhis2_online'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Globe className="w-4 h-4 text-emerald-600 shrink-0" />
                  <div>
                    <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 block">Online DHIS2</span>
                    <span className="font-mono text-[10px] text-slate-500 truncate block max-w-[220px]">
                      {onlineInfo?.effective_url || 'https://central.dhis2.org'}
                    </span>
                  </div>
                </div>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {onlineInfo?.source === 'env' ? 'Env' : 'Vault'}
                </span>
              </button>
            </div>

            {/* Connection Status Pill */}
            {connState.connected ? (
              <div className="flex items-center gap-2 text-xs text-emerald-700 dark:text-emerald-400 font-medium bg-emerald-50/60 dark:bg-emerald-950/20 px-3 py-1.5 rounded-lg border border-emerald-200 dark:border-emerald-900/30">
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                <span>
                  Connected as <strong>{connState.user}</strong> ({orgUnits.length} facilities loaded)
                </span>
              </div>
            ) : connState.error ? (
              <div className="flex items-center gap-2 text-xs text-rose-600 dark:text-rose-400 font-medium bg-rose-50/60 dark:bg-rose-950/20 px-3 py-1.5 rounded-lg border border-rose-200 dark:border-rose-900/30">
                <XCircle className="w-3.5 h-3.5 shrink-0" />
                <span>{connState.error}</span>
              </div>
            ) : null}
          </div>

          {/* Program Transformation Banner */}
          <div className="p-3 rounded-lg bg-slate-50/70 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-800 dark:text-slate-200">
              <span className="font-semibold">{NCF_PROGRAM_NAME}</span>
              <ArrowRight className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400 shrink-0" />
              <span className="font-semibold">{NID_PROGRAM_NAME}</span>
            </div>
            <div className="text-[11px] text-slate-500 font-mono">
              Key: Record ID (Xam97lYmJB7 ↔ UGwDTPoObkT)
            </div>
          </div>

          {/* Scope & Facility Filters */}
          <div className="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
              Facility Scope & Filters
            </label>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Select
                label="Organization Unit Scope"
                value={orgMode}
                onChange={(e) => setOrgMode(e.target.value)}
                options={[
                  { value: 'ALL', label: 'All Accessible Facilities' },
                  { value: 'SPECIFIC', label: 'Specific Organization Unit' },
                ]}
              />

              {orgMode === 'SPECIFIC' && (
                <TextInput
                  id="ncf_facility_search"
                  label="Search Facilities"
                  placeholder="Filter by facility name or UID..."
                  leadingIcon={<Search className="w-4 h-4 text-teal-600" />}
                  trailingIcon={
                    searchQuery ? (
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    ) : null
                  }
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  disabled={connecting}
                />
              )}

              {orgMode === 'SPECIFIC' && (
                <div className="md:col-span-2">
                  <Select
                    label={`Target Facility (${filteredOrgUnits.length} available)`}
                    value={selectedOu}
                    onChange={(e) => setSelectedOu(e.target.value)}
                    options={
                      filteredOrgUnits.length > 0
                        ? [
                            { value: '', label: '— Select a facility —' },
                            ...filteredOrgUnits.map((o) => ({
                              value: o.id,
                              label: `${o.display || o.displayName || o.name} (${o.id})`,
                            })),
                          ]
                        : [
                            {
                              value: '',
                              label: connecting ? 'Loading facilities...' : 'No matching facilities found',
                            },
                          ]
                    }
                  />
                </div>
              )}
            </div>
          </div>

          {/* Date Range Filtering */}
          <div className="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5">
              <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                <Calendar className="w-3.5 h-3.5 text-teal-600" />
                Enrollment Date Range (Optional)
              </label>
              <div className="flex items-center gap-1 text-[11px]">
                <button
                  type="button"
                  onClick={() => applyDatePreset('all')}
                  className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                >
                  All Time
                </button>
                <button
                  type="button"
                  onClick={() => applyDatePreset('last30')}
                  className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                >
                  Last 30 Days
                </button>
                <button
                  type="button"
                  onClick={() => applyDatePreset('month')}
                  className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                >
                  This Month
                </button>
                <button
                  type="button"
                  onClick={() => applyDatePreset('year')}
                  className="px-2 py-0.5 rounded bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
                >
                  This Year
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <TextInput
                type="date"
                label="Start Date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
              <TextInput
                type="date"
                label="End Date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </div>

          {/* Options & Overrides */}
          <div className="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <Switch
              id="verbose_toggle"
              label="Verbose Diagnostic Logging"
              helperText="Stream detailed field-by-field transformation traces into the job log"
              checked={verbose}
              onChange={setVerbose}
            />

            {/* Overrides Accordion */}
            <div className="pt-2">
              <button
                type="button"
                onClick={() => setShowOverrides(!showOverrides)}
                className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
              >
                {showOverrides ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                <span>Advanced: Custom DHIS2 Endpoint Overrides</span>
              </button>

              {showOverrides && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-3">
                  <TextInput
                    label="Custom DHIS2 URL"
                    placeholder={activeDhisConn?.base_url || 'http://localhost:8080'}
                    value={customUrl}
                    onChange={(e) => setCustomUrl(e.target.value)}
                  />
                  <TextInput
                    label="Custom DHIS2 Username"
                    placeholder={activeDhisConn?.username || 'admin'}
                    value={customUser}
                    onChange={(e) => setCustomUser(e.target.value)}
                  />
                  <TextInput
                    type="password"
                    label="Custom DHIS2 Password"
                    placeholder="••••••••"
                    value={customPass}
                    onChange={(e) => setCustomPass(e.target.value)}
                  />
                </div>
              )}
            </div>
          </div>

          {/* Action Buttons Centered */}
          <div className="flex items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="secondary"
              icon={<Eye className="w-4 h-4 mr-1.5 text-slate-600" />}
              loading={loading}
              disabled={isViewer || loading || !dhis2Instance}
              onClick={() => executeSync(true)}
            >
              Validate & Preview (Dry-Run)
            </Button>
            <Button
              variant="primary"
              icon={<Play className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={isViewer || loading || !dhis2Instance}
              onClick={() => {
                if (validateInputs()) {
                  setShowConfirm(true);
                }
              }}
            >
              Start NCF to NID Sync
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Metrics Counters */}
      {counters && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="p-3.5 rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50/70 dark:bg-emerald-950/20">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-emerald-800 dark:text-emerald-300">
                Updated
              </span>
              <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-emerald-700 dark:text-emerald-400 mt-1">
              {counters.updated ?? 0}
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-blue-200 dark:border-blue-900/50 bg-blue-50/70 dark:bg-blue-950/20">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-blue-800 dark:text-blue-300">
                Created
              </span>
              <PlusCircle className="w-4 h-4 text-blue-600 dark:text-blue-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-blue-700 dark:text-blue-400 mt-1">
              {counters.created ?? 0}
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-amber-200 dark:border-amber-900/50 bg-amber-50/70 dark:bg-amber-950/20">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-amber-800 dark:text-amber-300">
                Skipped
              </span>
              <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-amber-700 dark:text-amber-400 mt-1">
              {counters.skipped ?? 0}
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50/70 dark:bg-rose-950/20">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-rose-800 dark:text-rose-300">
                Errors
              </span>
              <XCircle className="w-4 h-4 text-rose-600 dark:text-rose-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-rose-700 dark:text-rose-400 mt-1">
              {counters.errors ?? 0}
            </div>
          </div>
        </div>
      )}

      {/* Live Job & Log Panel */}
      <JobPanel
        jobId={activeJobId}
        jobState={jobState}
        logs={liveLogs}
        isStreaming={isStreaming}
        onCancel={cancelActiveJob}
        onReset={resetJob}
        title="NCF to NID Sync Progress"
      />

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={showConfirm}
        targetSystem={dhis2Instance}
        title="Confirm NCF to NID Sync"
        message={`This will execute real intra-system synchronization of Neonatal Care Form records into Newborn Inpatient Data on ${instanceName} for "${facilityDisplayName}". Do you want to proceed?`}
        confirmText="Confirm & Synchronize"
        onConfirm={() => executeSync(false)}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default NcfNidSyncPage;
