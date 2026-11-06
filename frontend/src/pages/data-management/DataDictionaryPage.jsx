import React, { useState, useEffect, useCallback } from 'react';
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

  const [sourceInstance, setSourceInstance] = useState(null);
  const [programs, setPrograms] = useState([]);
  const [loadingPrograms, setLoadingPrograms] = useState(false);
  const [selectedProgramId, setSelectedProgramId] = useState('');
  const [outputDir, setOutputDir] = useState('/data/exports');
  const [filename, setFilename] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchPrograms = useCallback(async (system) => {
    setLoadingPrograms(true);
    try {
      const res = await fetch(`/api/data-management/dhis2/programs?system=${system}`, {
        headers: authHeader(),
      });
      if (res.ok) {
        const data = await res.json();
        const progs = data.ok && Array.isArray(data.programs) ? data.programs : [];
        setPrograms(progs);
        if (progs.length > 0) {
          setSelectedProgramId((prev) => (progs.some((p) => p.id === prev) ? prev : progs[0].id));
        } else {
          setSelectedProgramId('');
        }
      }
    } catch (err) {
      console.warn('Failed to fetch programs for', system, err);
      setPrograms([]);
      setSelectedProgramId('');
    } finally {
      setLoadingPrograms(false);
    }
  }, [authHeader]);

  useEffect(() => {
    if (sourceInstance) {
      fetchPrograms(sourceInstance);
    } else {
      setPrograms([]);
      setSelectedProgramId('');
    }
  }, [sourceInstance, fetchPrograms]);

  const handleExport = async () => {
    if (!sourceInstance) {
      showToast('Please select a source DHIS2 instance (Offline or Online)', 'error');
      return;
    }
    if (!selectedProgramId) {
      showToast('Please select a tracker program before generating dictionary', 'error');
      return;
    }
    setLoading(true);
    const chosenProg = programs.find((p) => p.id === selectedProgramId);
    const chosenName = chosenProg?.name || selectedProgramId;
    try {
      const res = await fetch('/api/data-management/data-dictionary/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_instance: sourceInstance,
          program_name: chosenName,
          program_id: selectedProgramId,
          output_dir: outputDir,
          filename: filename || undefined,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Data dictionary generation failed'));
      subscribeToJob(data.job_id);
      showToast(`Generating dictionary for ${chosenName}...`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="DHIS2 Data Dictionary Generator"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'Data Dictionary' },
        ]}
      />

      <Card>
        <CardContent className="space-y-6">
          {/* Source Instance Selector */}
          <div className="space-y-2">
            <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
              Source DHIS2 Instance
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setSourceInstance('dhis2_offline')}
                className={`p-3 rounded-xl border text-left flex items-center justify-between transition-all ${
                  sourceInstance === 'dhis2_offline'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Laptop className="w-5 h-5 text-teal-600 dark:text-teal-400 shrink-0" />
                  <div>
                    <span className="font-semibold text-sm text-slate-800 dark:text-slate-100 block">Offline DHIS2</span>
                    <span className="font-mono text-xs text-slate-500 truncate block max-w-[220px]">
                      {offlineInfo?.effective_url || 'http://localhost:8080'}
                    </span>
                  </div>
                </div>
                <span className="text-xs font-medium px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {offlineInfo?.source === 'env' ? 'Env' : 'Vault'}
                </span>
              </button>

              <button
                type="button"
                onClick={() => setSourceInstance('dhis2_online')}
                className={`p-3 rounded-xl border text-left flex items-center justify-between transition-all ${
                  sourceInstance === 'dhis2_online'
                    ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/20 ring-1 ring-teal-500'
                    : 'border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 hover:bg-slate-100 dark:hover:bg-slate-800/60'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Globe className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <div>
                    <span className="font-semibold text-sm text-slate-800 dark:text-slate-100 block">Online DHIS2</span>
                    <span className="font-mono text-xs text-slate-500 truncate block max-w-[220px]">
                      {onlineInfo?.effective_url || 'https://central.dhis2.org'}
                    </span>
                  </div>
                </div>
                <span className="text-xs font-medium px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {onlineInfo?.source === 'env' ? 'Env' : 'Vault'}
                </span>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 sm:gap-6 pt-4 border-t border-slate-100 dark:border-slate-800">
            <Select
              label="Tracker Program"
              value={selectedProgramId}
              onChange={(e) => setSelectedProgramId(e.target.value)}
              disabled={!sourceInstance || loadingPrograms || programs.length === 0}
              options={
                !sourceInstance
                  ? [{ value: '', label: 'Select an instance to load programs' }]
                  : loadingPrograms
                  ? [{ value: '', label: 'Loading programs...' }]
                  : programs.length === 0
                  ? [{ value: '', label: 'No tracker programs found' }]
                  : programs.map((p) => ({
                      value: p.id,
                      label: p.name ? `${p.name} (${p.id})` : p.id,
                    }))
              }
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

          <div className="flex justify-center pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="primary"
              icon={<BookOpen className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={isViewer || !sourceInstance}
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
