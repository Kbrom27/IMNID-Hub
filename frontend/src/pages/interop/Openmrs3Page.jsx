import React, { useState } from 'react';
import {
  Download,
  Shuffle,
  Upload,
  RefreshCw,
  RotateCw,
  Info,
  FileCheck,
  CheckCircle2,
  AlertCircle,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  Select,
  DateInput,
  TextInput,
  Checkbox,
  JobPanel,
  ConfirmDialog,
  Alert,
} from '../../ui';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../ui/ToastProvider';
import { useInteropJob } from './useInteropJob';
import { useVisitTypes } from './useVisitTypes';
import DirectoryPicker from './DirectoryPicker';
import FileUploadField from './FileUploadField';
import Dhis2TargetSelector from './Dhis2TargetSelector';

const SUB_TABS = [
  { id: 'export', label: '1. Export EMR Data', icon: Download },
  { id: 'transform', label: '2. Transform to DHIS2', icon: Shuffle },
  { id: 'import', label: '3. Import to DHIS2', icon: Upload },
  { id: 'sync', label: '4. Full Sync Pipeline', icon: RotateCw },
];

/**
 * OpenMRS 3.x (O3) Interoperability Page
 * Standard 4-step workflow (Export, Transform, Import, Sync) with vault credentials and direct file upload capability.
 */
