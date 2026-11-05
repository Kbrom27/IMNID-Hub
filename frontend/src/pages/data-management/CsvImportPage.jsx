import React, { useState } from 'react';
import { Upload, Eye, Play, Globe, Laptop } from 'lucide-react';
import {
  PageHeader,
  Card,
  CardContent,
  Button,
  FileDropzone,
  JobPanel,
  ConfirmDialog,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

/**
 * CSV Import Page -> DHIS2 Tracker
 */
const CsvImportPage = () => {
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

  const [file, setFile] = useState(null);
  const [targetInstance, setTargetInstance] = useState('dhis2_online');
  const [loading, setLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const onlineInfo = vaultConns?.online;
  const offlineInfo = vaultConns?.offline;

  const handleDryRun = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const up = await uploadFile(file);
      const res = await fetch('/api/data-management/csv-import/dry-run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ filepath: up.filepath, target_instance: targetInstance }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Dry-run validation failed'));
      subscribeToJob(data.job_id);
      showToast(`Validating CSV with dry-run job #${data.job_id}`, 'info');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleCommit = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const up = await uploadFile(file);
      const res = await fetch('/api/data-management/csv-import/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ filepath: up.filepath, target_instance: targetInstance }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Import failed to start'));
      subscribeToJob(data.job_id);
      showToast(`Started DHIS2 tracker data import job #${data.job_id}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
      setShowConfirm(false);
    }
  };

  const destName = targetInstance === 'dhis2_offline' ? 'Offline DHIS2' : 'Online DHIS2';

  return (
    <div className="space-y-4 w-full">
      <PageHeader
        title="DHIS2 Tracker Data Import"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'Tracker Data Import' },
        ]}
      />

      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
          {/* Target Instance Selector */}
          <div className="space-y-2">
            <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
              Target DHIS2 Instance
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setTargetInstance('dhis2_online')}
                className={`p-2.5 rounded-lg border text-left flex items-center justify-between transition-all ${
                  targetInstance === 'dhis2_online'
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

              <button
                type="button"
                onClick={() => setTargetInstance('dhis2_offline')}
                className={`p-2.5 rounded-lg border text-left flex items-center justify-between transition-all ${
                  targetInstance === 'dhis2_offline'
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
            </div>
          </div>

          <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
              Tracker CSV Data File
            </label>
            <FileDropzone
              accept=".csv"
              maxSize={100 * 1024 * 1024}
              value={file}
              onChange={setFile}
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="secondary"
              icon={<Eye className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={!file || isViewer}
              onClick={handleDryRun}
            >
              Validate & Preview (Dry-Run)
            </Button>
            <Button
              variant="primary"
              icon={<Play className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={!file || isViewer}
              onClick={() => setShowConfirm(true)}
            >
              Import to DHIS2
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
        title="Tracker Data Import Progress"
      />

      <ConfirmDialog
        open={showConfirm}
        targetSystem={targetInstance}
        title="Confirm DHIS2 Tracker Data Import"
        message={`Are you sure you want to write and commit records from "${file?.name}" into ${destName}?`}
        confirmText="Confirm & Import"
        onConfirm={handleCommit}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default CsvImportPage;
