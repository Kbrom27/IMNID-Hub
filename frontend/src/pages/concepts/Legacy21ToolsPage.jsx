import React, { useState, useEffect, useRef } from 'react';
import { Download, FileSpreadsheet, Wrench, Play, Upload, Server, XCircle } from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  TextInput,
  JobPanel,
  DirectoryPicker,
  FileDropzone,
} from '../../ui';
import { useAuth } from '../../context/AuthContext';
import { useToast } from '../../ui/ToastProvider';
import { TOOLS_21 } from './schemaConstants';

/**
 * OpenMRS 2.1 Legacy Concepts Page
 * Support for CM-11 and CM-12 legacy format exporters and converters with real job execution.
 * Tools are listed at the top as an interactive selection row, with their forms displayed at the bottom.
 */
const Legacy21ToolsPage = () => {
  const { authHeader, isViewer } = useAuth();
  const { showToast } = useToast();

  const [selectedToolId, setSelectedToolId] = useState('cm11_legacy_export');
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobState, setJobState] = useState(null);
  const [liveLogs, setLiveLogs] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);

  const eventSourceRef = useRef(null);

  const [inputs, setInputs] = useState({
    cm11_server_type: 'bahmni',
    cm11_output_dir: '/data/exports/legacy-concepts',
    cm11_filename: 'concepts.csv',
    cm12_input_file: '',
    cm12_parent_folder: 'MID',
    cm12_output_dir: '/data/exports',
  });

  const handleInputChange = (field, value) => {
    setInputs((prev) => ({ ...prev, [field]: value }));
  };

  // SSE Job Listener with resilient polling fallback
  useEffect(() => {
    if (!activeJobId) return;

    let pollInterval = null;

    const fetchLogsFallback = async () => {
      try {
        const res = await fetch(`/api/jobs/${activeJobId}/logs`, {
          headers: authHeader(),
        });
        if (res.ok) {
          const text = await res.text();
          if (text) {
            const lines = text.split('\n').filter(Boolean);
            if (lines.length > 0) {
              setLiveLogs(lines);
            }
          }
        }
      } catch (e) {
        // ignore
      }
    };

    const fetchStatus = async () => {
      try {
        const res = await fetch(`/api/jobs/${activeJobId}`, {
          headers: authHeader(),
        });
        if (res.ok) {
          const data = await res.json();
          setJobState(data);
          if (data.errors && Array.isArray(data.errors) && data.errors.length > 0) {
            setLiveLogs((prev) => {
              const existing = new Set(prev);
              const toAdd = data.errors.filter((e) => !existing.has(e));
              return toAdd.length > 0 ? [...prev, ...toAdd] : prev;
            });
          }
          if (['completed', 'failed', 'cancelled', 'canceled'].includes(data.status)) {
            setIsStreaming(false);
            if (pollInterval) clearInterval(pollInterval);
            fetchLogsFallback();
          }
        }
      } catch (e) {
        console.error('Job poll error', e);
      }
    };

    fetchStatus();
    fetchLogsFallback();
    pollInterval = setInterval(fetchStatus, 2000);

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const token =
      localStorage.getItem('imnid_token') ||
      localStorage.getItem('access_token') ||
      localStorage.getItem('token') ||
      '';
    const es = new EventSource(
      `/api/jobs/${activeJobId}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`
    );
    eventSourceRef.current = es;
    setIsStreaming(true);

    const handlePayload = (parsed) => {
      if (!parsed) return;
      if (parsed.type === 'log') {
        const line =
          typeof parsed.data === 'string'
            ? parsed.data
            : parsed.data?.line ||
              parsed.data?.text ||
              parsed.message ||
              (typeof parsed === 'string' ? parsed : JSON.stringify(parsed.data || parsed));
        if (line) setLiveLogs((prev) => [...prev, line]);
      } else if (parsed.type === 'progress') {
        setJobState((prev) => ({ ...(prev || {}), ...(parsed.data || parsed) }));
      } else if (parsed.type === 'status' || parsed.type === 'state') {
        const stateData = parsed.data || parsed;
        if (stateData) {
          setJobState((prev) => ({ ...(prev || {}), ...stateData }));
          if (['completed', 'failed', 'cancelled', 'canceled'].includes(stateData.status)) {
            setIsStreaming(false);
            if (es) es.close();
            if (pollInterval) clearInterval(pollInterval);
            fetchStatus();
            fetchLogsFallback();
          }
        }
      }
    };

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handlePayload(data);
      } catch (err) {
        if (event.data) setLiveLogs((prev) => [...prev, event.data]);
      }
    };

    es.addEventListener('log', (e) => {
      try {
        const data = JSON.parse(e.data);
        const line = data.line || data.text || (typeof data === 'string' ? data : e.data);
        if (line) setLiveLogs((prev) => [...prev, line]);
      } catch {
        if (e.data) setLiveLogs((prev) => [...prev, e.data]);
      }
    });

    es.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data) setJobState((prev) => ({ ...(prev || {}), ...data }));
      } catch {}
    });

    es.addEventListener('status', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data) {
          setJobState((prev) => ({ ...(prev || {}), ...data }));
          if (['completed', 'failed', 'cancelled', 'canceled'].includes(data.status)) {
            setIsStreaming(false);
            if (es) es.close();
            if (pollInterval) clearInterval(pollInterval);
            fetchStatus();
            fetchLogsFallback();
          }
        }
      } catch {}
    });

    es.onerror = () => {
      // Keep polling fallback active and attempt log file fetch
      fetchLogsFallback();
    };

    return () => {
      if (es) es.close();
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [activeJobId]);

  const handleFileUpload = async (file, targetField) => {
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/concepts/upload', {
        method: 'POST',
        headers: authHeader(),
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        handleInputChange(targetField, data.filepath);
        showToast(`Uploaded "${file.name}"`, 'success');
      } else {
        showToast(data.detail || 'Upload failed', 'error');
      }
    } catch (err) {
      showToast('Upload error: ' + err.message, 'error');
    }
  };

  const submitJob = async (endpoint, payload) => {
    setLiveLogs([]);
    setJobState({ status: 'queued', progress: 0 });

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();
      if (res.ok) {
        setActiveJobId(data.job_id);
        showToast(`Job #${data.job_id} launched`, 'success');
      } else {
        showToast(data.detail || 'Failed to submit operation', 'error');
        setJobState({ status: 'failed', error: data.detail });
      }
    } catch (err) {
      showToast('Network error: ' + err.message, 'error');
      setJobState({ status: 'failed', error: err.message });
    }
  };

  const cancelJob = async () => {
    if (!activeJobId) return;
    try {
      await fetch(`/api/jobs/${activeJobId}/cancel`, {
        method: 'POST',
        headers: authHeader(),
      });
      setIsStreaming(false);
      showToast('Cancellation requested', 'info');
    } catch (err) {
      console.error('Failed to cancel job:', err);
    }
  };

  const currentTool = TOOLS_21.find((t) => t.id === selectedToolId) || TOOLS_21[0];
  const isRunning =
    isStreaming ||
    ['queued', 'running', 'pending', 'in_progress'].includes(jobState?.status);

  const handleRun = async () => {
    if (selectedToolId === 'cm11_legacy_export') {
      submitJob('/api/concepts/legacy-export', {
        server_type: inputs.cm11_server_type || 'bahmni',
        output_dir: inputs.cm11_output_dir || null,
        filename: inputs.cm11_filename || 'concepts.csv',
      });
    } else if (selectedToolId === 'cm12_legacy_conv') {
      if (!inputs.cm12_input_file) {
        showToast('Please select or upload a mapping spreadsheet first.', 'warning');
        return;
      }
      submitJob('/api/concepts/legacy-convert', {
        input_file: inputs.cm12_input_file,
        parent_folder: inputs.cm12_parent_folder || 'MID',
        output_dir: inputs.cm12_output_dir || null,
      });
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Legacy 2.1 Tools"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Concepts & Forms', to: '/concepts' },
          { label: 'Legacy 2.1 Tools' },
        ]}
      />

      {/* Top Tool Selector */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 shadow-xs">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {TOOLS_21.map((tool) => {
            const isSelected = selectedToolId === tool.id;
            return (
              <button
                key={tool.id}
                type="button"
                onClick={() => setSelectedToolId(tool.id)}
                className={`p-3.5 rounded-xl text-left transition-all border flex items-center gap-3 cursor-pointer ${
                  isSelected
                    ? 'bg-teal-50/80 dark:bg-teal-950/50 border-teal-500 dark:border-teal-400 text-teal-950 dark:text-teal-100 shadow-2xs ring-1 ring-teal-500/20'
                    : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-white dark:bg-slate-900/60 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-850'
                }`}
              >
                <span className="font-sans text-xs font-bold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 shrink-0">
                  {tool.code}
                </span>
                <span className="font-semibold text-sm truncate">{tool.name}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Selected Tool Form & Run Card */}
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <span className="font-sans text-xs font-bold text-teal-700 dark:text-teal-300 px-2 py-0.5 rounded bg-teal-50 dark:bg-teal-950/60 border border-teal-200 dark:border-teal-800">
                {currentTool.code}
              </span>
              <CardTitle>{currentTool.name}</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* CM-11 */}
            {selectedToolId === 'cm11_legacy_export' && (
              <div className="space-y-5">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-xl bg-teal-50/50 dark:bg-teal-950/30 border border-teal-200 dark:border-teal-800 text-sm text-teal-900 dark:text-teal-200">
                  <div className="flex items-center gap-2.5">
                    <Server className="w-5 h-5 text-teal-600 dark:text-teal-400 shrink-0" />
                    <span>
                      Target: <strong>{inputs.cm11_server_type === 'bahmni' ? 'Bahmni 0.93 / OpenMRS 2.x (CentOS)' : 'OpenMRS 3.x (Localhost)'}</strong>
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-slate-500 dark:text-slate-400 text-xs font-semibold">Server Connection:</span>
                    <select
                      value={inputs.cm11_server_type}
                      onChange={(e) => handleInputChange('cm11_server_type', e.target.value)}
                      className="bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200 rounded-lg px-3 py-1.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-teal-500"
                    >
                      <option value="bahmni">Bahmni 0.93 (CentOS: 172.16.75.128)</option>
                      <option value="openmrs">OpenMRS 3.x (Localhost)</option>
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <TextInput
                    label="Output CSV Filename"
                    value={inputs.cm11_filename}
                    onChange={(e) => handleInputChange('cm11_filename', e.target.value)}
                    placeholder="concepts.csv"
                  />
                  <DirectoryPicker
                    label="Export Destination Directory"
                    value={inputs.cm11_output_dir}
                    onChange={(val) => handleInputChange('cm11_output_dir', val)}
                  />
                </div>
              </div>
            )}

            {/* CM-12 */}
            {selectedToolId === 'cm12_legacy_conv' && (
              <div className="space-y-5">
                <FileDropzone
                  label="DHIS2 to OpenMRS Mapping Spreadsheet"
                  accept=".xlsx,.xls,.csv"
                  selectedPath={inputs.cm12_input_file}
                  onFileSelected={(file) => handleFileUpload(file, 'cm12_input_file')}
                  onPathSelected={(val) => handleInputChange('cm12_input_file', val)}
                />

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <TextInput
                    label="Parent Output Folder Name"
                    value={inputs.cm12_parent_folder}
                    onChange={(e) => handleInputChange('cm12_parent_folder', e.target.value)}
                    placeholder="MID"
                  />
                  <DirectoryPicker
                    label="Output Root Directory"
                    value={inputs.cm12_output_dir}
                    onChange={(val) => handleInputChange('cm12_output_dir', val)}
                  />
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              {isRunning && (
                <Button
                  variant="danger"
                  icon={<XCircle className="w-4 h-4 mr-1.5" />}
                  onClick={cancelJob}
                >
                  Cancel Export
                </Button>
              )}

              <Button
                variant="primary"
                icon={<Play className="w-4 h-4 mr-1.5" />}
                loading={isRunning}
                disabled={isViewer || isRunning}
                onClick={handleRun}
              >
                {isRunning ? 'Exporting in Progress...' : `Execute ${currentTool.name}`}
              </Button>
            </div>
          </CardContent>
        </Card>

        <JobPanel
          jobId={activeJobId}
          jobState={jobState}
          logs={liveLogs}
          isStreaming={isStreaming}
          onCancel={cancelJob}
          onReset={() => {
            setActiveJobId(null);
            setJobState(null);
            setLiveLogs([]);
          }}
          title="Legacy Operation Status"
        />
      </div>
    </div>
  );
};

export default Legacy21ToolsPage;
