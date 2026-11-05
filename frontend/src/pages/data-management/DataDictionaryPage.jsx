import React, { useState } from 'react';
import { BookOpen, Laptop, Globe } from 'lucide-react';
import {
  PageHeader,
  Card,
  CardContent,
  Button,
  Select,
  TextInput,
  DirectoryPicker,
  JobPanel,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

/**
 * Data Dictionary Page
 */
const DataDictionaryPage = () => {
  const { user } = useAuth();
  const isViewer = user?.role === 'viewer';
  const { showToast } = useToast();
  const {
    authHeader,
    subscribeToJob,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    cancelActiveJob,
    resetJob,
    vaultConns,
  } = useDataManagementJob();

  const offlineInfo = vaultConns?.offline;
  const onlineInfo = vaultConns?.online;

  const [sourceInstance, setSourceInstance] = useState('dhis2_offline');
  const [programName, setProgramName] = useState('Maternal inpatient data');
  const [outputDir, setOutputDir] = useState('/data/exports');
  const [filename, setFilename] = useState('');
  const [loading, setLoading] = useState(false);

  const handleExport = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/data-management/data-dictionary/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_instance: sourceInstance,
          program_name: programName,
          output_dir: outputDir,
          filename: filename || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Data dictionary generation failed'));
      subscribeToJob(data.job_id);
      showToast(`Generating dictionary for ${programName}...`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4 w-full">
      <PageHeader
        title="DHIS2 Data Dictionary Generator"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'Data Dictionary' },
        ]}
      />

      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
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

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <Select
              label="Tracker Program"
              value={programName}
              onChange={(e) => setProgramName(e.target.value)}
              options={[
                { value: 'Maternal inpatient data', label: 'Maternal Inpatient Data' },
                { value: 'Neonatal care Form', label: 'Neonatal Care Form' },
                { value: 'Newborn Inpatient Data', label: 'Newborn Inpatient Data' },
              ]}
            />

            <DirectoryPicker
              label="Output Directory"
              value={outputDir}
              onChange={setOutputDir}
            />

            <TextInput
              label="Output File Name (Optional)"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              placeholder="e.g. data_dictionary.xlsx"
            />
          </div>

          <div className="flex justify-end pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="primary"
              icon={<BookOpen className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={isViewer}
              onClick={handleExport}
            >
              Generate Data Dictionary
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
        title="Dictionary Generation Progress"
      />
    </div>
  );
};

export default DataDictionaryPage;