const Openmrs3Page = () => {
  const { isViewer, authHeader } = useAuth();
  const { showToast } = useToast();
  const {
    facilities,
    vaultConns,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    cancelActiveJob,
    executeApiJob,
    resetJob,
  } = useInteropJob();

  const { visitTypes, loadingVisitTypes, visitTypeMsg, handleLoadVisitTypes } = useVisitTypes('o3');

  const [subTab, setSubTab] = useState('export');
  const [importTarget, setImportTarget] = useState(null);
  const [syncTarget, setSyncTarget] = useState(null);
  const [showCredsOverride, setShowCredsOverride] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [confirmPayload, setConfirmPayload] = useState(null);

  // Forms
  const [exportForm, setExportForm] = useState({
    emr_base_url: '',
    emr_username: '',
    emr_password: '',
    facility_name: 'Adama Teaching Hospital',
    facility_code: 'ADMT',
    visit_type_name: 'Delivery',
    start_date: '2026-01-01',
    end_date: new Date().toISOString().split('T')[0],
    output_dir: '/data/exports',
    filename: 'openmrs3_export.csv',
  });

  const [transformForm, setTransformForm] = useState({
    input_csv: '/data/exports/openmrs3_export.csv',
    output_dir: '/data/exports',
    filename: 'dhis2_tracker_import.csv',
  });

  const [importForm, setImportForm] = useState({
    input_csv: '/data/exports/dhis2_tracker_import.csv',
    dry_run: false,
  });

  const [syncForm, setSyncForm] = useState({
    facility_name: 'Adama Teaching Hospital',
    facility_code: 'ADMT',
    visit_type_name: 'Delivery',
    start_date: '2026-01-01',
    end_date: new Date().toISOString().split('T')[0],
    output_dir: '/data/exports',
  });

  // Quick Date Range Presets
  const applyDatePreset = (preset, formType = 'export') => {
    const today = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const fmt = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    let start = '';
    let end = '';

    if (preset === 'last30') {
      const d = new Date();
      d.setDate(d.getDate() - 30);
      start = fmt(d);
      end = fmt(today);
    } else if (preset === 'month') {
      const d = new Date(today.getFullYear(), today.getMonth(), 1);
      start = fmt(d);
      end = fmt(today);
    } else if (preset === 'year') {
      const d = new Date(today.getFullYear(), 0, 1);
      start = fmt(d);
      end = fmt(today);
    }

    if (formType === 'export') {
      setExportForm((prev) => ({ ...prev, start_date: start, end_date: end }));
    } else if (formType === 'sync') {
      setSyncForm((prev) => ({ ...prev, start_date: start, end_date: end }));
    }
  };

  const [verifyingMappings, setVerifyingMappings] = useState(false);
  const [mappingStats, setMappingStats] = useState(null);
  const [mappingError, setMappingError] = useState(null);

  const handleVerifyMappings = async () => {
    setVerifyingMappings(true);
    setMappingError(null);
    try {
      const res = await fetch('/api/v1/interop/o3/verify-mappings', { headers: authHeader() });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Failed to verify mapping files');
      }
      setMappingStats(data);
    } catch (err) {
      setMappingError(err.message);
    } finally {
      setVerifyingMappings(false);
    }
  };

  const handleExport = () => {
    executeApiJob('/api/v1/interop/o3/export', exportForm);
  };

  const handleTransform = () => {
    executeApiJob('/api/v1/interop/o3/transform', transformForm);
  };

  const handleImportSubmit = (dryRun = false) => {
    if (!importTarget) {
      showToast('Please select a DHIS2 destination instance (Online or Offline)', 'error');
      return;
    }
    if (dryRun) {
      executeApiJob('/api/v1/interop/o3/import', { ...importForm, dry_run: true, target: importTarget });
    } else {
      setConfirmPayload({
        endpoint: '/api/v1/interop/o3/import',
        payload: { ...importForm, dry_run: false, target: importTarget },
        message: `This will commit imported records from "${importForm.input_csv}" directly into ${
          importTarget === 'online' ? 'Online DHIS2 (Central)' : 'Offline DHIS2 (Local)'
        }. Are you sure?`,
      });
      setShowConfirm(true);
    }
  };

  const handleSyncSubmit = (dryRun = false) => {
    if (!syncTarget) {
      showToast('Please select a DHIS2 destination instance (Online or Offline)', 'error');
      return;
    }
    if (dryRun) {
      executeApiJob('/api/v1/interop/o3/sync', { ...syncForm, dry_run: true, target: syncTarget });
    } else {
      setConfirmPayload({
        endpoint: '/api/v1/interop/o3/sync',
        payload: { ...syncForm, dry_run: false, target: syncTarget },
        message: `This will execute the full end-to-end sync pipeline from OpenMRS 3 directly into ${
          syncTarget === 'online' ? 'Online DHIS2 (Central)' : 'Offline DHIS2 (Local)'
        }. Are you sure?`,
      });
      setShowConfirm(true);
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="OpenMRS 3.x (O3) ⟷ DHIS2 Tracker"
        breadcrumbs={[
          { label: 'Interoperability', href: '/interop' },
          { label: 'OpenMRS 3.x Pipeline' },
        ]}
      />

      {/* Sub-tab navigation */}
      <div className="flex flex-wrap gap-2 p-1.5 bg-slate-100 dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
        {SUB_TABS.map((sub) => {
          const Icon = sub.icon;
          const isSelected = subTab === sub.id;
          return (
            <button
              key={sub.id}
              onClick={() => setSubTab(sub.id)}
              className={`flex-1 min-w-[140px] flex items-center justify-center gap-2.5 py-2.5 px-4 rounded-lg text-sm font-bold transition-all ${
                isSelected
                  ? 'bg-white dark:bg-slate-900 text-teal-800 dark:text-teal-300 shadow-xs border border-slate-200 dark:border-slate-700 ring-1 ring-teal-500/20'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 hover:bg-slate-200/60 dark:hover:bg-slate-700'
              }`}
            >
              <Icon className={`w-4 h-4 ${isSelected ? 'text-teal-600 dark:text-teal-400' : 'text-slate-400'}`} />
              <span>{sub.label}</span>
            </button>
          );
        })}
      </div>

      {/* 1. Export */}
      {subTab === 'export' && (
        <Card>
          <CardHeader>
            <CardTitle>Part 1: Export EMR Data (OpenMRS 3.x)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="p-3 bg-slate-50 dark:bg-slate-855 border border-slate-200 dark:border-slate-800 rounded-xl flex items-center justify-between text-xs">
              <div className="flex items-center gap-2.5">
                <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></div>
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">Saved OpenMRS 3 Connection:</span>
                  <span className="text-slate-600 dark:text-slate-400 font-mono ml-1.5">
                    {vaultConns.o3?.base_url || 'http://localhost/openmrs'} ({vaultConns.o3?.username || 'admin'})
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowCredsOverride(!showCredsOverride)}
                className="text-[11px] font-bold text-teal-600 dark:text-teal-400 hover:underline"
              >
                {showCredsOverride ? 'Use Vault Default' : 'Override Credentials'}
              </button>
            </div>

            {showCredsOverride && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3 bg-amber-50/60 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-xl text-xs">
                <TextInput
                  label="Server URL"
                  value={exportForm.emr_base_url}
                  onChange={(e) => setExportForm({ ...exportForm, emr_base_url: e.target.value })}
                  placeholder={vaultConns.o3?.base_url || 'http://localhost/openmrs'}
                />
                <TextInput
                  label="Username"
                  value={exportForm.emr_username}
                  onChange={(e) => setExportForm({ ...exportForm, emr_username: e.target.value })}
                  placeholder="admin"
                />
                <TextInput
                  label="Password"
                  type="password"
                  value={exportForm.emr_password}
                  onChange={(e) => setExportForm({ ...exportForm, emr_password: e.target.value })}
                  placeholder="••••••••"
                />
              </div>
            )}

            {visitTypeMsg && (
              <Alert
                variant={visitTypeMsg.type === 'success' ? 'success' : 'danger'}
                description={visitTypeMsg.text}
              />
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Select
                label="Target Facility"
                value={exportForm.facility_name}
                onChange={(e) => {
                  const sel = facilities.find((f) => f.name === e.target.value);
                  setExportForm({
                    ...exportForm,
                    facility_name: e.target.value,
                    facility_code: sel ? sel.code : '',
                  });
                }}
                options={facilities.map((fac) => ({ value: fac.name, label: `${fac.name} (${fac.code})` }))}
              />

              <div>
                <div className="flex justify-between items-center mb-1">
                  <label htmlFor="o3-visit-type-select" className="text-xs font-semibold text-slate-700 dark:text-slate-300">Visit Type</label>
                  <button
                    type="button"
                    onClick={() => handleLoadVisitTypes('o3')}
                    disabled={loadingVisitTypes}
                    className="text-[11px] font-bold text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1"
                  >
                    <RefreshCw className={`w-3 h-3 ${loadingVisitTypes ? 'animate-spin' : ''}`} />
                    Reload from EMR
                  </button>
                </div>
                <Select
                  id="o3-visit-type-select"
                  aria-label="Visit Type"
                  value={exportForm.visit_type_name}
                  onChange={(e) => setExportForm({ ...exportForm, visit_type_name: e.target.value })}
                  options={visitTypes.map((vt) => ({ value: vt.name, label: vt.name }))}
                />
              </div>

              {/* Date Presets Row */}
              <div className="col-span-1 md:col-span-2 flex items-center justify-between border-t border-slate-100 dark:border-slate-800 pt-3">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  Visit Date Range Filter
                </span>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="text-slate-400 mr-0.5 text-[11px]">Presets:</span>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('all', 'export')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    All Time
                  </button>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('last30', 'export')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    Last 30 Days
                  </button>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('month', 'export')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    This Month
                  </button>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('year', 'export')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    This Year
                  </button>
                </div>
              </div>

              <DateInput
                label="Start Date"
                value={exportForm.start_date}
                onChange={(e) => setExportForm({ ...exportForm, start_date: e.target.value })}
              />
              <DateInput
                label="End Date"
                value={exportForm.end_date}
                onChange={(e) => setExportForm({ ...exportForm, end_date: e.target.value })}
              />

              <DirectoryPicker
                label="Output Directory"
                value={exportForm.output_dir}
                onChange={(dir) => setExportForm({ ...exportForm, output_dir: dir })}
              />
              <TextInput
                label="Output File Name"
                value={exportForm.filename}
                onChange={(e) => setExportForm({ ...exportForm, filename: e.target.value })}
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="primary"
                icon={<Download className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer}
                onClick={handleExport}
              >
                Export O3 Patients
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 2. Transform */}
      {subTab === 'transform' && (
        <Card>
          <CardHeader>
            <CardTitle>Part 2: Transform O3 Data to DHIS2 Tracker Format</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <FileUploadField
              label="O3 Export CSV"
              value={transformForm.input_csv}
              onChange={(val) => setTransformForm({ ...transformForm, input_csv: val })}
              placeholder="/data/exports/openmrs3_export.csv"
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
              <DirectoryPicker
                label="Output Directory"
                value={transformForm.output_dir}
                onChange={(dir) => setTransformForm({ ...transformForm, output_dir: dir })}
              />
              <TextInput
                label="Output File Name"
                value={transformForm.filename}
                onChange={(e) => setTransformForm({ ...transformForm, filename: e.target.value })}
              />
            </div>

            {/* Packaged Mapping Files Verification */}
            <div className="p-3.5 bg-slate-50 dark:bg-slate-850/60 border border-slate-200 dark:border-slate-800 rounded-xl space-y-2.5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800 dark:text-slate-200">
                  <Info className="w-4 h-4 text-teal-600 dark:text-teal-400 shrink-0" />
                  <span>Packaged Mapping Files (Resources/O3)</span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  icon={<FileCheck className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400" />}
                  loading={verifyingMappings}
                  onClick={handleVerifyMappings}
                >
                  Verify Mapping Files
                </Button>
              </div>

              {mappingError && (
                <div className="flex items-center gap-2 p-2 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/60 rounded-lg text-xs text-red-700 dark:text-red-300">
                  <AlertCircle className="w-4 h-4 shrink-0 text-red-500" />
                  <span>{mappingError}</span>
                </div>
              )}

              {mappingStats && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-xs">
                  <div className="p-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg">
                    <span className="text-[10px] text-slate-500 block uppercase font-bold tracking-wider">Maternal</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold">{mappingStats.maternal_mapping?.rows} rows</span>
                  </div>
                  <div className="p-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg">
                    <span className="text-[10px] text-slate-500 block uppercase font-bold tracking-wider">Neonatal</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold">{mappingStats.neonatal_mapping?.rows} rows</span>
                  </div>
                  <div className="p-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg">
                    <span className="text-[10px] text-slate-500 block uppercase font-bold tracking-wider">Value Mappings</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold">{mappingStats.value_mapping?.rows} rows</span>
                  </div>
                  <div className="p-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg">
                    <span className="text-[10px] text-slate-500 block uppercase font-bold tracking-wider">Metadata JSON</span>
                    <span className="text-emerald-600 dark:text-emerald-400 font-semibold flex items-center gap-1">
                      <CheckCircle2 className="w-3.5 h-3.5" /> Verified
                    </span>
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="primary"
                icon={<Shuffle className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !transformForm.input_csv}
                onClick={handleTransform}
              >
                Transform O3 Export
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 3. Import */}
      {subTab === 'import' && (
        <Card>
          <CardHeader>
            <CardTitle>Part 3: Import Transformed Data into DHIS2 Tracker</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <Dhis2TargetSelector
              target={importTarget}
              setTarget={setImportTarget}
              vaultConns={vaultConns}
            />

            <FileUploadField
              label="Transformed CSV"
              value={importForm.input_csv}
              onChange={(val) => setImportForm({ ...importForm, input_csv: val })}
              placeholder="/data/exports/dhis2_tracker_import.csv"
            />

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="secondary"
                icon={<FileCheck className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !importForm.input_csv || !importTarget}
                onClick={() => handleImportSubmit(true)}
              >
                Validate (Dry-Run)
              </Button>
              <Button
                variant="primary"
                icon={<Upload className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !importForm.input_csv || !importTarget}
                onClick={() => handleImportSubmit(false)}
              >
                Import to DHIS2
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 4. Full Sync */}
      {subTab === 'sync' && (
        <Card>
          <CardHeader>
            <CardTitle>Part 4: Full End-to-End Synchronization</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* OpenMRS 3 Connection */}
            <div className="p-3 bg-slate-50 dark:bg-slate-855 border border-slate-200 dark:border-slate-800 rounded-xl flex items-center justify-between text-xs">
              <div className="flex items-center gap-2.5">
                <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></div>
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">OpenMRS 3 Source:</span>
                  <span className="text-slate-600 dark:text-slate-400 font-mono ml-1.5">
                    {vaultConns.o3?.base_url || 'http://localhost/openmrs'} ({vaultConns.o3?.username || 'admin'})
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowCredsOverride(!showCredsOverride)}
                className="text-[11px] font-bold text-teal-600 dark:text-teal-400 hover:underline"
              >
                {showCredsOverride ? 'Use Vault Default' : 'Override Credentials'}
              </button>
            </div>

            {showCredsOverride && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 p-3 bg-amber-50/60 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-xl text-xs">
                <TextInput
                  label="Server URL"
                  value={syncForm.emr_base_url || ''}
                  onChange={(e) => setSyncForm({ ...syncForm, emr_base_url: e.target.value })}
                  placeholder={vaultConns.o3?.base_url || 'http://localhost/openmrs'}
                />
                <TextInput
                  label="Username"
                  value={syncForm.emr_username || ''}
                  onChange={(e) => setSyncForm({ ...syncForm, emr_username: e.target.value })}
                  placeholder="admin"
                />
                <TextInput
                  label="Password"
                  type="password"
                  value={syncForm.emr_password || ''}
                  onChange={(e) => setSyncForm({ ...syncForm, emr_password: e.target.value })}
                  placeholder="••••••••"
                />
              </div>
            )}

            <Dhis2TargetSelector
              target={syncTarget}
              setTarget={setSyncTarget}
              vaultConns={vaultConns}
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <Select
                label="Target Facility"
                value={syncForm.facility_name}
                onChange={(e) => {
                  const sel = facilities.find((f) => f.name === e.target.value);
                  setSyncForm({
                    ...syncForm,
                    facility_name: e.target.value,
                    facility_code: sel ? sel.code : '',
                  });
                }}
                options={facilities.map((fac) => ({ value: fac.name, label: `${fac.name} (${fac.code})` }))}
              />
              <Select
                label="Visit Type"
                value={syncForm.visit_type_name}
                onChange={(e) => setSyncForm({ ...syncForm, visit_type_name: e.target.value })}
                options={visitTypes.map((vt) => ({ value: vt.name, label: vt.name }))}
              />
              {/* Date Presets Row */}
              <div className="col-span-1 md:col-span-2 flex items-center justify-between border-t border-slate-100 dark:border-slate-800 pt-3">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">
                  Visit Date Range Filter
                </span>
                <div className="flex items-center gap-1.5 text-xs">
                  <span className="text-slate-400 mr-0.5 text-[11px]">Presets:</span>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('all', 'sync')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    All Time
                  </button>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('last30', 'sync')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    Last 30 Days
                  </button>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('month', 'sync')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    This Month
                  </button>
                  <button
                    type="button"
                    onClick={() => applyDatePreset('year', 'sync')}
                    className="px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300 transition-colors"
                  >
                    This Year
                  </button>
                </div>
              </div>

              <DateInput
                label="Start Date"
                value={syncForm.start_date}
                onChange={(e) => setSyncForm({ ...syncForm, start_date: e.target.value })}
              />
              <DateInput
                label="End Date"
                value={syncForm.end_date}
                onChange={(e) => setSyncForm({ ...syncForm, end_date: e.target.value })}
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="secondary"
                icon={<FileCheck className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !syncTarget}
                onClick={() => handleSyncSubmit(true)}
              >
                Validate (Dry-Run)
              </Button>
              <Button
                variant="primary"
                icon={<RotateCw className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !syncTarget}
                onClick={() => handleSyncSubmit(false)}
              >
                Run Full O3 Sync
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Progress & Live Logs */}
      <JobPanel
        jobId={activeJobId}
        jobState={jobState}
        logs={liveLogs}
        isStreaming={isStreaming}
        onCancel={cancelActiveJob}
        onReset={resetJob}
        title="Interoperability Job Execution"
      />

      <ConfirmDialog
        open={showConfirm}
        targetSystem={confirmPayload?.payload?.target === 'offline' ? 'dhis2_offline' : 'dhis2_online'}
        title="Confirm Live Execution"
        message={confirmPayload?.message || 'Are you sure you want to proceed?'}
        confirmText="Confirm & Run"
        onConfirm={() => {
          setShowConfirm(false);
          if (confirmPayload) {
            executeApiJob(confirmPayload.endpoint, confirmPayload.payload);
          }
        }}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default Openmrs3Page;
