import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Download, Globe, Laptop, Search, X } from 'lucide-react';
import {
  PageHeader,
  Card,
  CardContent,
  Button,
  Select,
  TextInput,
  DateInput,
  JobPanel,
  DirectoryPicker,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

/**
 * Data Export Page (DHIS2 Tracker Export for Syncing)
 */
const DataExportPage = () => {
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

  const [sourceInstance, setSourceInstance] = useState('dhis2_offline');
  const [programName, setProgramName] = useState('Maternal Inpatient Data');
  const [orgMode, setOrgMode] = useState('ALL');
  const [orgUnitId, setOrgUnitId] = useState('');
  const [orgUnits, setOrgUnits] = useState([]);
  const [loadingOrgUnits, setLoadingOrgUnits] = useState(false);
  const [orgSearchQuery, setOrgSearchQuery] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [eventStatusFilter, setEventStatusFilter] = useState('ALL');
  const [format, setFormat] = useState('csv');
  const [outputDir, setOutputDir] = useState('/data/exports');
  const [filename, setFilename] = useState('dhis2_export_sync.csv');
  const [loading, setLoading] = useState(false);

  const filteredOrgUnits = useMemo(() => {
    if (!orgSearchQuery.trim()) return orgUnits;
    const q = orgSearchQuery.toLowerCase().trim();
    return orgUnits.filter((ou) => {
      const name = (ou.name || ou.displayName || ou.display || '').toLowerCase();
      const id = (ou.id || '').toLowerCase();
      return name.includes(q) || id.includes(q);
    });
  }, [orgUnits, orgSearchQuery]);

  useEffect(() => {
    if (orgMode === 'SELECTED' && filteredOrgUnits.length > 0) {
      setOrgUnitId((prev) => (filteredOrgUnits.some((ou) => ou.id === prev) ? prev : filteredOrgUnits[0].id));
    }
  }, [filteredOrgUnits, orgMode]);

  const onlineInfo = vaultConns?.online;
  const offlineInfo = vaultConns?.offline;

  const programIds = {
    'Maternal Inpatient Data': 'aLoraiFNkng',
    'Newborn Inpatient Data': 'pLk3Ht2XMKl',
    'Neonatal care Form': 'QYJKpoUeg9F',
    'FINC': 'flBSKMXQloQ',
    'SLL Assist AI': 'yxRNHSagJmU',
  };

  const fetchOrgUnits = useCallback(async (system) => {
    setLoadingOrgUnits(true);
    try {
      const res = await fetch(`/api/data-management/dhis2/org-units?system=${system}`, {
        headers: authHeader(),
      });
      if (res.ok) {
        const data = await res.json();
        const ous = data.org_units || [];
        setOrgUnits(ous);
        setOrgUnitId((prev) => (ous.some((ou) => ou.id === prev) ? prev : ous[0]?.id || ''));
      }
    } catch (err) {
      console.warn('Failed to fetch org units for', system, err);
    } finally {
      setLoadingOrgUnits(false);
    }
  }, [authHeader]);

  useEffect(() => {
    fetchOrgUnits(sourceInstance);
  }, [sourceInstance, fetchOrgUnits]);

  const handleExport = async () => {
    if (orgMode === 'SELECTED' && !orgUnitId) {
      showToast('Please select a specific organisation unit before starting export', 'error');
      return;
    }
    setLoading(true);
    try {
      const payload = {
        source_instance: sourceInstance,
        program_name: programName,
        program_id: programIds[programName] || 'pLk3Ht2XMKl',
        org_unit_mode: orgMode,
        ou_mode: orgMode,
        org_unit_id: orgMode === 'SELECTED' ? orgUnitId : undefined,
        ou_ids: orgMode === 'SELECTED' && orgUnitId ? [orgUnitId] : [],
        start_date: startDate || undefined,
        end_date: endDate || undefined,
        status: statusFilter,
        status_filter: statusFilter,
        event_status: eventStatusFilter,
        event_status_filter: eventStatusFilter,
        format: format,
        output_format: format,
        output_dir: outputDir || undefined,
        filename: filename || undefined,
      };

      const res = await fetch('/api/data-management/data-export/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Export failed to start'));
      subscribeToJob(data.job_id);
      showToast(`Started sync export job #${data.job_id}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Data Export for Syncing"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'Sync Export' },
        ]}
      />

      <Card>
        <CardContent className="space-y-5 p-6">
          {/* Source Instance Selector */}
          <div className="space-y-2">
            <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
              Source DHIS2 Instance
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
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
                  <Laptop className="w-4 h-4 text-teal-600 dark:text-teal-400 shrink-0" />
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
                      {onlineInfo?.effective_url || 'https://central.dhis2.org'}
                    </span>
                  </div>
                </div>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {onlineInfo?.source === 'env' ? 'Env' : 'Vault'}
                </span>
              </button>
            </div>
          </div>

          {/* Export Parameters Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <Select
              label="Program"
              value={programName}
              onChange={(e) => setProgramName(e.target.value)}
              options={Object.keys(programIds).map((p) => ({ value: p, label: p }))}
            />

            <Select
              label="Organisation Unit Scope"
              value={orgMode}
              onChange={(e) => {
                setOrgMode(e.target.value);
                if (e.target.value === 'ALL') setOrgSearchQuery('');
              }}
              options={[
                { value: 'ALL', label: 'All Accessible Organisation Units' },
                { value: 'SELECTED', label: 'Specific Organisation Unit' },
              ]}
            />

            {orgMode === 'SELECTED' && (
              <>
                <TextInput
                  id="sync_org_filter_input"
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
                  disabled={orgUnits.length === 0}
                />

                <Select
                  label={`Target Facility (${filteredOrgUnits.length} found)`}
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
              </>
            )}

            <Select
              label="Enrollment Status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              options={[
                { value: 'ALL', label: 'All (Active, Completed, Cancelled)' },
                { value: 'COMPLETED', label: 'Completed Only' },
                { value: 'ACTIVE', label: 'Active Only' },
              ]}
            />

            <Select
              label="Event Status"
              value={eventStatusFilter}
              onChange={(e) => setEventStatusFilter(e.target.value)}
              options={[
                { value: 'ALL', label: 'All Events' },
                { value: 'COMPLETED', label: 'Completed Only' },
                { value: 'ACTIVE', label: 'Active Only' },
                { value: 'SCHEDULE', label: 'Scheduled Only' },
              ]}
            />

            <DateInput
              label="Start Date (Enrollment)"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />

            <DateInput
              label="End Date (Enrollment)"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />

            <DirectoryPicker
              label="Output Directory"
              value={outputDir}
              onChange={setOutputDir}
            />

            <TextInput
              label="Output File Name"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              placeholder="dhis2_export_sync.csv"
            />
          </div>

          <div className="flex justify-end pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="primary"
              icon={<Download className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={isViewer}
              onClick={handleExport}
            >
              Start Export for Syncing
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
        title="Sync Export Progress"
      />
    </div>
  );
};

export default DataExportPage;
