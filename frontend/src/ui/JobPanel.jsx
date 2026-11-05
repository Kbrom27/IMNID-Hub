import React, { useState, useEffect, useRef } from 'react';
import {
  Download,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Clock,
  Ban,
  RefreshCw,
  FolderDown,
} from 'lucide-react';
import Card, { CardHeader, CardTitle, CardContent } from './Card';
import Badge from './Badge';
import StatusBadge from './StatusBadge';
import ProgressBar from './ProgressBar';
import Button from './Button';
import LogViewer from './LogViewer';
import { getAuthToken } from '../hooks/useAuthFetch';
import { useToast } from './ToastProvider';
import {
  getStoredDirectoryHandle,
  setStoredDirectoryHandle,
  saveBlobToDirectory,
  saveBlobWithPicker,
} from '../utils/localFileSystem';

function formatPanelText(val, fallback = '') {
  if (val === null || val === undefined) return fallback;
  if (typeof val === 'string') {
    return val === '[object Object]' ? fallback : val;
  }
  if (typeof val === 'object') {
    if (val.message) return formatPanelText(val.message, fallback);
    if (val.detail) return formatPanelText(val.detail, fallback);
    if (val.error) return formatPanelText(val.error, fallback);
    if (val.msg) return formatPanelText(val.msg, fallback);
    try {
      return JSON.stringify(val);
    } catch {
      return fallback;
    }
  }
  return String(val);
}

/**
 * JobPanel Component
 * Standard execution status and live streaming panel for background jobs across all modules.
 *
 * When the job completes with a result_file, the file is automatically saved directly
 * to the user's selected directory (if chosen via Browse Local) or downloaded via browser.
 * A "Re-download" button is shown if they need to download again.
 */
