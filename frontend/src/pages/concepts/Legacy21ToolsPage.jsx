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
  const [uploadingField, setUploadingField] = useState(null);
  const [cm13FolderSource, setCm13FolderSource] = useState('folder');

  const eventSourceRef = useRef(null);

  const [inputs, setInputs] = useState({
    cm11_server_type: 'bahmni',
    cm11_output_dir: '/data/exports/legacy-concepts',
    cm11_filename: 'concepts.csv',
    cm12_input_file: '',
    cm12_parent_folder: 'MID',
    cm12_output_dir: '/data/exports',
    cm13_export_file: '',
    cm13_folder: '',
    cm13_mode: 'api',
    cm13_apply: false,
    cm13_server_type: 'bahmni',
    cm13_output_dir: '/data/exports/legacy-import',
    cm13_strict_set_check: false,
    cm13_check_only: false,
    cm13_delay_ms: 200,
    cm13_batch_size: 100,
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
    setUploadingField(targetField);
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
    } finally {
      setUploadingField(null);
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
    } else if (selectedToolId === 'cm13_legacy_import') {
      if (!inputs.cm13_folder && !inputs.cm13_check_only) {
        showToast('Please select or upload an import folder or zip archive first.', 'warning');
        return;
      }
      submitJob('/api/concepts/legacy-bulk-import', {
        export_file: inputs.cm13_export_file || null,
        folder: inputs.cm13_folder,
        mode: inputs.cm13_mode || 'api',
        apply: Boolean(inputs.cm13_apply),
        server_type: inputs.cm13_server_type || 'bahmni',
        output_dir: inputs.cm13_output_dir || null,
        strict_set_check: Boolean(inputs.cm13_strict_set_check),
        check_only: Boolean(inputs.cm13_check_only),
        delay_ms: Number(inputs.cm13_delay_ms) || 200,
        batch_size: Number(inputs.cm13_batch_size) || 100,
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
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
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
                  <DirectoryPicker
                    label="Export Destination Directory"
                    value={inputs.cm11_output_dir}
                    onChange={(val) => handleInputChange('cm11_output_dir', val)}
                  />
                  <TextInput
                    label="Output CSV Filename"
                    value={inputs.cm11_filename}
                    onChange={(e) => handleInputChange('cm11_filename', e.target.value)}
                    placeholder="concepts.csv"
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
                  filePath={inputs.cm12_input_file}
                  uploading={uploadingField === 'cm12_input_file'}
                  onFileSelect={(file) => handleFileUpload(file, 'cm12_input_file')}
                  onRemove={() => handleInputChange('cm12_input_file', '')}
                  helperText="Click to browse or drop DHIS2 mapping spreadsheet (.xlsx, .xls, .csv)"
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

            {/* CM-13 */}
            {selectedToolId === 'cm13_legacy_import' && (
              <div className="space-y-5">
                {/* Execution Mode & Safety Controls */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 space-y-2">
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                      Import Delivery Mode
                    </label>
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => handleInputChange('cm13_mode', 'api')}
                        className={`flex-1 py-2 px-3 rounded-lg text-xs font-semibold border transition-all cursor-pointer ${
                          inputs.cm13_mode === 'api'
                            ? 'bg-teal-600 text-white border-teal-600 shadow-xs'
                            : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700'
                        }`}
                      >
                        REST API Mode (Direct)
                      </button>
                      <button
                        type="button"
                        onClick={() => handleInputChange('cm13_mode', 'csv')}
                        className={`flex-1 py-2 px-3 rounded-lg text-xs font-semibold border transition-all cursor-pointer ${
                          inputs.cm13_mode === 'csv'
                            ? 'bg-teal-600 text-white border-teal-600 shadow-xs'
                            : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700'
                        }`}
                      >
                        Bahmni Admin CSV Mode
                      </button>
                    </div>
                    <p className="text-[11px] text-slate-500 dark:text-slate-400">
                      {inputs.cm13_mode === 'api'
                        ? 'Creates concepts directly via REST API with polite pacing, adaptive back-off, and state persistence.'
                        : 'Generates chunked CSV upload files and upload_order.txt for Bahmni Admin CSV management.'}
                    </p>
                  </div>

                  <div className={`p-4 rounded-xl border transition-all ${
                    inputs.cm13_apply
                      ? 'border-amber-300 dark:border-amber-700 bg-amber-50/70 dark:bg-amber-950/30'
                      : 'border-teal-300 dark:border-teal-800 bg-teal-50/70 dark:bg-teal-950/30'
                  }`}>
                    <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300 mb-2">
                      Execution Safety Control
                    </label>
                    <div className="flex items-center justify-between">
                      <div>
                        <span className={`text-xs font-bold ${inputs.cm13_apply ? 'text-amber-800 dark:text-amber-300' : 'text-teal-800 dark:text-teal-300'}`}>
                          {inputs.cm13_apply ? '⚠️ Live Apply Mode (Modifications Enabled)' : '🛡️ Safe Dry-Run Plan Only'}
                        </span>
                        <p className="text-[11px] text-slate-600 dark:text-slate-400 mt-0.5">
                          {inputs.cm13_apply
                            ? 'Will create concepts on the server or write chunked files.'
                            : 'Analyzes files & produces plan reports without touching existing data.'}
                        </p>
                      </div>
                      <label className="relative inline-flex items-center cursor-pointer">
                        <input
                          type="checkbox"
                          className="sr-only peer"
                          checked={inputs.cm13_apply}
                          onChange={(e) => handleInputChange('cm13_apply', e.target.checked)}
                        />
                        <div className="w-11 h-6 bg-slate-300 peer-focus:outline-none rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-slate-600 peer-checked:bg-amber-600"></div>
                      </label>
                    </div>
                  </div>
                </div>

                {/* Server selection for API mode */}
                {inputs.cm13_mode === 'api' && (
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-xl bg-teal-50/50 dark:bg-teal-950/30 border border-teal-200 dark:border-teal-800 text-sm text-teal-900 dark:text-teal-200">
                    <div className="flex items-center gap-2.5">
                      <Server className="w-5 h-5 text-teal-600 dark:text-teal-400 shrink-0" />
                      <span>
                        Target Server: <strong>{inputs.cm13_server_type === 'bahmni' ? 'Bahmni 0.93 / OpenMRS 2.x (CentOS: 172.16.75.128)' : 'OpenMRS 3.x (Localhost)'}</strong>
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500 dark:text-slate-400 text-xs font-semibold">Server Connection:</span>
                      <select
                        value={inputs.cm13_server_type}
                        onChange={(e) => handleInputChange('cm13_server_type', e.target.value)}
                        className="bg-white dark:bg-slate-900 border border-slate-300 dark:border-slate-700 text-slate-800 dark:text-slate-200 rounded-lg px-3 py-1.5 text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="bahmni">Bahmni 0.93 (CentOS: 172.16.75.128)</option>
                        <option value="openmrs">OpenMRS 3.x (Localhost)</option>
                      </select>
                    </div>
                  </div>
                )}

                {/* File / Folder Inputs */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <FileDropzone
                      label="Server Concepts Snapshot (CSV)"
                      accept=".csv"
                      filePath={inputs.cm13_export_file}
                      uploading={uploadingField === 'cm13_export_file'}
                      onFileSelect={(file) => handleFileUpload(file, 'cm13_export_file')}
                      onRemove={() => handleInputChange('cm13_export_file', '')}
                      helperText="Click to browse or drop server export CSV"
                    />
                    <p className="text-[11px] text-slate-500 dark:text-slate-400">
                      Export CSV from CM-11 or server. If left blank, the most recent export is used.
                    </p>
                  </div>

                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                        Import Source ({cm13FolderSource === 'folder' ? 'Folder Tree' : 'Zip Archive'})
                      </label>
                      <div className="flex rounded-md bg-slate-100 dark:bg-slate-800 p-0.5 border border-slate-200 dark:border-slate-700">
                        <button
                          type="button"
                          onClick={() => {
                            setCm13FolderSource('folder');
                            if (inputs.cm13_folder?.endsWith('.zip')) {
                              handleInputChange('cm13_folder', '');
                            }
                          }}
                          className={`px-2 py-0.5 text-[11px] font-semibold rounded transition-colors cursor-pointer ${
                            cm13FolderSource === 'folder'
                              ? 'bg-white dark:bg-slate-900 text-teal-700 dark:text-teal-300 shadow-2xs'
                              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                          }`}
                        >
                          📁 Folder Tree
                        </button>
                        <button
                          type="button"
                          onClick={() => setCm13FolderSource('zip')}
                          className={`px-2 py-0.5 text-[11px] font-semibold rounded transition-colors cursor-pointer ${
                            cm13FolderSource === 'zip'
                              ? 'bg-white dark:bg-slate-900 text-teal-700 dark:text-teal-300 shadow-2xs'
                              : 'text-slate-600 dark:text-slate-400 hover:text-slate-900'
                          }`}
                        >
                          📦 Zip Archive
                        </button>
                      </div>
                    </div>

                    {cm13FolderSource === 'folder' ? (
                      <DirectoryPicker
                        label=""
                        value={inputs.cm13_folder?.endsWith('.zip') ? '' : inputs.cm13_folder}
                        onChange={(val) => handleInputChange('cm13_folder', val)}
                        helperText="Browse your computer or select a server folder tree containing concepts.csv / concept_sets.csv"
                      />
                    ) : (
                      <FileDropzone
                        id="cm13_zip_upload"
                        accept=".zip"
                        filePath={inputs.cm13_folder?.endsWith('.zip') ? inputs.cm13_folder : ''}
                        uploading={uploadingField === 'cm13_folder'}
                        onFileSelect={(file) => handleFileUpload(file, 'cm13_folder')}
                        onRemove={() => handleInputChange('cm13_folder', '')}
                        helperText="Click to browse or drop .zip archive (e.g. from CM-12)"
                      />
                    )}
                    <p className="text-[11px] text-slate-500 dark:text-slate-400">
                      {cm13FolderSource === 'folder'
                        ? 'Select a folder containing concepts.csv and concept_sets.csv (recursively scanned).'
                        : 'Upload a .zip package of concepts exported from CM-12 (auto-extracted on server).'}
                    </p>
                  </div>
                </div>

                {/* Output Dir and Options */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <DirectoryPicker
                    label="Output Destination Directory"
                    value={inputs.cm13_output_dir}
                    onChange={(val) => handleInputChange('cm13_output_dir', val)}
                  />

                  <div className="flex items-center gap-4 pt-6">
                    <label className="flex items-center gap-2 cursor-pointer text-xs font-medium text-slate-700 dark:text-slate-300">
                      <input
                        type="checkbox"
                        checked={inputs.cm13_strict_set_check}
                        onChange={(e) => handleInputChange('cm13_strict_set_check', e.target.checked)}
                        className="w-4 h-4 rounded text-teal-600 focus:ring-teal-500 border-slate-300"
                      />
                      <span>Strict Set Check (treat existing N/A concepts as non-sets)</span>
                    </label>
                  </div>
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
                  Cancel Operation
                </Button>
              )}

              <Button
                variant={inputs.cm13_apply && selectedToolId === 'cm13_legacy_import' ? 'warning' : 'primary'}
                icon={<Play className="w-4 h-4 mr-1.5" />}
                loading={isRunning}
                disabled={isViewer || isRunning}
                onClick={handleRun}
              >
                {isRunning
                  ? 'Operation in Progress...'
                  : selectedToolId === 'cm13_legacy_import'
                  ? inputs.cm13_apply
                    ? 'Execute Live Bulk Import'
                    : 'Run Safe Dry-Run Plan'
                  : `Execute ${currentTool.name}`}
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
