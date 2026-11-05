import React, { useState, useEffect } from 'react';
import {
  Layers,
  Download,
  CheckCircle2,
  Play,
  FileSpreadsheet,
  ShieldCheck,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Button,
  TextInput,
  DirectoryPicker,
  JobPanel,
} from '../../ui';
import { useAuth } from '../../context/AuthContext';
import { useHmisJob } from './useHmisJob';
import {
  HmisConnectionCard,
  MohDataElementSelect,
  MappingFileSelect,
} from './HmisServerSelectors';
import {
  getStoredDirectoryHandle,
  useStoredDirectoryHandle,
} from '../../utils/localFileSystem';

const MohAggregatePage = () => {
  const { isViewer } = useAuth();
  const {
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    outputArtifacts,
    handleSubmitJob,
    handleCancelJob,
    resetJob,
  } = useHmisJob();

  const storedFolder = useStoredDirectoryHandle();
  const [dhis2System, setDhis2System] = useState('dhis2_moh');
  const [dataElementUid, setDataElementUid] = useState('lzhOxCHJMOV');
  const [outputFilename, setOutputFilename] = useState('N_NICU_admissions_imnid_only');
  const [mappingFilePath, setMappingFilePath] = useState('Maternal aggregate.xlsx');
  const [outputDir, setOutputDir] = useState(() => {
    const stored = getStoredDirectoryHandle();
    return stored?.name ? `[Local Folder] ${stored.name}` : '/data/exports';
  });

  useEffect(() => {
    if (storedFolder?.name && (!outputDir || outputDir === '/data/exports')) {
      setOutputDir(`[Local Folder] ${storedFolder.name}`);
    }
  }, [storedFolder, outputDir]);

  const [periodMode, setPeriodMode] = useState('all');
  const [targetYear, setTargetYear] = useState('2018');
  const [selectedMonths, setSelectedMonths] = useState([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  const [showCustomMapping, setShowCustomMapping] = useState(false);

  const toggleMonth = (m) => {
    setSelectedMonths((prev) =>
      prev.includes(m) ? prev.filter((x) => x !== m) : [...prev, m].sort((a, b) => a - b)
    );
  };

  const handleRunPipeline = async () => {
    // Reaffirm directory permissions using this click gesture if a local folder is active
    const stored = getStoredDirectoryHandle();
    if (stored?.handle && typeof stored.handle.queryPermission === 'function') {
      try {
        const state = await stored.handle.queryPermission({ mode: 'readwrite' });
        if (state !== 'granted' && typeof stored.handle.requestPermission === 'function') {
          await stored.handle.requestPermission({ mode: 'readwrite' });
        }
      } catch (permErr) {
        console.warn('Could not reaffirm directory permission on click:', permErr);
      }
    }

    const cleanOutputDir = outputDir && !outputDir.startsWith('[Local Folder]') ? outputDir.trim() : undefined;
    const payload = {
      system: dhis2System,
      data_element_uid: (dataElementUid || '').trim(),
      mapping_file: mappingFilePath,
      output_filename: outputFilename.trim() || undefined,
      output_dir: cleanOutputDir,
    };

    if (periodMode === 'specific') {
      payload.year = parseInt(targetYear, 10);
      payload.months = selectedMonths;
    }

    handleSubmitJob('/api/hmis/moh-aggregate/run', payload);
  };

  return (
    <div className="space-y-4 w-full">
      <PageHeader
        title="MOH Aggregate Report Exporter"
        breadcrumbs={[
          { label: 'Reporting', href: '/hmis' },
          { label: 'MOH Aggregate Exporter' },
        ]}
      />

      {/* Saved MOH DHIS2 Connection Card */}
      <HmisConnectionCard
        type="dhis2_moh"
        selectedSystem={dhis2System}
        onSystemChange={setDhis2System}
        showToggle={false}
      />

      {/* Analytics Configuration Card */}
      <Card>
        <CardContent className="space-y-4 p-4 sm:p-5">
          <MohDataElementSelect
            system={dhis2System}
            value={dataElementUid}
            onChange={setDataElementUid}
            label="MOH Aggregate Data Element"
          />

          {/* Auto-configured Bundled Facility Mapping */}
          <div className="pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="p-3.5 rounded-xl border border-teal-200 dark:border-teal-850 bg-teal-50/50 dark:bg-teal-950/20 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-teal-100 dark:bg-teal-900/40 text-teal-700 dark:text-teal-300 flex items-center justify-center font-bold text-sm shrink-0">
                  <FileSpreadsheet className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-slate-900 dark:text-slate-100">
                      IMNID Facility Mapping
                    </span>
                    <span className="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800 flex items-center gap-1">
                      <ShieldCheck className="w-3.5 h-3.5" /> 99 Facilities Auto-Configured
                    </span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 self-end sm:self-auto">
                <a
                  href="/api/hmis/templates/Maternal aggregate.xlsx"
                  download
                  className="px-3 py-1.5 text-xs rounded-lg font-semibold border border-teal-300 dark:border-teal-700 text-teal-700 dark:text-teal-300 hover:bg-teal-100 dark:hover:bg-teal-900/40 inline-flex items-center gap-1.5 transition-colors"
                >
                  <Download className="w-3.5 h-3.5" /> Download Template (.xlsx)
                </a>
                <button
                  type="button"
                  onClick={() => setShowCustomMapping(!showCustomMapping)}
                  className="text-xs text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 underline font-medium px-1"
                >
                  {showCustomMapping ? 'Hide Custom' : 'Custom file?'}
                </button>
              </div>
            </div>

            {showCustomMapping && (
              <div className="mt-3 p-3 bg-slate-50 dark:bg-slate-850 rounded-lg border border-slate-200 dark:border-slate-700 space-y-2">
                <span className="text-xs font-bold text-slate-700 dark:text-slate-300">Override Mapping File:</span>
                <MappingFileSelect
                  value={mappingFilePath}
                  onChange={setMappingFilePath}
                  label="Selected Custom Mapping File"
                />
              </div>
            )}
          </div>

          {/* Period Range Configuration */}
          <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
            <label className="text-sm font-bold text-slate-800 dark:text-slate-200 block">
              Reporting Periods
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label
                className={`p-3.5 rounded-xl border cursor-pointer flex items-center gap-3.5 transition-colors ${
                  periodMode === 'all'
                    ? 'border-teal-500 bg-teal-50/40 dark:bg-teal-950/20 ring-1 ring-teal-500/30'
                    : 'border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-850'
                }`}
              >
                <input
                  type="radio"
                  name="period-mode"
                  checked={periodMode === 'all'}
                  onChange={() => setPeriodMode('all')}
                  className="w-4 h-4 text-teal-600 focus:ring-teal-500"
                />
                <div>
                  <span className="text-sm font-bold text-slate-800 dark:text-slate-200 block">
                    Full Historical Range
                  </span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    2017-07 to Current Month
                  </span>
                </div>
              </label>

              <label
                className={`p-3.5 rounded-xl border cursor-pointer flex items-center gap-3.5 transition-colors ${
                  periodMode === 'specific'
                    ? 'border-teal-500 bg-teal-50/40 dark:bg-teal-950/20 ring-1 ring-teal-500/30'
                    : 'border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-850'
                }`}
              >
                <input
                  type="radio"
                  name="period-mode"
                  checked={periodMode === 'specific'}
                  onChange={() => setPeriodMode('specific')}
                  className="w-4 h-4 text-teal-600 focus:ring-teal-500"
                />
                <div>
                  <span className="text-sm font-bold text-slate-800 dark:text-slate-200 block">
                    Specific Year & Months
                  </span>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    Custom year and month selection
                  </span>
                </div>
              </label>
            </div>

            {periodMode === 'specific' && (
              <div className="p-3.5 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg space-y-3 mt-2">
                <div className="flex flex-wrap items-end gap-4">
                  <div className="w-36">
                    <TextInput
                      label="Year (YYYY)"
                      value={targetYear}
                      onChange={(e) => setTargetYear(e.target.value)}
                      placeholder="2018"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5 pb-2">
                    <span className="text-xs text-slate-500 mr-1">Quick Select:</span>
                    {[
                      { y: '2018', label: '2018 (Baseline)' },
                      { y: '2017', label: '2017' },
                      { y: '2019', label: '2019' },
                      { y: '2025', label: '2025' },
                      { y: '2026', label: '2026' },
                    ].map((btn) => (
                      <button
                        key={btn.y}
                        type="button"
                        onClick={() => setTargetYear(btn.y)}
                        className={`px-2 py-0.5 text-xs rounded border transition-colors ${
                          targetYear === btn.y
                            ? 'bg-teal-600 text-white border-teal-600 font-semibold'
                            : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-teal-400'
                        }`}
                      >
                        {btn.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-2 pb-2 ml-auto">
                    <button
                      type="button"
                      onClick={() => setSelectedMonths([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])}
                      className="text-xs text-teal-600 dark:text-teal-400 font-medium hover:underline"
                    >
                      All Months
                    </button>
                    <span className="text-slate-300 dark:text-slate-700">|</span>
                    <button
                      type="button"
                      onClick={() => setSelectedMonths([])}
                      className="text-xs text-slate-400 hover:underline"
                    >
                      Clear
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-6 sm:grid-cols-12 gap-1 pt-1">
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                    const isSelected = selectedMonths.includes(m);
                    return (
                      <button
                        key={m}
                        type="button"
                        onClick={() => toggleMonth(m)}
                        className={`py-1 text-xs font-bold rounded border text-center transition-colors ${
                          isSelected
                            ? 'bg-teal-600 text-white border-teal-600'
                            : 'bg-white dark:bg-slate-800 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:border-teal-400'
                        }`}
                      >
                        {String(m).padStart(2, '0')}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Output Directory & Filename */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <DirectoryPicker
              label="Output Directory"
              value={outputDir}
              onChange={setOutputDir}
            />
            <TextInput
              label="Output Workbook Name"
              value={outputFilename}
              onChange={(e) => setOutputFilename(e.target.value)}
              placeholder="N_NICU_admissions_imnid_only"
            />
          </div>

          <div className="flex items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="primary"
              onClick={handleRunPipeline}
              disabled={isViewer || isStreaming || !dataElementUid || !mappingFilePath}
            >
              <Play className="w-4 h-4 mr-1.5" />
              Run MOH Analytics Export
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Active Job & Execution Monitor */}
      {activeJobId && (
        <JobPanel
          jobId={activeJobId}
          jobState={jobState}
          logs={liveLogs}
          liveLogs={liveLogs}
          isStreaming={isStreaming}
          onCancel={handleCancelJob}
          onReset={resetJob}
          onDismiss={resetJob}
          showDownloadButtons={false}
        />
      )}
    </div>
  );
};

export default MohAggregatePage;
