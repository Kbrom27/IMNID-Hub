import React, { useState } from 'react';
import {
  Package,
  Eye,
  Play,
  Globe,
  Laptop,
  Info,
  FileJson,
  Search,
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
  Switch,
  FileDropzone,
  JobPanel,
  ConfirmDialog,
  Modal,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { useDataManagementJob } from './useDataManagementJob';
import { extractErrorMessage } from '../../utils/errors';

/**
 * Metadata Import Page
 * Imports JSON or ZIP metadata packages into DHIS2 using saved credentials,
 * with validation dry-runs, package breakdown (file info), and granular import options.
 */
const MetadataImportPage = () => {
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

  // Target DHIS2 Instance (Online vs Offline from saved vault/env)
  const [targetInstance, setTargetInstance] = useState(null);

  // File & Upload State
  const [file, setFile] = useState(null);
  const [fileUploading, setFileUploading] = useState(false);
  const [fileUploadError, setFileUploadError] = useState(null);
  const [uploadedRef, setUploadedRef] = useState(null); // { file, filepath }
  const [fileInfoModalOpen, setFileInfoModalOpen] = useState(false);
  const [fileInfoLoading, setFileInfoLoading] = useState(false);
  const [fileInfoData, setFileInfoData] = useState(null);
  const [fileInfoFilter, setFileInfoFilter] = useState('');

  // Import Options
  const [importMode, setImportMode] = useState('COMMIT'); // COMMIT or VALIDATE
  const [strategy, setStrategy] = useState('CREATE_AND_UPDATE'); // CREATE_AND_UPDATE, CREATE, UPDATE
  const [identifier, setIdentifier] = useState('UID'); // UID or CODE
  const [mergeMode, setMergeMode] = useState('MERGE'); // MERGE or REPLACE
  const [execMode, setExecMode] = useState('Direct (Synchronous)'); // Direct (Synchronous) or Background (Async)
  const [apiVersion, setApiVersion] = useState('auto-detect');
  const [atomic, setAtomic] = useState(false);

  // Action State
  const [loading, setLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  const onlineInfo = vaultConns?.online;
  const offlineInfo = vaultConns?.offline;

  // Handle file selection with immediate upload
  const handleFileChange = async (newFile) => {
    setFile(newFile);
    setUploadedRef(null);
    setFileInfoData(null);
    setFileUploadError(null);
    if (!newFile) return;

    setFileUploading(true);
    try {
      const up = await uploadFile(newFile);
      setUploadedRef({ file: newFile, filepath: up.filepath });
    } catch (err) {
      console.error('File upload error:', err);
      setFileUploadError(err.message || 'Upload failed');
      showToast(`Upload failed: ${err.message}`, 'error');
    } finally {
      setFileUploading(false);
    }
  };

  // Helper to ensure file is uploaded to server and returns server filepath
  const ensureUploaded = async () => {
    if (!file) throw new Error('No metadata file selected.');
    if (uploadedRef && uploadedRef.file === file && uploadedRef.filepath) {
      return uploadedRef.filepath;
    }
    setFileUploading(true);
    try {
      const up = await uploadFile(file);
      setUploadedRef({ file, filepath: up.filepath });
      return up.filepath;
    } finally {
      setFileUploading(false);
    }
  };

  // Fetch File Info
  const handleShowFileInfo = async () => {
    if (!file) return;
    setFileInfoLoading(true);
    setFileInfoModalOpen(true);
    try {
      const serverPath = await ensureUploaded();
      const res = await fetch('/api/data-management/metadata-import/file-info', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ filepath: serverPath }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || data.error || 'Failed to analyze metadata file');
      }
      setFileInfoData(data.info);
    } catch (err) {
      showToast(err.message, 'error');
      setFileInfoModalOpen(false);
    } finally {
      setFileInfoLoading(false);
    }
  };

  // Validation Dry-Run
  const handleValidate = async () => {
    if (!file) {
      showToast('Please select a metadata file first.', 'warning');
      return;
    }
    if (!targetInstance) {
      showToast('Please select a target DHIS2 instance (Online or Offline)', 'error');
      return;
    }
    setLoading(true);
    try {
      const serverPath = await ensureUploaded();
      const res = await fetch('/api/data-management/metadata-import/dry-run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filepath: serverPath,
          target_instance: targetInstance,
          api_version: apiVersion,
          import_strategy: strategy,
          identifier: identifier,
          merge_mode: mergeMode,
          atomic_mode: atomic,
          exec_mode: execMode,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Metadata dry-run failed'));
      subscribeToJob(data.job_id);
      showToast(`Validating metadata package with dry-run #${data.job_id}`, 'info');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
    }
  };

  // Commit Execution
  const handleCommit = async () => {
    if (!file) {
      showToast('Please select a metadata file first.', 'warning');
      return;
    }
    if (!targetInstance) {
      showToast('Please select a target DHIS2 instance (Online or Offline)', 'error');
      return;
    }
    setLoading(true);
    try {
      const serverPath = await ensureUploaded();
      const res = await fetch('/api/data-management/metadata-import/run', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filepath: serverPath,
          target_instance: targetInstance,
          api_version: apiVersion,
          import_mode: importMode,
          import_strategy: strategy,
          identifier: identifier,
          merge_mode: mergeMode,
          atomic_mode: atomic,
          exec_mode: execMode,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(extractErrorMessage(data, 'Metadata import failed to start'));
      subscribeToJob(data.job_id);
      showToast(`Started metadata import job #${data.job_id}`, 'success');
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      setLoading(false);
      setShowConfirm(false);
    }
  };

  const handlePrimaryAction = () => {
    if (!file) {
      showToast('Please select a metadata file first.', 'warning');
      return;
    }
    if (!targetInstance) {
      showToast('Please select a target DHIS2 instance (Online or Offline)', 'error');
      return;
    }
    if (importMode === 'COMMIT') {
      setShowConfirm(true);
    } else {
      handleValidate();
    }
  };

  const destName = targetInstance === 'dhis2_offline' ? 'Offline DHIS2' : targetInstance === 'dhis2_online' ? 'Online DHIS2' : 'DHIS2';

  const filteredContents = fileInfoData?.contents
    ? Object.entries(fileInfoData.contents).filter(([key]) =>
        key.toLowerCase().includes(fileInfoFilter.toLowerCase())
      )
    : [];

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="DHIS2 Metadata Importer"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
          { label: 'Metadata Import' },
        ]}
      />

      {/* Unified Configuration Card */}
      <Card>
        <CardContent className="space-y-6">
          {/* Target Instance Selection */}
          <div className="space-y-2">
            <label className="block text-sm font-bold text-slate-800 dark:text-slate-200">
              Target DHIS2 Instance
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setTargetInstance('dhis2_online')}
                className={`p-3 rounded-lg border text-left flex items-center justify-between transition-all ${
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
                className={`p-3 rounded-lg border text-left flex items-center justify-between transition-all ${
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

          {/* Metadata File Selection */}
          <div className="space-y-2 pt-2 border-t border-slate-100 dark:border-slate-800">
            <div className="flex items-center justify-between">
              <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
                Metadata Package File (.json or .zip)
              </label>
              {file && (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Info className="w-3.5 h-3.5 text-teal-600" />}
                  onClick={handleShowFileInfo}
                  className="text-xs text-teal-700 dark:text-teal-400 h-7"
                >
                  Inspect Contents ({file.name})
                </Button>
              )}
            </div>
            <FileDropzone
              id="metadata-file-dropzone"
              accept=".json,.zip"
              maxSize={150 * 1024 * 1024}
              file={file}
              value={file}
              onFileSelect={handleFileChange}
              onChange={handleFileChange}
              onRemove={() => handleFileChange(null)}
              uploading={fileUploading}
              error={fileUploadError}
            />
          </div>

          {/* Import Options Grid */}
          <div className="space-y-3 pt-2 border-t border-slate-100 dark:border-slate-800">
            <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300">
              Import Options
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
              <Select
                label="Import Mode"
                value={importMode}
                onChange={(e) => setImportMode(e.target.value)}
                options={[
                  { value: 'COMMIT', label: 'COMMIT (Apply Changes)' },
                  { value: 'VALIDATE', label: 'VALIDATE (Preview Only)' },
                ]}
              />

              <Select
                label="Import Strategy"
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                options={[
                  { value: 'CREATE_AND_UPDATE', label: 'Create & Update (Default)' },
                  { value: 'CREATE', label: 'Create New Only' },
                  { value: 'UPDATE', label: 'Update Existing Only' },
                ]}
              />

              <Select
                label="Identifier"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                options={[
                  { value: 'UID', label: 'UID (Default)' },
                  { value: 'CODE', label: 'CODE' },
                ]}
              />

              <Select
                label="Merge Mode"
                value={mergeMode}
                onChange={(e) => setMergeMode(e.target.value)}
                options={[
                  { value: 'MERGE', label: 'MERGE (Default)' },
                  { value: 'REPLACE', label: 'REPLACE' },
                ]}
              />

              <Select
                label="API Version"
                value={apiVersion}
                onChange={(e) => setApiVersion(e.target.value)}
                options={[
                  { value: 'auto-detect', label: 'Auto-detect' },
                  { value: '42', label: 'Version 42' },
                  { value: '41', label: 'Version 41' },
                  { value: '40', label: 'Version 40' },
                  { value: '39', label: 'Version 39' },
                  { value: '38', label: 'Version 38' },
                  { value: '37', label: 'Version 37' },
                ]}
              />

              <Select
                label="Execution"
                value={execMode}
                onChange={(e) => setExecMode(e.target.value)}
                options={[
                  { value: 'Direct (Synchronous)', label: 'Direct (Synchronous)' },
                  { value: 'Background (Async)', label: 'Background (Async Task)' },
                ]}
              />
            </div>

            <div className="pt-1">
              <Switch
                label="Atomic Mode"
                checked={atomic}
                onChange={setAtomic}
              />
            </div>
          </div>

          {/* Action Buttons Centered */}
          <div className="flex items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
            {importMode === 'COMMIT' && (
              <Button
                variant="secondary"
                icon={<Eye className="w-4 h-4 mr-1.5 text-slate-600" />}
                loading={loading}
                disabled={!file || !targetInstance || fileUploading || isViewer}
                onClick={handleValidate}
              >
                Validate First (Dry-Run)
              </Button>
            )}

            <Button
              variant="primary"
              icon={importMode === 'COMMIT' ? <Play className="w-4 h-4 mr-1.5" /> : <Eye className="w-4 h-4 mr-1.5" />}
              loading={loading || fileUploading}
              disabled={!file || !targetInstance || fileUploading || isViewer}
              onClick={handlePrimaryAction}
            >
              {fileUploading
                ? 'Uploading to Hub...'
                : importMode === 'COMMIT'
                ? 'Import Metadata'
                : 'Validate Metadata (Dry-Run)'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Real-time Progress & Live Job Output */}
      <JobPanel
        jobId={activeJobId}
        jobState={jobState}
        logs={liveLogs}
        isStreaming={isStreaming}
        onCancel={cancelActiveJob}
        onReset={resetJob}
        title="Metadata Import Progress"
      />

      {/* Confirmation Dialog for Commit */}
      <ConfirmDialog
        open={showConfirm}
        targetSystem={targetInstance}
        title="Confirm Metadata Commit"
        message={`This will commit the metadata package "${file?.name}" directly into ${destName} using the saved credentials with strategy "${strategy}", identifier "${identifier}", and merge mode "${mergeMode}". Are you sure you want to proceed?`}
        confirmText="Confirm & Commit"
        onConfirm={handleCommit}
        onCancel={() => setShowConfirm(false)}
      />

      {/* File Info Modal */}
      <Modal
        isOpen={fileInfoModalOpen}
        onClose={() => setFileInfoModalOpen(false)}
        title="Metadata Package Information"
        description="Detailed structural breakdown of objects inside this metadata file."
        size="lg"
        footer={
          <Button variant="secondary" size="md" onClick={() => setFileInfoModalOpen(false)}>
            Close
          </Button>
        }
      >
        {fileInfoLoading ? (
          <div className="py-12 flex flex-col items-center justify-center space-y-3">
            <div className="w-8 h-8 border-3 border-teal-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-sm text-slate-500">Reading and analyzing metadata structure...</p>
          </div>
        ) : fileInfoData ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 text-xs">
              <div>
                <span className="text-slate-400 block">File Name</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200 truncate block">
                  {fileInfoData.filename}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">File Size</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  {(fileInfoData.size / 1024).toFixed(1)} KB ({fileInfoData.size.toLocaleString()} bytes)
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">Modified</span>
                <span className="font-semibold text-slate-800 dark:text-slate-200">
                  {fileInfoData.modified}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block">Total Objects</span>
                <span className="font-bold text-teal-600 dark:text-teal-400 text-sm">
                  {fileInfoData.total_objects.toLocaleString()} objects
                </span>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                  Contents Breakdown ({filteredContents.length} types)
                </span>
                <div className="relative w-48">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    type="text"
                    value={fileInfoFilter}
                    onChange={(e) => setFileInfoFilter(e.target.value)}
                    placeholder="Filter objects..."
                    className="w-full text-xs pl-8 pr-2 py-1 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-teal-500"
                  />
                </div>
              </div>

              <div className="max-h-72 overflow-y-auto border border-slate-200 dark:border-slate-800 rounded-xl divide-y divide-slate-100 dark:divide-slate-800/80">
                {filteredContents.length === 0 ? (
                  <p className="p-4 text-xs text-center text-slate-400">No matching metadata objects found.</p>
                ) : (
                  filteredContents.map(([key, count]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between px-3.5 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/40 text-xs"
                    >
                      <span className="font-mono text-slate-700 dark:text-slate-300 font-medium">
                        {key}
                      </span>
                      <span className="px-2 py-0.5 rounded-full font-semibold bg-teal-100 dark:bg-teal-950/60 text-teal-800 dark:text-teal-300">
                        {count.toLocaleString()} {count === 1 ? 'item' : 'items'}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
};

export default MetadataImportPage;
