import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Link as LinkIcon,
  Eye,
  Search,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  HelpCircle,
  RefreshCw,
  Calendar,
  Layers,
  HardDrive,
  Globe,
  X,
  ChevronDown,
  ChevronUp,
  ShieldCheck,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardContent,
  Button,
  TextInput,
  Select,
  JobPanel,
  ConfirmDialog,
  Badge,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

/**
 * Standard relationship type UID for "Mother - Neonate"
 */
const RELATIONSHIP_TYPE_MOTHER_NEONATE = 'Mym9LgC6uWZ';
const DEFAULT_FUZZY_THRESHOLD = 0.85;

/**
 * Mother-Neonate Relationship Linker Page
 * Deterministic (MRN / Exact Name) & Fuzzy (Name + Date of Delivery) relationship linking
 * between Maternal Inpatient Data (MID) and Neonatal Care Form (NCF) in DHIS2.
 */
const MotherNeonateLinkerPage = () => {
  const { user } = useAuth();
  const isViewer = user?.role === 'viewer';
  const toast = useToast();
  const notify = useCallback((msg, variant = 'info') => {
    if (typeof toast?.showToast === 'function') {
      toast.showToast(msg, variant);
    } else if (variant === 'error' && typeof toast?.error === 'function') {
      toast.error(msg);
    } else if (variant === 'success' && typeof toast?.success === 'function') {
      toast.success(msg);
    } else if (variant === 'warning' && typeof toast?.warning === 'function') {
      toast.warning(msg);
    } else if (typeof toast?.info === 'function') {
      toast.info(msg);
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
  const [dhis2Instance, setDhis2Instance] = useState('dhis2_offline');
  const [connecting, setConnecting] = useState(false);
  const [connState, setConnState] = useState({
    connected: false,
    user: '',
    server: '',
    error: '',
  });

  const onlineInfo = vaultConns?.online;
  const offlineInfo = vaultConns?.offline;

  // ── Facility Scope & Metadata ──────────────────────────────────
  const [orgUnits, setOrgUnits] = useState([]);
  const [selectedOu, setSelectedOu] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [relationshipTypes, setRelationshipTypes] = useState([]);
  const [selectedRelType, setSelectedRelType] = useState(RELATIONSHIP_TYPE_MOTHER_NEONATE);

  // ── Date Filters & Matching Parameters ─────────────────────────
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [threshold, setThreshold] = useState(DEFAULT_FUZZY_THRESHOLD);

  // ── Advanced Overrides ─────────────────────────────────────────
  const [showOverrides, setShowOverrides] = useState(false);
  const [customUrl, setCustomUrl] = useState('');
  const [customUser, setCustomUser] = useState('');
  const [customPass, setCustomPass] = useState('');

  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);

  // Load Metadata (Org Units & Relationship Types)
  const handleLoadMetadata = useCallback(
    async (targetInstance = dhis2Instance) => {
      setConnecting(true);
      setConnState({ connected: false, user: '', server: '', error: '' });

      try {
        const payload = { system: targetInstance };
        if (showOverrides && customUrl) payload.server = customUrl;
        if (showOverrides && customUser) payload.username = customUser;
        if (showOverrides && customPass) payload.password = customPass;

        const res = await fetch('/api/data-management/mother-neonate/metadata', {
          method: 'POST',
          headers: { ...authHeader(), 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error(data.error || 'Failed to fetch DHIS2 metadata');
        }

        const list = data.org_units || [];
        const rTypes = data.relationship_types || [];
        setOrgUnits(list);
        setRelationshipTypes(rTypes);
        setConnState({
          connected: true,
          user: data.user,
          server: data.server,
          error: '',
        });

        if (list.length > 0) {
          setSelectedOu((prev) => (prev && list.some((ou) => ou.id === prev) ? prev : ''));
        }
        if (rTypes.length > 0) {
          const hasDefault = rTypes.some((r) => r.id === RELATIONSHIP_TYPE_MOTHER_NEONATE);
          if (hasDefault) {
            setSelectedRelType(RELATIONSHIP_TYPE_MOTHER_NEONATE);
          } else {
            setSelectedRelType(rTypes[0].id);
          }
        }
      } catch (err) {
        setConnState({
          connected: false,
          user: '',
          server: '',
          error: err.message,
        });
        setOrgUnits([]);
        setRelationshipTypes([]);
        notify(err.message, 'error');
      } finally {
        setConnecting(false);
      }
    },
    [dhis2Instance, showOverrides, customUrl, customUser, customPass, authHeader, notify]
  );

  useEffect(() => {
    handleLoadMetadata(dhis2Instance);
  }, [dhis2Instance, handleLoadMetadata]);

  // Filter facilities
  const filteredOrgUnits = useMemo(() => {
    if (!searchQuery.trim()) return orgUnits;
    const q = searchQuery.toLowerCase();
    return orgUnits.filter(
      (ou) =>
        ou.name?.toLowerCase().includes(q) ||
        ou.display?.toLowerCase().includes(q) ||
        ou.id?.toLowerCase().includes(q)
    );
  }, [orgUnits, searchQuery]);

  const selectedOuObj = useMemo(
    () => orgUnits.find((ou) => ou.id === selectedOu),
    [orgUnits, selectedOu]
  );

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
    if (!selectedOu) {
      notify('Please select a facility (Organisation Unit).', 'warning');
      return false;
    }
    if (startDate && endDate && startDate > endDate) {
      notify('Start Date must be before or equal to End Date.', 'error');
      return false;
    }
    return true;
  };

  const executeLinking = async (isDryRun) => {
    if (!validateInputs()) return;

    setLoading(true);
    try {
      const endpoint = isDryRun
        ? '/api/data-management/mother-neonate-linker/dry-run'
        : '/api/data-management/mother-neonate-linker/run';

      const payload = {
        system: dhis2Instance,
        org_unit_id: selectedOu,
        relationship_type_id: selectedRelType || RELATIONSHIP_TYPE_MOTHER_NEONATE,
        start_date: startDate || '',
        end_date: endDate || '',
        threshold: parseFloat(threshold) || DEFAULT_FUZZY_THRESHOLD,
        dry_run: isDryRun,
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
      if (!res.ok) {
        throw new Error(extractErrorMessage(data, 'Linking job dispatch failed'));
      }

      subscribeToJob(data.job_id);
      notify(
        isDryRun
          ? `Started Linking Dry-Run job #${data.job_id}`
          : `Started Mother-Neonate Linking job #${data.job_id}`,
        'info'
      );
    } catch (err) {
      notify(err.message, 'error');
    } finally {
      setLoading(false);
      setShowConfirm(false);
    }
  };

  const counters = jobState?.meta?.counters;
  const activeDhisConn = dhis2Instance === 'dhis2_offline' ? offlineInfo : onlineInfo;

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Mother-Neonate Relationship Linker"
        description="Link Maternal Inpatient Data (MID) and Neonatal Care Form (NCF) in DHIS2"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'Mother-Neonate Linker' },
        ]}
      />

      <Card>
        <CardContent className="space-y-5 p-6">
          {/* Target Instance Selection Header */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
                Target DHIS2 Instance
              </label>
              <Button
                variant="ghost"
                size="sm"
                icon={<RefreshCw className={`w-3.5 h-3.5 ${connecting ? 'animate-spin' : ''}`} />}
                loading={connecting}
                disabled={connecting}
                onClick={() => handleLoadMetadata(dhis2Instance)}
                className="text-xs h-7"
              >
                Reload Metadata
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
                      {offlineInfo?.effective_url || offlineInfo?.base_url || 'http://localhost:8080'}
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
                      {onlineInfo?.effective_url || onlineInfo?.base_url || 'https://imnid.online/dhis'}
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

          {/* Facility & Relationship Type Grid */}
          <div className="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
              Facility & Relationship Type
            </label>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <TextInput
                  placeholder="Filter facility by name or UID..."
                  leadingIcon={<Search className="w-4 h-4 text-teal-600" />}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  disabled={connecting || orgUnits.length === 0}
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
                />
                <Select
                  value={selectedOu}
                  onChange={(e) => setSelectedOu(e.target.value)}
                  disabled={connecting || orgUnits.length === 0}
                  placeholder={
                    connecting
                      ? 'Loading facilities...'
                      : filteredOrgUnits.length === 0
                      ? 'No matching facilities found'
                      : '-- Select Facility (Required) --'
                  }
                  options={filteredOrgUnits.map((ou) => ({
                    value: ou.id,
                    label: ou.display || ou.name,
                  }))}
                />
              </div>

              <div className="space-y-1.5">
                <Select
                  label="Relationship Type"
                  value={selectedRelType}
                  onChange={(e) => setSelectedRelType(e.target.value)}
                  disabled={connecting || relationshipTypes.length === 0}
                  options={relationshipTypes.map((rt) => ({
                    value: rt.id,
                    label: `${rt.name} (${rt.id})`,
                  }))}
                />
                {selectedRelType !== RELATIONSHIP_TYPE_MOTHER_NEONATE && (
                  <p className="text-[11px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                    Standard matching algorithm applies to "Mother - Neonate"
                  </p>
                )}
              </div>
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

          {/* Fuzzy Matching Threshold */}
          <div className="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="flex justify-between items-center">
              <label htmlFor="fuzzy-match-threshold" className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                Fuzzy Match Threshold (0.10 - 1.00)
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min="0.10"
                  max="1.00"
                  step="0.05"
                  value={threshold}
                  onChange={(e) => setThreshold(e.target.value)}
                  className="w-16 px-1.5 py-0.5 text-xs font-mono font-bold text-teal-700 dark:text-teal-400 bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-900 rounded text-center"
                />
                <button
                  type="button"
                  onClick={() => setThreshold(DEFAULT_FUZZY_THRESHOLD)}
                  className="text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 underline"
                >
                  Reset (0.85)
                </button>
              </div>
            </div>

            <input
              id="fuzzy-match-threshold"
              aria-label="Fuzzy Match Threshold"
              type="range"
              min="0.50"
              max="1.00"
              step="0.01"
              value={threshold}
              onChange={(e) => setThreshold(parseFloat(e.target.value))}
              className="w-full h-1.5 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-teal-600"
            />

            <div className="p-3 rounded-lg bg-slate-50/70 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-800 text-[11px] text-slate-600 dark:text-slate-400 space-y-1">
              <div className="flex items-center gap-1.5 font-semibold text-slate-800 dark:text-slate-200">
                <ShieldCheck className="w-3.5 h-3.5 text-teal-600 shrink-0" />
                Pipeline Priority:
              </div>
              <p>1. Maternal MRN Match (Priority 0) &bull; 2. Exact Full-Name Match (Priority 1) &bull; 3. Fuzzy Name Match &ge; {threshold} with Delivery Date confirmation &bull; 4. First-Name Fallback</p>
            </div>
          </div>

          {/* Overrides Accordion */}
          <div className="pt-2 border-t border-slate-100 dark:border-slate-800">
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

          {/* Action Buttons Right-Aligned */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="secondary"
              icon={<Eye className="w-4 h-4 mr-1.5 text-slate-600" />}
              loading={loading}
              disabled={isViewer || loading || !connState.connected || !selectedOu}
              onClick={() => executeLinking(true)}
            >
              Preview Matches (Dry-Run)
            </Button>
            <Button
              variant="primary"
              icon={<LinkIcon className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={isViewer || loading || !connState.connected || !selectedOu}
              onClick={() => {
                if (validateInputs()) {
                  setShowConfirm(true);
                }
              }}
            >
              Find & Link Mothers / Neonates
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Metrics Counters */}
      {counters && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="p-3.5 rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50/70 dark:bg-emerald-950/20">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-emerald-800 dark:text-emerald-300">
                Newly Linked
              </span>
              <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-emerald-700 dark:text-emerald-400 mt-1">
              {counters.linked ?? 0}
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-blue-200 dark:border-blue-900/50 bg-blue-50/70 dark:bg-blue-950/20">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-blue-800 dark:text-blue-300">
                Already Linked
              </span>
              <Layers className="w-4 h-4 text-blue-600 dark:text-blue-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-blue-700 dark:text-blue-400 mt-1">
              {counters.already_linked ?? 0}
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-amber-200 dark:border-amber-900/50 bg-amber-50/70 dark:bg-amber-950/20">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-amber-800 dark:text-amber-300">
                Unmatched
              </span>
              <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-amber-700 dark:text-amber-400 mt-1">
              {counters.unmatched ?? 0}
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/70 dark:bg-slate-900/40">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-slate-700 dark:text-slate-300">
                Missing Data
              </span>
              <HelpCircle className="w-4 h-4 text-slate-500" />
            </div>
            <div className="text-2xl font-bold font-mono text-slate-700 dark:text-slate-300 mt-1">
              {counters.skipped_no_mother_name ?? 0}
            </div>
          </div>

          <div className="p-3.5 rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50/70 dark:bg-rose-950/20 col-span-2 md:col-span-1">
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider font-semibold text-rose-800 dark:text-rose-300">
                Failed
              </span>
              <XCircle className="w-4 h-4 text-rose-600 dark:text-rose-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-rose-700 dark:text-rose-400 mt-1">
              {counters.failed ?? 0}
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
        title="Mother-Neonate Linking Progress"
      />

      {/* Confirmation Dialog */}
      <ConfirmDialog
        open={showConfirm}
        targetSystem={dhis2Instance}
        title="Execute Mother-Neonate Relationship Linking?"
        message={`This will match and create relationships in DHIS2 (${
          dhis2Instance === 'dhis2_offline' ? 'Offline' : 'Online'
        }) for facility "${selectedOuObj?.name || selectedOu}" with confidence threshold >= ${threshold}. Are you sure you want to proceed?`}
        confirmText="Confirm & Start Linking"
        onConfirm={() => executeLinking(false)}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default MotherNeonateLinkerPage;