const JobPanel = ({
  jobId,
  jobState = {},
  logs = [],
  liveLogs = [],
  isStreaming = false,
  onCancel,
  onReset,
  onDismiss,
  title = 'Job Execution',
  downloadPrefix,
  className = '',
  showDownloadButtons = true,
}) => {
  const incomingLogs = (logs && logs.length > 0) ? logs : (liveLogs && liveLogs.length > 0) ? liveLogs : [];
  const [fetchedLogs, setFetchedLogs] = useState([]);

  const { showToast } = useToast();
  const [downloading, setDownloading] = useState(false);
  const autoSavedJobsRef = useRef(new Set());
  const [savedLocation, setSavedLocation] = useState('');
  const [localResultFile, setLocalResultFile] = useState(null);
  const [localCsvFile, setLocalCsvFile] = useState(null);

  const safeJobState = jobState || {};
  const status = safeJobState.status || (isStreaming ? 'running' : 'idle');
  const token = getAuthToken();
  const handleReset = onReset || onDismiss;

  const artifacts = safeJobState.artifacts || {};

  const primaryResultFile =
    localResultFile ||
    safeJobState.result_file ||
    safeJobState.artifacts?.output_xlsx ||
    safeJobState.artifacts?.output_file ||
    safeJobState.artifacts?.filename ||
    safeJobState.result?.output_xlsx ||
    safeJobState.result?.output_file ||
    safeJobState.result?.filename ||
    (artifacts && Object.values(artifacts).find((f) => typeof f === 'string' && f.endsWith('.xlsx')));

  const csvResultFile =
    localCsvFile ||
    safeJobState.artifacts?.output_csv ||
    safeJobState.artifacts?.csv_filename ||
    safeJobState.result?.output_csv ||
    safeJobState.result?.csv_filename;

  // Persisted log fallback: fetch server log file if incoming live logs are empty or when terminal
  useEffect(() => {
    let isMounted = true;
    if (!jobId) {
      setFetchedLogs([]);
      return;
    }

    if (incomingLogs.length > 0 && isStreaming) {
      return;
    }

    const fetchPersistedLogs = async () => {
      try {
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const res = await fetch(`/api/jobs/${jobId}/logs`, { headers });
        if (res.ok) {
          const text = await res.text();
          if (text && isMounted) {
            const lines = text.split('\n').filter((l) => l.trim().length > 0);
            if (lines.length > 0) {
              setFetchedLogs(lines);
            }
          }
        }
      } catch (err) {
        console.warn('Failed to load persisted logs for job', jobId, err);
      }
    };

    if (incomingLogs.length === 0 || !isStreaming) {
      fetchPersistedLogs();
    }

    if (status === 'completed' || status === 'failed' || status === 'canceled') {
      const timer = setTimeout(fetchPersistedLogs, 500);
      return () => clearTimeout(timer);
    }

    return () => {
      isMounted = false;
    };
  }, [jobId, status, isStreaming, incomingLogs.length, token]);

  // Compute effective logs to render in the stream viewer
  let effectiveLogs = [];
  if (incomingLogs.length > 0) {
    effectiveLogs = incomingLogs;
  } else if (fetchedLogs.length > 0) {
    effectiveLogs = fetchedLogs;
  } else if (safeJobState.errors && safeJobState.errors.length > 0) {
    effectiveLogs = safeJobState.errors.map((e) => `[ERROR] ${formatPanelText(e)}`);
  } else if (safeJobState.message) {
    effectiveLogs = [`[INFO] ${formatPanelText(safeJobState.message)}`];
  }

  const statusConfig = {
    running: { variant: 'primary', label: 'Running', dot: true, icon: <Clock className="w-3.5 h-3.5 animate-spin" /> },
    completed: { variant: 'success', label: 'Completed', dot: false, icon: <CheckCircle2 className="w-3.5 h-3.5" /> },
    failed: { variant: 'danger', label: 'Failed', dot: false, icon: <AlertCircle className="w-3.5 h-3.5" /> },
    canceled: { variant: 'neutral', label: 'Canceled', dot: false, icon: <Ban className="w-3.5 h-3.5" /> },
    idle: { variant: 'neutral', label: 'Idle', dot: false, icon: null },
  };

  const currentStatus = statusConfig[status] || statusConfig.idle;
  const progress = safeJobState.progress !== undefined ? safeJobState.progress : 0;

  // Resolve download URL
  const getDownloadUrl = (fileName) => {
    if (!fileName) return null;
    let clean = String(fileName).replace(/\\/g, '/').trim();
    if (clean.startsWith('[Local Folder]')) {
      clean = clean.split('/').pop();
    }
    const safeName = clean.split('/').filter(Boolean).pop() || clean;
    const encoded = encodeURIComponent(safeName);

    let base = downloadPrefix;
    if (!base) {
      if (typeof window !== 'undefined' && window.location.pathname.startsWith('/data-management')) {
        base = '/api/data-management/download';
      } else if (typeof window !== 'undefined' && window.location.pathname.startsWith('/hmis')) {
        base = '/api/hmis/download';
      } else if (typeof window !== 'undefined' && window.location.pathname.startsWith('/concepts')) {
        base = '/api/concepts/download';
      } else {
        base = '/api/v1/interop/download';
      }
    }
    return `${base}/${encoded}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
  };

  // Simple browser download fallback
  const triggerDownload = (blob, fileName) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  };

  // Download a file from the server and save directly to folder or download
  const downloadFile = async (filePath) => {
    if (!filePath) return;
    const downloadUrl = getDownloadUrl(filePath);
    const safeName = String(filePath).replace(/\\/g, '/').split('/').pop();

    setDownloading(true);
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(downloadUrl, { headers });
      if (res.status === 404) {
        showToast(`File '${safeName}' not found on server. The export may have completed with 0 records.`, 'error');
        return;
      }
      if (!res.ok) throw new Error(`Server returned HTTP ${res.status}`);
      const blob = await res.blob();

      // Check if user selected a local directory
      let savedDirectly = false;
      const stored = getStoredDirectoryHandle();
      if (stored?.handle) {
        try {
          await saveBlobToDirectory(stored.handle, safeName, blob);
          savedDirectly = true;
          setSavedLocation(`Saved directly to folder: "${stored.name}"`);
          showToast(`File saved directly to folder "${stored.name}" (${safeName})`, 'success');
        } catch (fsErr) {
          console.warn('Direct file system save failed, falling back to browser download:', fsErr);
        }
      }

      if (!savedDirectly) {
        triggerDownload(blob, safeName);
        setSavedLocation(`Downloaded to browser Downloads folder (~/Downloads)`);
        showToast(`Downloaded ${safeName} to Downloads`, 'info');
      }
    } catch (err) {
      showToast(err.message || 'Failed to download file', 'error');
    } finally {
      setDownloading(false);
    }
  };

  // Explicitly prompt user to choose destination folder on their computer
  const saveFileAs = async (filePath) => {
    if (!filePath) return;
    const downloadUrl = getDownloadUrl(filePath);
    const safeName = String(filePath).replace(/\\/g, '/').split('/').pop();

    setDownloading(true);
    try {
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(downloadUrl, { headers });
      if (!res.ok) throw new Error(`Server returned HTTP ${res.status}`);
      const blob = await res.blob();

      // Priority 1: Modern showSaveFilePicker (native OS Save As dialog)
      if (typeof window !== 'undefined' && 'showSaveFilePicker' in window) {
        try {
          const fileHandle = await saveBlobWithPicker(safeName, blob);
          if (fileHandle) {
            setSavedLocation(`Saved as: "${fileHandle.name || safeName}"`);
            showToast(`File saved successfully as "${fileHandle.name || safeName}"`, 'success');
            return;
          }
        } catch (pickerErr) {
          if (pickerErr.name === 'AbortError') return;
          console.warn('showSaveFilePicker error:', pickerErr);
        }
      }

      // Priority 2: showDirectoryPicker to pick destination folder
      if (typeof window !== 'undefined' && 'showDirectoryPicker' in window) {
        try {
          const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
          if (dirHandle) {
            await saveBlobToDirectory(dirHandle, safeName, blob);
            setStoredDirectoryHandle(dirHandle, dirHandle.name);
            setSavedLocation(`Saved to folder: "${dirHandle.name}"`);
            showToast(`File saved directly to folder "${dirHandle.name}" (${safeName})`, 'success');
            return;
          }
        } catch (dirErr) {
          if (dirErr.name === 'AbortError') return;
          console.warn('showDirectoryPicker error:', dirErr);
        }
      }

      // Priority 3: Fallback standard browser download
      triggerDownload(blob, safeName);
      setSavedLocation(`Downloaded to browser Downloads folder (~/Downloads)`);
      showToast(`Downloaded ${safeName} to Downloads`, 'info');
    } catch (err) {
      showToast(err.message || 'Failed to save file', 'error');
    } finally {
      setDownloading(false);
    }
  };

  // If completed and no result file detected yet, fetch job detail directly
  useEffect(() => {
    if (status === 'completed' && jobId && !primaryResultFile) {
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      fetch(`/api/jobs/${jobId}`, { headers })
        .then((r) => (r.ok ? r.json() : null))
        .then((j) => {
          if (!j) return;
          const resFile =
            j.result_file ||
            j.artifacts?.output_xlsx ||
            j.artifacts?.output_file ||
            j.artifacts?.filename ||
            j.result?.output_xlsx ||
            j.result?.output_file;
          const csvFile = j.artifacts?.output_csv || j.result?.output_csv;
          if (resFile) setLocalResultFile(resFile);
          if (csvFile) setLocalCsvFile(csvFile);
        })
        .catch(() => {});
    }
  }, [status, jobId, primaryResultFile, token]);

  // Auto-download / auto-save directly to chosen local directory when job completes
  useEffect(() => {
    if (status === 'completed' && jobId) {
      const primary = primaryResultFile;
      const csv = csvResultFile;
      const fileToSave = primary || csv;
      if (!fileToSave) return;

      if (autoSavedJobsRef.current.has(jobId)) return;
      autoSavedJobsRef.current.add(jobId);

      const performAutoSave = async () => {
        try {
          if (primary) {
            await downloadFile(primary);
          }
          if (csv && csv !== primary) {
            await downloadFile(csv);
          }
        } catch (err) {
          console.error('Auto-save execution failed:', err);
        }
      };

      performAutoSave();
    }
  }, [status, jobId, primaryResultFile, csvResultFile]);

  if (!jobId && incomingLogs.length === 0 && fetchedLogs.length === 0) return null;

  return (
    <Card className={`border-slate-300 dark:border-slate-700 shadow-md ${className}`}>
      <CardHeader className="flex flex-row items-center justify-between gap-3 bg-slate-50/80 dark:bg-slate-800/50">
        <div className="flex items-center gap-3 min-w-0">
          <CardTitle className="text-sm sm:text-base font-bold text-slate-900 dark:text-slate-100 truncate">
            {title}
          </CardTitle>
          {jobId && (
            <span className="font-mono text-xs px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
              #{jobId}
            </span>
          )}
          <StatusBadge status={status} size="sm" />
        </div>

        <div className="flex items-center gap-2">
          {isStreaming && onCancel && (
            <Button
              variant="danger"
              size="sm"
              onClick={onCancel}
              icon={<XCircle className="w-3.5 h-3.5" />}
            >
              Cancel
            </Button>
          )}
          {!isStreaming && handleReset && (
            <Button variant="ghost" size="sm" onClick={handleReset}>
              Clear
            </Button>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Failed Error Banner */}
        {status === 'failed' && (
          <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 space-y-1">
            <div className="flex items-center gap-2 text-rose-900 dark:text-rose-200 text-xs font-bold">
              <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0" />
              <span>Job Execution Failed</span>
            </div>
            <p className="text-xs text-rose-800 dark:text-rose-300 ml-6">
              {formatPanelText(
                safeJobState.message || (safeJobState.errors && safeJobState.errors[0]),
                'An error occurred during execution.'
              )}
            </p>
          </div>
        )}

        {/* Progress & Status Message */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
            <span className="truncate max-w-md text-slate-600 dark:text-slate-400">
              {formatPanelText(safeJobState.message) || (isStreaming ? 'Processing job in background...' : 'Ready')}
            </span>
            <span className="font-mono">{progress}%</span>
          </div>
          <ProgressBar
            value={progress}
            color={status === 'failed' ? 'rose' : status === 'completed' ? 'emerald' : 'teal'}
            size="md"
          />
        </div>

        {/* Counts summary if present */}
        {(safeJobState.total > 0 || safeJobState.success_count > 0 || safeJobState.fail_count > 0 || safeJobState.artifacts?.rejected_count > 0) && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 p-3 rounded-md bg-slate-50 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-800 text-xs">
            <div>
              <span className="text-slate-400 block text-[10px] uppercase font-bold">Total</span>
              <span className="font-bold text-slate-800 dark:text-slate-200 text-sm">
                {safeJobState.total || 0}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px] uppercase font-bold">Processed</span>
              <span className="font-bold text-teal-600 dark:text-teal-400 text-sm">
                {(safeJobState.success_count || 0) + (safeJobState.fail_count || 0) + (safeJobState.artifacts?.rejected_count || 0)}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px] uppercase font-bold">Success</span>
              <span className="font-bold text-emerald-600 dark:text-emerald-400 text-sm">
                {safeJobState.success_count || 0}
              </span>
            </div>
            {safeJobState.artifacts?.rejected_count !== undefined && (
              <div>
                <span className="text-slate-400 block text-[10px] uppercase font-bold">Rejected</span>
                <span className="font-bold text-amber-600 dark:text-amber-400 text-sm">
                  {safeJobState.artifacts.rejected_count || 0}
                </span>
              </div>
            )}
            <div>
              <span className="text-slate-400 block text-[10px] uppercase font-bold">Failed</span>
              <span className="font-bold text-rose-600 dark:text-rose-400 text-sm">
                {safeJobState.fail_count || 0}
              </span>
            </div>
          </div>
        )}

        {/* Completed: show file info, location status, and action buttons */}
        {status === 'completed' && (primaryResultFile || csvResultFile) && (
          <div className="p-3.5 rounded-lg bg-emerald-50/80 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/80 space-y-2">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <span className="text-xs font-bold text-emerald-950 dark:text-emerald-100 truncate">
                    {String(primaryResultFile || csvResultFile).split('/').pop()}
                    {csvResultFile && primaryResultFile && csvResultFile !== primaryResultFile && (
                      <span className="text-emerald-700/80 dark:text-emerald-300/80 font-medium ml-1.5">
                        & {String(csvResultFile).split('/').pop()}
                      </span>
                    )}
                  </span>
                </div>
                <p className="text-[11px] text-emerald-800 dark:text-emerald-300 mt-0.5 ml-6">
                  {savedLocation ||
                    (getStoredDirectoryHandle()?.name
                      ? `Saved directly to folder: "${getStoredDirectoryHandle()?.name}"`
                      : 'Saved on server & downloaded to browser Downloads folder (~/Downloads)')}
                </p>
              </div>

              {showDownloadButtons && (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    disabled={downloading}
                    onClick={() => saveFileAs(primaryResultFile || csvResultFile)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-teal-600 hover:bg-teal-700 text-white text-xs font-semibold rounded-md shadow-sm transition-colors disabled:opacity-60 cursor-pointer"
                    title="Choose exact destination folder on your computer to save this file"
                  >
                    <FolderDown className="w-3.5 h-3.5" />
                    <span>Save to Folder...</span>
                  </button>

                  <button
                    type="button"
                    disabled={downloading}
                    onClick={() => downloadFile(primaryResultFile || csvResultFile)}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-200 hover:bg-slate-300 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-medium rounded-md transition-colors disabled:opacity-60 cursor-pointer"
                    title="Download file again via browser"
                  >
                    {downloading ? (
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Download className="w-3.5 h-3.5" />
                    )}
                    <span>Download</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Additional artifacts (not the main result_file) */}
        {showDownloadButtons && Object.entries(artifacts).length > 0 && (
          <div className="flex flex-wrap gap-2">
            {Object.entries(artifacts).map(([k, file]) => {
              if (
                !file ||
                typeof file !== 'string' ||
                !file.trim() ||
                file === safeJobState.result_file ||
                !/\.(xlsx|xls|csv|json|zip|txt|pdf)$/i.test(file)
              ) {
                return null;
              }
              const safeName = file.split('/').pop();
              return (
                <button
                  key={k}
                  type="button"
                  disabled={downloading}
                  onClick={() => downloadFile(file)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white dark:bg-slate-800 text-emerald-800 dark:text-emerald-300 hover:bg-emerald-50 dark:hover:bg-slate-700 border border-emerald-300 dark:border-emerald-700 text-xs font-medium rounded-md transition-colors disabled:opacity-60 cursor-pointer"
                >
                  <Download className="w-3.5 h-3.5 text-emerald-600" />
                  <span>{safeName}</span>
                </button>
              );
            })}
          </div>
        )}

        {/* Live Logs Stream */}
        <div className="space-y-1">
          <LogViewer
            logs={effectiveLogs}
            title="Live Output Stream"
            maxHeight="280px"
            logFileName={`job_${jobId || 'log'}.log`}
          />
        </div>
      </CardContent>
    </Card>
  );
};

export default JobPanel;
