import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Database,
  Eye,
  Play,
  HardDrive,
  Globe,
  RefreshCw,
  Search,
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
  FileDropzone,
  JobPanel,
  ConfirmDialog,
  Badge,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

const PROGRAM_ID = 'pLk3Ht2XMKl';
const PROGRAM_NAME = 'Newborn Inpatient Data';

/**
 * DHIS to REDCap Sync Page
 */
const RedcapImportPage = () => {
  const { user } = useAuth();
  const isViewer = user?.role === 'viewer';
  const { showToast } = useToast();
  const {
    uploadFile,
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

  const [sourceInstance, setSourceInstance] = useState(null);
  const [orgUnits, setOrgUnits] = useState([]);
  const [loadingOrgUnits, setLoadingOrgUnits] = useState(false);
  const [orgSearchQuery, setOrgSearchQuery] = useState('');
  const [orgUnitId, setOrgUnitId] = useState('xKpOsRLDIsG');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [templateFile, setTemplateFile] = useState(null);

  const [showOverrides, setShowOverrides] = useState(false);
  const [customDhisUrl, setCustomDhisUrl] = useState('');
  const [customDhisUser, setCustomDhisUser] = useState('');
  const [customDhisPass, setCustomDhisPass] = useState('');
  const [customRedcapUrl, setCustomRedcapUrl] = useState('');
  const [customRedcapToken, setCustomRedcapToken] = useState('');

  const [loading, setLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const fetchOrgUnits = useCallback(async (instanceKey) => {
    setLoadingOrgUnits(true);
    try {
      const res = await fetch(`/api/data-management/dhis2/org-units?system=${instanceKey}`, {
        headers: authHeader(),
      });
      if (res.ok) {
        const data = await res.json();
        const list = data.org_units || [];
        setOrgUnits(list);
        if (list.length > 0 && !list.some((o) => o.id === orgUnitId)) {
          setOrgUnitId(list[0].id);
        }
      }
    } catch (err) {
      console.warn('Failed to load DHIS2 facilities for REDCap:', err);
    } finally {
      setLoadingOrgUnits(false);
    }
  }, [authHeader, orgUnitId]);

  useEffect(() => {
    if (sourceInstance) {
      fetchOrgUnits(sourceInstance);
    } else {
      setOrgUnits([]);
      setOrgUnitId('');
    }
  }, [sourceInstance, fetchOrgUnits]);

  const filteredOrgUnits = useMemo(() => {
    if (!orgSearchQuery.trim()) return orgUnits;
    const q = orgSearchQuery.toLowerCase().trim();
    return orgUnits.filter((ou) => {
      const name = (ou.displayName || ou.name || ou.display || '').toLowerCase();
      const id = (ou.id || '').toLowerCase();
      return name.includes(q) || id.includes(q);
    });
  }, [orgUnits, orgSearchQuery]);

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
    if (!sourceInstance) {
      showToast('Please select a source DHIS2 instance (Offline or Online)', 'warning');
      return false;
    }
    if (!orgUnitId) {
      showToast('Please select a target facility / organisation unit', 'warning');
      return false;
    }
    if (startDate && endDate && startDate > endDate) {
      showToast('Start date cannot be after End date', 'warning');
      return false;
    }
    return true;
  };

  const buildPayload = async () => {
    let uploadedTemplatePath = null;
    if (templateFile) {
      try {
        const up = await uploadFile(templateFile);
        uploadedTemplatePath = up.filepath;
      } catch (e) {
        console.warn('Could not upload optional template file, proceeding with auto-headers:', e);
      }
    }

    const payload = {
      source_instance: sourceInstance,
      org_unit_id: orgUnitId,
      program_id: PROGRAM_ID,
      start_date: startDate || undefined,
      end_date: endDate || undefined,
      template_path: uploadedTemplatePath || undefined,
    };

    if (showOverrides) {
      if (customDhisUrl) payload.custom_dhis_url = customDhisUrl;
      if (customDhisUser) payload.custom_dhis_user = customDhisUser;
      if (customDhisPass) payload.custom_dhis_pass = customDhisPass;
      if (customRedcapUrl) payload.custom_redcap_url = customRedcapUrl;
      if (customRedcapToken) payload.custom_redcap_token = customRedcapToken;
    }

    return payload;
  };

  const handleDryRun = async () => {
    if (!validateInputs()) return;
    setLoading(true);
    try {
      const payload = await buildPayload();
      const res = await fetch('/api/data-management/redcap-import/dry-run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'REDCap preview failed'));
      subscribeToJob(data.job_id);
      showToast(`Generating REDCap transform preview #${data.job_id}`, 'info');
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
      const payload = await buildPayload();
      const res = await fetch('/api/data-management/redcap-import/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'REDCap sync failed to start'));
      subscribeToJob(data.job_id);
      showToast(`Started DHIS to REDCap sync job #${data.job_id}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
      setShowConfirm(false);
    }
  };

  const activeDhisConn = sourceInstance === 'dhis2_offline' ? vaultConns?.offline : vaultConns?.online;
  const redcapConn = vaultConns?.redcap;
  const sourceName = sourceInstance === 'dhis2_offline' ? 'Offline DHIS2' : 'Online DHIS2';
  const selectedFacilityObj = orgUnits.find((o) => o.id === orgUnitId);
  const facilityDisplayName = selectedFacilityObj?.displayName || selectedFacilityObj?.name || orgUnitId;

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="DHIS to REDCap Synchronization"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'DHIS to REDCap' },
        ]}
      />

      <Card>
        <CardContent className="space-y-6">
          {/* Source Instance Selector */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
                Source DHIS2 Instance → Destination REDCap eCRF
              </label>
              <Badge variant="teal">Program: {PROGRAM_NAME}</Badge>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSourceInstance('dhis2_offline')}
                className={`p-2.5 rounded-lg border text-left flex items-center justify-between transition-all ${
                  sourceInstance === 'dhis2_offline'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <HardDrive className="w-4 h-4 text-amber-500 shrink-0" />
                  <div>
                    <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 block">Offline DHIS2</span>
                    <span className="font-mono text-[10px] text-slate-500 truncate block max-w-[220px]">
                      {vaultConns?.offline?.effective_url || 'http://localhost:8080'}
                    </span>
                  </div>
                </div>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {vaultConns?.offline?.source === 'env' ? 'Env' : 'Vault'}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSourceInstance('dhis2_online')}
                className={`p-2.5 rounded-lg border text-left flex items-center justify-between transition-all ${
                  sourceInstance === 'dhis2_online'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Globe className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <div>
                    <span className="font-semibold text-xs text-slate-800 dark:text-slate-100 block">Online DHIS2</span>
                    <span className="font-mono text-[10px] text-slate-500 truncate block max-w-[220px]">
                      {vaultConns?.online?.effective_url || 'https://central.dhis2.org'}
                    </span>
                  </div>
                </div>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {vaultConns?.online?.source === 'env' ? 'Env' : 'Vault'}
                </span>
              </button>
            </div>
          </div>

          {/* Facility & Date Filters */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <TextInput
              id="facility_search"
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
              disabled={loadingOrgUnits}
            />

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
                  : [{ value: '', label: loadingOrgUnits ? 'Loading...' : 'No matches' }]
              }
            />

            <TextInput
              type="date"
              label="Start Date (Optional)"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />

            <TextInput
              type="date"
              label="End Date (Optional)"
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

          {/* Optional REDCap Template Dropzone */}
          <div className="pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                REDCap CSV Mapping Template (Optional)
              </label>
              {templateFile && (
                <button
                  type="button"
                  onClick={() => setTemplateFile(null)}
                  className="text-xs text-slate-400 hover:text-slate-600"
                >
                  Clear Template
                </button>
              )}
            </div>
            <FileDropzone
              accept=".csv"
              maxSize={50 * 1024 * 1024}
              value={templateFile}
              onChange={setTemplateFile}
            />
          </div>

          {/* Advanced Accordion */}
          <div className="pt-2 border-t border-slate-100 dark:border-slate-800">
            <button
              type="button"
              onClick={() => setShowOverrides(!showOverrides)}
              className="flex items-center justify-between w-full text-xs font-semibold text-slate-700 dark:text-slate-300 py-1"
            >
              <span>Custom Endpoint & Token Overrides (Optional)</span>
              {showOverrides ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>

            {showOverrides && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2 pt-2">
                <TextInput
                  label="Custom DHIS2 URL"
                  placeholder={activeDhisConn?.base_url || 'http://localhost:8080/dhis'}
                  value={customDhisUrl}
                  onChange={(e) => setCustomDhisUrl(e.target.value)}
                />
                <TextInput
                  label="Custom DHIS2 Username"
                  placeholder={activeDhisConn?.username || 'admin'}
                  value={customDhisUser}
                  onChange={(e) => setCustomDhisUser(e.target.value)}
                />
                <TextInput
                  type="password"
                  label="Custom DHIS2 Password"
                  placeholder="••••••••"
                  value={customDhisPass}
                  onChange={(e) => setCustomDhisPass(e.target.value)}
                />
                <TextInput
                  label="Custom REDCap API URL"
                  placeholder={redcapConn?.base_url || 'https://redcap.example.org/api/'}
                  value={customRedcapUrl}
                  onChange={(e) => setCustomRedcapUrl(e.target.value)}
                />
                <TextInput
                  type="password"
                  label="Custom REDCap API Token"
                  placeholder="API token"
                  value={customRedcapToken}
                  onChange={(e) => setCustomRedcapToken(e.target.value)}
                />
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="secondary"
              icon={<Eye className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={!sourceInstance || !orgUnitId || isViewer}
              onClick={handleDryRun}
            >
              Validate & Preview (Dry-Run)
            </Button>
            <Button
              variant="primary"
              icon={<Database className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={!sourceInstance || !orgUnitId || isViewer}
              onClick={() => {
                if (validateInputs()) setShowConfirm(true);
              }}
            >
              Start REDCap Sync
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
        title="DHIS to REDCap Sync Progress"
      />

      <ConfirmDialog
        open={showConfirm}
        targetSystem="redcap"
        title="Confirm DHIS to REDCap Sync"
        message={`Extract newborn records from ${sourceName} for facility "${facilityDisplayName}" and commit transformed eCRFs into REDCap?`}
        confirmText="Confirm & Synchronize"
        onConfirm={handleCommit}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default RedcapImportPage;
