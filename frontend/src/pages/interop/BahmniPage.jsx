import React, { useState } from 'react';
import {
  Download,
  Shuffle,
  Upload,
  RefreshCw,
  Play,
  RotateCw,
  AlertTriangle,
  CheckCircle2,
  Info,
  FileCheck,
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
 * Bahmni / OpenMRS 2.x Interoperability Page
 * Standard 4-step workflow (Export, Transform, Import, Sync) with vault credentials and direct file upload capability.
 */
const BahmniPage = () => {
  const { isViewer } = useAuth();
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

  const { visitTypes, loadingVisitTypes, visitTypeMsg, handleLoadVisitTypes } = useVisitTypes('bahmni');

  const [subTab, setSubTab] = useState('export');
  const [importTarget, setImportTarget] = useState('online');
  const [syncTarget, setSyncTarget] = useState('online');
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
    filename: 'openmrs_export.csv',
  });

  const [transformForm, setTransformForm] = useState({
    input_csv: '/data/exports/openmrs_export.csv',
    mapping_file: '',
    dictionary_file: '',
    value_mapping_file: '',
    output_dir: '/data/exports',
    filename: 'dhis2_tracker_import.csv',
  });

  const [importForm, setImportForm] = useState({
    input_csv: '/data/exports/dhis2_tracker_import.csv',
    dry_run: true,
  });

  const [syncForm, setSyncForm] = useState({
    facility_name: 'Adama Teaching Hospital',
    facility_code: 'ADMT',
    visit_type_name: 'Delivery',
    start_date: '2026-01-01',
    end_date: new Date().toISOString().split('T')[0],
    mapping_path: '',
    dict_path: '',
    value_mapping_path: '',
    output_dir: '/data/exports',
    export_filename: 'openmrs_export.csv',
    transform_filename: 'dhis2_tracker_import.csv',
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

  const handleExport = () => {
    executeApiJob('/api/v1/interop/bahmni/export', exportForm);
  };

  const handleTransform = () => {
    executeApiJob('/api/v1/interop/bahmni/transform', transformForm);
  };

  const handleImportSubmit = (dryRun = false) => {
    if (dryRun) {
      executeApiJob('/api/v1/interop/bahmni/import', { ...importForm, dry_run: true, target: importTarget });
    } else {
      setConfirmPayload({
        endpoint: '/api/v1/interop/bahmni/import',
        payload: { ...importForm, dry_run: false, target: importTarget },
        message: `This will commit imported records from "${importForm.input_csv}" directly into ${
          importTarget === 'online' ? 'Online DHIS2 (Central)' : 'Offline DHIS2 (Local)'
        }. Are you sure?`,
      });
      setShowConfirm(true);
    }
  };

  const handleSyncSubmit = (dryRun = false) => {
    if (dryRun) {
      executeApiJob('/api/v1/interop/bahmni/sync', {
        ...syncForm,
        target: syncTarget,
        dry_run: true,
      });
    } else {
      setConfirmPayload({
        endpoint: '/api/v1/interop/bahmni/sync',
        payload: { ...syncForm, target: syncTarget, dry_run: false },
        message: `This will execute the full end-to-end sync pipeline from Bahmni directly into ${
          syncTarget === 'online' ? 'Online DHIS2 (Central)' : 'Offline DHIS2 (Local)'
        }. Are you sure?`,
      });
      setShowConfirm(true);
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Bahmni EMR ⟷ DHIS2 Tracker"
        breadcrumbs={[
          { label: 'Interoperability', href: '/interop' },
          { label: 'Bahmni Pipeline' },
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
            <CardTitle>Part 1: Export EMR Data (Bahmni / OpenMRS 2.x)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="p-3 bg-slate-50 dark:bg-slate-850 border border-slate-200 dark:border-slate-800 rounded-xl flex items-center justify-between text-xs">
              <div className="flex items-center gap-2.5">
                <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></div>
                <div>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">Saved Bahmni Connection:</span>
                  <span className="text-slate-600 dark:text-slate-400 font-mono ml-1.5">
                    {vaultConns.bahmni?.base_url || 'http://localhost/openmrs'} ({vaultConns.bahmni?.username || 'admin'})
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
                  placeholder={vaultConns.bahmni?.base_url || 'http://localhost/openmrs'}
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
                  <label htmlFor="bahmni-visit-type-select" className="text-xs font-semibold text-slate-700 dark:text-slate-300">Visit Type</label>
                  <button
                    type="button"
                    onClick={() => handleLoadVisitTypes('bahmni')}
                    disabled={loadingVisitTypes}
                    className="text-[11px] font-bold text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1"
                  >
                    <RefreshCw className={`w-3 h-3 ${loadingVisitTypes ? 'animate-spin' : ''}`} />
                    Reload from EMR
                  </button>
                </div>
                <Select
                  id="bahmni-visit-type-select"
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
                Export Bahmni Encounters
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* 2. Transform */}
      {subTab === 'transform' && (
        <Card>
          <CardHeader>
            <CardTitle>Part 2: Transform EMR Data to DHIS2 Tracker Format</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <FileUploadField
              label="1. Exported EMR Data (.csv)"
              value={transformForm.input_csv}
              onChange={(val) => setTransformForm({ ...transformForm, input_csv: val })}
              placeholder="/data/exports/openmrs_export.csv"
              accept=".csv"
            />
            <FileUploadField
              label="2. Mapping Excel File (.xlsx)"
              value={transformForm.mapping_file}
              onChange={(val) => setTransformForm({ ...transformForm, mapping_file: val })}
              placeholder="Select or upload facility mapping file (.xlsx)"
              accept=".xlsx,.xls,.csv"
            />
            <FileUploadField
              label="3. Dictionary Excel File (.xlsx, optional)"
              value={transformForm.dictionary_file}
              onChange={(val) => setTransformForm({ ...transformForm, dictionary_file: val })}
              placeholder="Leave empty to use packaged dictionary"
              accept=".xlsx,.xls"
            />
            <FileUploadField
              label="4. Value Mapping File (.csv, optional)"
              value={transformForm.value_mapping_file}
              onChange={(val) => setTransformForm({ ...transformForm, value_mapping_file: val })}
              placeholder="Leave empty to use active value mappings"
              accept=".csv"
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

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="primary"
                icon={<Shuffle className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !transformForm.input_csv}
                onClick={handleTransform}
              >
                Run Transformation Pipeline
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
              label="Transformed Tracker CSV File"
              value={importForm.input_csv}
              onChange={(val) => setImportForm({ ...importForm, input_csv: val })}
              placeholder="/data/exports/dhis2_tracker_import.csv"
              accept=".csv"
            />

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="secondary"
                icon={<FileCheck className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !importForm.input_csv}
                onClick={() => handleImportSubmit(true)}
              >
                Validate (Dry-Run)
              </Button>
              <Button
                variant="primary"
                icon={<Upload className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !importForm.input_csv}
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
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label htmlFor="bahmni-sync-visit-type-select" className="text-xs font-semibold text-slate-700 dark:text-slate-300">Visit Type</label>
                  <button
                    type="button"
                    onClick={() => handleLoadVisitTypes('bahmni')}
                    disabled={loadingVisitTypes}
                    className="text-[11px] font-bold text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1"
                  >
                    <RefreshCw className={`w-3 h-3 ${loadingVisitTypes ? 'animate-spin' : ''}`} />
                    Reload from EMR
                  </button>
                </div>
                <Select
                  id="bahmni-sync-visit-type-select"
                  aria-label="Visit Type"
                  value={syncForm.visit_type_name}
                  onChange={(e) => setSyncForm({ ...syncForm, visit_type_name: e.target.value })}
                  options={visitTypes.map((vt) => ({ value: vt.name, label: vt.name }))}
                />
              </div>

              {/* Date Presets */}
              <div className="md:col-span-2 flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-1 pb-1">
                <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">Quick Date Presets:</span>
                <div className="flex flex-wrap gap-1.5">
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

            <FileUploadField
              label="Mapping Excel File (.xlsx, optional)"
              value={syncForm.mapping_path}
              onChange={(val) => setSyncForm({ ...syncForm, mapping_path: val })}
              placeholder="Leave empty to use default packaged mapping"
              accept=".xlsx,.xls,.csv"
            />
            <FileUploadField
              label="Dictionary Excel File (.xlsx, optional)"
              value={syncForm.dict_path}
              onChange={(val) => setSyncForm({ ...syncForm, dict_path: val })}
              placeholder="Leave empty to use standard packaged dictionary"
              accept=".xlsx,.xls"
            />
            <FileUploadField
              label="Value Mapping File (.csv, optional)"
              value={syncForm.value_mapping_path}
              onChange={(val) => setSyncForm({ ...syncForm, value_mapping_path: val })}
              placeholder="Leave empty to use active value mappings"
              accept=".csv"
            />

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="secondary"
                icon={<FileCheck className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !syncForm.visit_type_name}
                onClick={() => handleSyncSubmit(true)}
              >
                Validate (Dry-Run)
              </Button>
              <Button
                variant="primary"
                icon={<RotateCw className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer || !syncForm.visit_type_name}
                onClick={() => handleSyncSubmit(false)}
              >
                Start Full Bahmni Sync
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

export default BahmniPage;
