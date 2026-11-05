import React, { useState } from 'react';
import {
  Sparkles,
  FileSpreadsheet,
  FileText,
  X,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardContent,
  Button,
  TextInput,
  DirectoryPicker,
  FileDropzone,
  JobPanel,
  Badge,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

/**
 * Data Transformation Page — One Row per TEI
 */
const CleaningPage = () => {
  const { user } = useAuth();
  const isViewer = user?.role === 'viewer';
  const { showToast } = useToast();
  const {
    uploadFile,
    authHeader,
    subscribeToJob,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    cancelActiveJob,
    resetJob,
  } = useDataManagementJob();

  const [selectedFile, setSelectedFile] = useState(null);
  const [outputDir, setOutputDir] = useState('/data/exports');
  const [filename, setFilename] = useState('');
  const [loading, setLoading] = useState(false);

  const handleFileChange = (file) => {
    setSelectedFile(file);
    if (file && !filename) {
      const cleanStem = file.name.replace(/\.csv$/i, '');
      setFilename(`transformed_${cleanStem}.csv`);
    }
  };

  const handleRun = async () => {
    if (!selectedFile) return;
    setLoading(true);
    try {
      const up = await uploadFile(selectedFile);
      const res = await fetch('/api/data-management/cleaning/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filepath: up.filepath,
          output_dir: outputDir || null,
          filename: filename.trim() || null,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Data transformation job failed to start'));
      subscribeToJob(data.job_id);
      showToast(`Started data transformation job #${data.job_id}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const effectiveOutFilename = filename.trim() || (selectedFile ? `transformed_${selectedFile.name}` : 'transformed_one_row_per_tei.csv');

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Data Transformation"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'Data Transformation' },
        ]}
      />

      <Card>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
                Input Tracker CSV Extract
              </label>
              {selectedFile && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedFile(null);
                    setFilename('');
                  }}
                  className="text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 font-semibold inline-flex items-center gap-1"
                >
                  <X className="w-3.5 h-3.5" /> Clear file
                </button>
              )}
            </div>

            <FileDropzone
              accept=".csv"
              maxSize={100 * 1024 * 1024}
              value={selectedFile}
              onChange={handleFileChange}
            />

            {selectedFile && (
              <div className="p-2.5 rounded-lg bg-teal-50 dark:bg-teal-950/30 border border-teal-200 dark:border-teal-800 flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  <FileSpreadsheet className="w-4 h-4 text-teal-600 dark:text-teal-400 shrink-0" />
                  <span className="font-semibold text-slate-800 dark:text-slate-200 truncate">{selectedFile.name}</span>
                  <span className="text-slate-400">({(selectedFile.size / 1024 / 1024).toFixed(2)} MB)</span>
                </div>
                <Badge variant="teal">Loaded</Badge>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-6 pt-4 border-t border-slate-100 dark:border-slate-800">
            <DirectoryPicker
              label="Output Directory"
              value={outputDir}
              onChange={setOutputDir}
            />
            <TextInput
              label="Output File Name"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              placeholder={effectiveOutFilename}
              leadingIcon={<FileText className="w-4 h-4 text-slate-400" />}
            />
          </div>

          <div className="flex justify-end pt-3 border-t border-slate-100 dark:border-slate-800">
            <Button
              variant="primary"
              icon={<Sparkles className="w-4 h-4 mr-1.5" />}
              loading={loading}
              disabled={!selectedFile || isViewer}
              onClick={handleRun}
            >
              Start Transformation
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
        title="Transformation Progress"
      />
    </div>
  );
};

export default CleaningPage;
