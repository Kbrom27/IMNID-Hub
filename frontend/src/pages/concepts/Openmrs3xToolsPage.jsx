import React, { useState, useEffect, useRef } from 'react';
import {
  Sparkles,
  Server,
  Download,
  FolderOpen,
  Layers,
  FileText,
  Upload,
  ArrowRight,
  Code,
  FileSpreadsheet,
  CheckCircle2,
  AlertTriangle,
  Play,
  RotateCcw,
  Search,
  RefreshCw,
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
  TextInput,
  Checkbox,
  JobPanel,
  ConfirmDialog,
  Alert,
  DirectoryPicker,
  FileDropzone,
  Tooltip,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';
import { TOOLS_3X } from './schemaConstants';

/**
 * OpenMRS 3.x Concept & Form Tools Page
 * CM-01 to CM-11 utilities for concept batch conversion, imports, schema generation, and metadata verification.
 * Tools are listed at the top as an interactive navigation grid, with their forms displayed at the bottom.
 */
const Openmrs3xToolsPage = () => {
  const { authHeader, isViewer } = useAuth();
  const { showToast } = useToast();

  const [selectedToolId, setSelectedToolId] = useState('cm01_bahmni');
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobState, setJobState] = useState(null);
  const [liveLogs, setLiveLogs] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [preflightResult, setPreflightResult] = useState(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [searchSetLoading, setSearchSetLoading] = useState(false);
  const [searchSetResults, setSearchSetResults] = useState(null);
  const [selectedSet, setSelectedSet] = useState(null);
  const [cm04Programs, setCm04Programs] = useState([]);
  const [cm04LoadingPrograms, setCm04LoadingPrograms] = useState(false);
  const [cm05ScanResult, setCm05ScanResult] = useState(null);
  const [cm05Scanning, setCm05Scanning] = useState(false);
  const [cm05ShowTree, setCm05ShowTree] = useState(false);
  const [cm06Programs, setCm06Programs] = useState([]);
  const [cm06LoadingPrograms, setCm06LoadingPrograms] = useState(false);
  const [cm06Stages, setCm06Stages] = useState([]);
  const [cm08Programs, setCm08Programs] = useState([]);
  const [cm08LoadingPrograms, setCm08LoadingPrograms] = useState(false);
  const [cm08Stages, setCm08Stages] = useState([]);
  const [uploadingField, setUploadingField] = useState(null);

  const eventSourceRef = useRef(null);

  // Input states covering all CM-01 to CM-11 original script parameters
  const [inputs, setInputs] = useState({
    cm01_concepts_csv: '',
    cm01_sets_csv: '',
    cm01_output_dir: '/data/exports/bahmni-concepts',
    cm02_concepts_file: '',
    cm02_sets_file: '',
    cm02_output_dir: '/data/exports/concept-reports',
    cm03_concept_set_name: '',
    cm03_concept_set_uuid: '',
    cm03_output_dir: '/data/exports/concept-sets',
    cm04_source_type: 'json',
    cm04_file_path: '',
    cm04_selected_programs: [],
    cm04_output_dir: '/data/exports/dhis2-concepts',
    cm05_folder_path: '',
    cm05_output_dir: '/data/exports/bulk-import-reports',
    cm06_program_name: '',
    cm06_metadata_file: '',
    cm06_concepts_file: '',
    cm06_encounter_type: '',
    cm06_use_dictionary: false,
    cm06_data_dictionary: '',
    cm06_output_dir: '/data/schemas',
    cm07_format: 'csv',
    cm07_output_dir: '/data/exports',
    cm07_output_filename: 'openmrs_all_concepts.csv',
    cm08_program_name: '',
    cm08_metadata_file: '',
    cm08_concepts_file: '',
    cm08_encounter_type: '',
    cm08_use_dictionary: false,
    cm08_data_dictionary: '',
    cm08_output_dir: '/data/schemas/enhanced',
    cm09_forms_dir: '/data/schemas/Maternal Inpatient Data',
    cm09_output_dir: '/data/exports/form-concepts',
    cm10_forms_dir: '/data/schemas/Maternal Inpatient Data',
  });

  const handleInputChange = (field, value) => {
    setInputs((prev) => ({ ...prev, [field]: value }));
  };

  // SSE Job Listener with resilient polling fallback
  useEffect(() => {
    if (!activeJobId) return;

    let pollInterval = null;
    const fetchStatus = async () => {
      try {
        const res = await fetch(`/api/jobs/${activeJobId}`, {
          headers: authHeader(),
        });
        if (res.ok) {
          const data = await res.json();
          if (data) {
            setJobState(data);
            if (data.errors && Array.isArray(data.errors) && data.errors.length > 0) {
              setLiveLogs((prev) => {
                const updated = [...prev];
                data.errors.forEach((err) => {
                  const line = `[ERROR] ${err}`;
                  if (!updated.includes(line)) updated.push(line);
                });
                return updated;
              });
            }
            if (['completed', 'failed', 'cancelled', 'canceled'].includes(data.status)) {
              setIsStreaming(false);
              if (pollInterval) clearInterval(pollInterval);
            }
          }
        }
      } catch (e) {
        console.error('Job poll error', e);
      }
    };

    fetchStatus();
    pollInterval = setInterval(fetchStatus, 2000);

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const token = localStorage.getItem('imnid_token') || localStorage.getItem('token');
    const es = new EventSource(`/api/jobs/${activeJobId}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`);
    eventSourceRef.current = es;
    setIsStreaming(true);

    const handlePayload = (parsed) => {
      if (!parsed) return;
      if (parsed.type === 'log') {
        const line = typeof parsed.data === 'string'
          ? parsed.data
          : parsed.data?.line || parsed.data?.text || parsed.message || (typeof parsed === 'string' ? parsed : JSON.stringify(parsed.data || parsed));
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
      } catch (err) {
        console.error('Progress event parse error:', err);
      }
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
          }
        }
      } catch (err) {
        console.error('Status event parse error:', err);
      }
    });

    es.onerror = () => {
      // Keep polling fallback active
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
        if (targetField === 'cm04_file_path') {
          handleFetchPrograms(data.filepath);
        }
        if (targetField === 'cm05_folder_path') {
          handleScanBulkFolder(data.filepath);
        }
        if (targetField === 'cm06_metadata_file') {
          await handleLoadCm06Metadata(data.filepath);
        }
        if (targetField === 'cm08_metadata_file') {
          await handleLoadCm08Metadata(data.filepath);
        }
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
    setPreflightResult(null);

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

  const handlePreflightCheck = async () => {
    if (!inputs.cm02_concepts_file) {
      showToast('Please select a concepts JSON file first.', 'warning');
      return;
    }
    setPreflightLoading(true);
    setPreflightResult({ loading: true });
    try {
      const res = await fetch('/api/concepts/check-classes', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({
          concepts_file: inputs.cm02_concepts_file,
          sets_file: inputs.cm02_sets_file || null,
        }),
      });
      const data = await res.json();
      setPreflightResult(data);
      if (data.status === 'ok') {
        showToast('Pre-flight validation passed!', 'success');
      } else if (data.status === 'error') {
        showToast('Pre-flight validation found issues.', 'warning');
      }
    } catch (err) {
      setPreflightResult({ error: err.message });
      showToast(err.message, 'error');
    } finally {
      setPreflightLoading(false);
    }
  };

  const handleSearchConceptSets = async (termOverride) => {
    const term = (termOverride !== undefined ? termOverride : (inputs.cm03_concept_set_name || inputs.cm03_concept_set_uuid || '')).trim();
    if (!term) {
      showToast('Please enter a concept set name to search.', 'warning');
      return;
    }
    setSearchSetLoading(true);
    setSearchSetResults(null);
    try {
      const res = await fetch('/api/concepts/search-sets', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({ term }),
      });
      if (res.ok) {
        const data = await res.json();
        const results = data.results || [];
        setSearchSetResults(results);
        if (results.length === 0) {
          showToast(`No concept sets found matching "${term}".`, 'info');
        } else {
          showToast(`Found ${results.length} concept set(s).`, 'success');
        }
      } else {
        const err = await res.json();
        showToast(err.detail || 'Failed to search concept sets', 'error');
      }
    } catch (err) {
      showToast('Search error: ' + err.message, 'error');
    } finally {
      setSearchSetLoading(false);
    }
  };

  const handleSelectConceptSet = (item) => {
    setSelectedSet(item);
    setInputs((prev) => ({
      ...prev,
      cm03_concept_set_name: item.display,
      cm03_concept_set_uuid: item.uuid,
    }));
  };

  const handleFetchPrograms = async (filePath) => {
    if (!filePath) return;
    setCm04LoadingPrograms(true);
    setCm04Programs([]);
    setInputs((prev) => ({ ...prev, cm04_selected_programs: [] }));
    try {
      const res = await fetch('/api/concepts/extract-programs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({ file_path: filePath }),
      });
      const data = await res.json();
      if (res.ok) {
        const progs = data.programs || [];
        setCm04Programs(progs);
        const allIds = progs.map((p) => p.id || p.name);
        setInputs((prev) => ({ ...prev, cm04_selected_programs: allIds }));
        if (progs.length > 0) {
          showToast(`Fetched ${progs.length} program(s) from file.`, 'success');
        } else {
          showToast('No programs found in the uploaded file.', 'warning');
        }
      } else {
        showToast(data.detail || 'Failed to inspect programs in file', 'error');
      }
    } catch (err) {
      showToast('Error reading programs: ' + err.message, 'error');
    } finally {
      setCm04LoadingPrograms(false);
    }
  };

  const toggleProgramSelection = (progKey) => {
    setInputs((prev) => {
      const current = prev.cm04_selected_programs || [];
      const updated = current.includes(progKey)
        ? current.filter((id) => id !== progKey)
        : [...current, progKey];
      return { ...prev, cm04_selected_programs: updated };
    });
  };

  const handleSelectAllPrograms = () => {
    const allIds = cm04Programs.map((p) => p.id || p.name);
    setInputs((prev) => ({
      ...prev,
      cm04_selected_programs: prev.cm04_selected_programs?.length === allIds.length ? [] : allIds,
    }));
  };

  const handleScanBulkFolder = async (folderPath, isManual = false) => {
    const path = folderPath || inputs.cm05_folder_path;
    if (!path?.trim()) return;
    setCm05Scanning(true);
    try {
      const res = await fetch('/api/concepts/scan-bulk-folder', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({ folder_path: path.trim() }),
      });
      const data = await res.json();
      if (res.ok) {
        setCm05ScanResult(data);
        if (data.resolved_path && data.resolved_path !== inputs.cm05_folder_path) {
          handleInputChange('cm05_folder_path', data.resolved_path);
        }
      } else {
        setCm05ScanResult(null);
        if (isManual) {
          showToast(data.detail || 'Folder scan failed', 'warning');
        }
      }
    } catch (err) {
      setCm05ScanResult(null);
      if (isManual) {
        showToast('Scan error: ' + err.message, 'error');
      }
    } finally {
      setCm05Scanning(false);
    }
  };

  useEffect(() => {
    if (selectedToolId === 'cm05_bulk_import' && inputs.cm05_folder_path?.trim()) {
      handleScanBulkFolder(inputs.cm05_folder_path, false);
    }
  }, [selectedToolId]);

  const handleLoadCm06Metadata = async (customPath) => {
    const metaPath = (customPath !== undefined ? customPath : inputs.cm06_metadata_file || '').trim();
    if (!metaPath) {
      showToast('Please select or upload a DHIS2 metadata JSON file first.', 'warning');
      return;
    }
    setCm06LoadingPrograms(true);
    try {
      const res = await fetch('/api/concepts/extract-programs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({ file_path: metaPath }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to inspect DHIS2 metadata JSON.');
      }
      const data = await res.json();
      const progs = data.programs || [];
      setCm06Programs(progs);
      if (progs.length > 0) {
        const currentSelected = progs.find((p) => p.name === inputs.cm06_program_name);
        const selected = currentSelected || progs[0];
        setInputs((prev) => ({
          ...prev,
          cm06_metadata_file: metaPath,
          cm06_program_name: selected.name,
        }));
        setCm06Stages(selected.stages || []);
        showToast(`Loaded ${progs.length} program(s) from metadata.`, 'success');
      } else {
        setInputs((prev) => ({
          ...prev,
          cm06_metadata_file: metaPath,
        }));
        setCm06Stages([]);
        showToast('No programs found in metadata file.', 'warning');
      }
    } catch (e) {
      showToast(e.message || 'Error loading metadata', 'error');
      setCm06Programs([]);
      setCm06Stages([]);
    } finally {
      setCm06LoadingPrograms(false);
    }
  };

  const handleSelectCm06Program = (progName) => {
    handleInputChange('cm06_program_name', progName);
    const prog = cm06Programs.find((p) => p.name === progName);
    if (prog) {
      setCm06Stages(prog.stages || []);
    } else {
      setCm06Stages([]);
    }
  };

  const handleLoadCm08Metadata = async (customPath) => {
    const metaPath = (customPath !== undefined ? customPath : inputs.cm08_metadata_file || '').trim();
    if (!metaPath) {
      showToast('Please select or upload a DHIS2 metadata JSON file first.', 'warning');
      return;
    }
    setCm08LoadingPrograms(true);
    try {
      const res = await fetch('/api/concepts/extract-programs', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({ file_path: metaPath }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to inspect DHIS2 metadata JSON.');
      }
      const data = await res.json();
      const progs = data.programs || [];
      setCm08Programs(progs);
      if (progs.length > 0) {
        const currentSelected = progs.find((p) => p.name === inputs.cm08_program_name);
        const selected = currentSelected || progs[0];
        setInputs((prev) => ({
          ...prev,
          cm08_metadata_file: metaPath,
          cm08_program_name: selected.name,
        }));
        setCm08Stages(selected.stages || []);
        showToast(`Loaded ${progs.length} program(s) from metadata.`, 'success');
      } else {
        setInputs((prev) => ({
          ...prev,
          cm08_metadata_file: metaPath,
        }));
        setCm08Stages([]);
        showToast('No programs found in metadata file.', 'warning');
      }
    } catch (e) {
      showToast(e.message || 'Error loading metadata', 'error');
      setCm08Programs([]);
      setCm08Stages([]);
    } finally {
      setCm08LoadingPrograms(false);
    }
  };

  const handleSelectCm08Program = (progName) => {
    handleInputChange('cm08_program_name', progName);
    const prog = cm08Programs.find((p) => p.name === progName);
    if (prog) {
      setCm08Stages(prog.stages || []);
    } else {
      setCm08Stages([]);
    }
  };

  useEffect(() => {
    if (selectedToolId === 'cm06_gen_schemas' && inputs.cm06_metadata_file && cm06Programs.length === 0) {
      handleLoadCm06Metadata(inputs.cm06_metadata_file);
    }
    if (selectedToolId === 'cm08_enhanced_gen' && inputs.cm08_metadata_file && cm08Programs.length === 0) {
      handleLoadCm08Metadata(inputs.cm08_metadata_file);
    }
  }, [selectedToolId]);

  const currentTool = TOOLS_3X.find((t) => t.id === selectedToolId) || TOOLS_3X[0];

  const handleRunTool = (isDryRun = false) => {
    const isWrite = ['cm02_import', 'cm05_bulk_import', 'cm10_import_schemas'].includes(selectedToolId);
    if (!isDryRun && isWrite) {
      setShowConfirm(true);
    } else {
      executeActiveTool(isDryRun);
    }
  };

  const executeActiveTool = (isDryRun = false) => {
    setShowConfirm(false);
    if (selectedToolId === 'cm01_bahmni') {
      if (!inputs.cm01_concepts_csv) {
        showToast('Please select or upload a Bahmni Concepts CSV file first.', 'warning');
        return;
      }
      submitJob('/api/concepts/convert-bahmni', {
        concepts_csv: inputs.cm01_concepts_csv,
        sets_csv: inputs.cm01_sets_csv || null,
        output_dir: inputs.cm01_output_dir || null,
      });
    } else if (selectedToolId === 'cm02_import') {
      if (!inputs.cm02_concepts_file) {
        showToast('Please select or upload an OpenMRS Concepts JSON file first.', 'warning');
        return;
      }
      submitJob('/api/concepts/import', {
        concepts_file: inputs.cm02_concepts_file,
        sets_file: inputs.cm02_sets_file || null,
        dry_run: isDryRun,
        output_dir: inputs.cm02_output_dir || null,
      });
    } else if (selectedToolId === 'cm03_export_set') {
      const target = (inputs.cm03_concept_set_name || inputs.cm03_concept_set_uuid || '').trim();
      if (!target) {
        showToast('Please enter or search for a Concept Set Name or UUID to export.', 'warning');
        return;
      }
      submitJob('/api/concepts/export-set', {
        concept_set_name: inputs.cm03_concept_set_name?.trim() || null,
        concept_set_uuid: inputs.cm03_concept_set_uuid?.trim() || null,
        root_uuid: target,
        output_dir: inputs.cm03_output_dir || null,
        dry_run: isDryRun,
      });
    } else if (selectedToolId === 'cm04_dhis2_conv') {
      if (!inputs.cm04_file_path?.trim()) {
        showToast(
          inputs.cm04_source_type === 'dictionary'
            ? 'Please select or upload a Data Dictionary CSV/Excel file first.'
            : 'Please select or upload a DHIS2 Metadata JSON file first.',
          'warning'
        );
        return;
      }
      if (!inputs.cm04_selected_programs || inputs.cm04_selected_programs.length === 0) {
        showToast('Please select at least one program to convert.', 'warning');
        return;
      }
      submitJob('/api/concepts/convert-dhis2', {
        source_type: inputs.cm04_source_type || 'json',
        file_path: inputs.cm04_file_path.trim(),
        selected_program_ids: inputs.cm04_selected_programs,
        output_dir: inputs.cm04_output_dir || null,
        dry_run: isDryRun,
      });
    } else if (selectedToolId === 'cm05_bulk_import') {
      if (!inputs.cm05_folder_path?.trim()) {
        showToast('Please select a program directory containing concept JSON files.', 'warning');
        return;
      }
      submitJob('/api/concepts/bulk-import', {
        folder_path: inputs.cm05_folder_path.trim(),
        dry_run: isDryRun,
        output_dir: inputs.cm05_output_dir || null,
      });
    } else if (selectedToolId === 'cm06_gen_schemas') {
      if (!inputs.cm06_metadata_file?.trim()) {
        showToast('Please select or upload a DHIS2 Metadata JSON file.', 'warning');
        return;
      }
      if (!inputs.cm06_concepts_file?.trim()) {
        showToast('Please select or upload an OpenMRS Concepts CSV file.', 'warning');
        return;
      }
      if (!inputs.cm06_output_dir?.trim()) {
        showToast('Please specify an output directory.', 'warning');
        return;
      }
      if (!inputs.cm06_program_name?.trim()) {
        showToast('Please select or enter a program name.', 'warning');
        return;
      }
      if (cm06Stages && cm06Stages.length === 0 && cm06Programs.length > 0) {
        showToast('Selected program has no stages.', 'warning');
        return;
      }
      submitJob('/api/concepts/generate-schemas', {
        program_name: inputs.cm06_program_name.trim(),
        metadata_file: inputs.cm06_metadata_file.trim(),
        concepts_file: inputs.cm06_concepts_file.trim(),
        encounter_type: (inputs.cm06_encounter_type || '').trim(),
        data_dictionary_path: inputs.cm06_use_dictionary && inputs.cm06_data_dictionary?.trim() ? inputs.cm06_data_dictionary.trim() : null,
        output_dir: inputs.cm06_output_dir?.trim() || null,
        dry_run: isDryRun,
      });
    } else if (selectedToolId === 'cm07_export_all') {
      const chosenFmt = (inputs.cm07_format || 'csv').trim().toLowerCase();
      const defaultFilename = `openmrs_all_concepts.${chosenFmt}`;
      const chosenFilename = (inputs.cm07_output_filename || defaultFilename).trim();
      submitJob('/api/concepts/export-all', {
        format: chosenFmt,
        export_format: chosenFmt,
        output_dir: inputs.cm07_output_dir?.trim() || null,
        output_filename: chosenFilename,
        dry_run: isDryRun,
      });
    } else if (selectedToolId === 'cm08_enhanced_gen') {
      if (!inputs.cm08_metadata_file?.trim()) {
        showToast('Please select or upload a DHIS2 Metadata JSON file.', 'warning');
        return;
      }
      if (!inputs.cm08_concepts_file?.trim()) {
        showToast('Please select or upload an OpenMRS Concepts CSV file.', 'warning');
        return;
      }
      if (!inputs.cm08_program_name?.trim()) {
        showToast('Please select or specify a program name.', 'warning');
        return;
      }
      submitJob('/api/concepts/enhanced-generator', {
        program_name: inputs.cm08_program_name.trim(),
        metadata_file: inputs.cm08_metadata_file.trim(),
        concepts_file: inputs.cm08_concepts_file.trim(),
        encounter_type: (inputs.cm08_encounter_type || '').trim(),
        data_dictionary_path: inputs.cm08_use_dictionary && inputs.cm08_data_dictionary?.trim() ? inputs.cm08_data_dictionary.trim() : null,
        output_dir: inputs.cm08_output_dir?.trim() || null,
        dry_run: isDryRun,
      });

    } else if (selectedToolId === 'cm09_export_form_concepts') {
      if (!inputs.cm09_forms_dir?.trim()) {
        showToast('Please select the directory containing form schemas.', 'warning');
        return;
      }
      submitJob('/api/concepts/export-form-concepts', {
        forms_dir: inputs.cm09_forms_dir.trim(),
        output_dir: inputs.cm09_output_dir || null,
        dry_run: isDryRun,
      });
    } else if (selectedToolId === 'cm10_import_schemas') {
      if (!inputs.cm10_forms_dir?.trim()) {
        showToast('Please select the forms directory or file.', 'warning');
        return;
      }
      submitJob('/api/concepts/import-schemas', {
        forms_dir: inputs.cm10_forms_dir.trim(),
        dry_run: isDryRun,
      });
    }
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="OpenMRS 3.x Tools"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Concepts & Forms', to: '/concepts' },
          { label: 'OpenMRS 3.x Tools' },
        ]}
      />

      {/* Top Tool Selector */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-4 shadow-xs">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
          {TOOLS_3X.map((tool) => {
            const isSelected = selectedToolId === tool.id;
            return (
              <Tooltip key={tool.id} content={`${tool.code} · ${tool.name}`}>
                <button
                  type="button"
                  onClick={() => setSelectedToolId(tool.id)}
                  title={`${tool.code} · ${tool.name}`}
                  className={`p-2.5 sm:px-3 sm:py-2.5 rounded-xl text-left transition-all flex flex-col justify-center border w-full min-h-[68px] relative cursor-pointer ${
                    isSelected
                      ? 'bg-teal-50/80 dark:bg-teal-950/50 border-teal-500 dark:border-teal-400 text-teal-950 dark:text-teal-100 shadow-2xs ring-1 ring-teal-500/20'
                      : 'border-slate-200/80 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 bg-white dark:bg-slate-900/60 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-850'
                  }`}
                >
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <span
                      className={`font-sans text-xs font-bold tracking-wider px-2 py-0.5 rounded ${
                        isSelected
                          ? 'bg-teal-600 text-white dark:bg-teal-500'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300'
                      }`}
                    >
                      {tool.code}
                    </span>
                  </div>
                  <div className="font-semibold text-xs sm:text-[13px] leading-snug line-clamp-2">
                    {tool.name}
                  </div>
                </button>
              </Tooltip>
            );
          })}
        </div>
      </div>

      {/* Selected Tool Form & Run Card */}
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 w-full">
              <div className="flex items-center gap-2">
                <span className="font-sans text-xs font-bold text-teal-600 dark:text-teal-400 px-2 py-0.5 rounded bg-teal-50 dark:bg-teal-950/40 border border-teal-200/60 dark:border-teal-800/60">
                  {currentTool.code}
                </span>
                <CardTitle>{currentTool.name}</CardTitle>
              </div>

              {/* Action Buttons visible right at top */}
              <div className="flex items-center gap-2 flex-wrap">
                {selectedToolId !== 'cm01_bahmni' && (
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RotateCcw className="w-3.5 h-3.5 text-amber-500" />}
                    loading={isStreaming}
                    disabled={isViewer}
                    onClick={() => handleRunTool(true)}
                  >
                    Dry-Run
                  </Button>
                )}
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Play className="w-3.5 h-3.5" />}
                  loading={isStreaming}
                  disabled={isViewer}
                  onClick={() => handleRunTool(false)}
                >
                  Execute
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            {/* CM-01: Bahmni Concept Converter */}
            {selectedToolId === 'cm01_bahmni' && (
              <div className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <label htmlFor="cm01_concepts_csv_input" className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                      Bahmni Concepts CSV File <span className="text-rose-500">*</span>
                    </label>
                    <FileDropzone
                      id="cm01_concepts_csv_input"
                      accept=".csv"
                      filePath={inputs.cm01_concepts_csv}
                      uploading={uploadingField === 'cm01_concepts_csv'}
                      onFileSelect={(selectedFile) => handleFileUpload(selectedFile, 'cm01_concepts_csv')}
                      onRemove={() => handleInputChange('cm01_concepts_csv', '')}
                      helperText="Drag & drop Bahmni Concepts CSV file"
                    />
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="cm01_sets_csv_input" className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                      Bahmni Concept Sets CSV File (Optional)
                    </label>
                    <FileDropzone
                      id="cm01_sets_csv_input"
                      accept=".csv"
                      filePath={inputs.cm01_sets_csv}
                      uploading={uploadingField === 'cm01_sets_csv'}
                      onFileSelect={(selectedFile) => handleFileUpload(selectedFile, 'cm01_sets_csv')}
                      onRemove={() => handleInputChange('cm01_sets_csv', '')}
                      helperText="Optional Bahmni Concept Sets CSV file"
                    />
                  </div>
                </div>

                <DirectoryPicker
                  label="Output Directory (Export Destination)"
                  value={inputs.cm01_output_dir}
                  onChange={(val) => handleInputChange('cm01_output_dir', val)}
                  helperText="Select or browse the target directory where the converted JSON files and zip bundle will be saved"
                />
              </div>
            )}

            {/* CM-02: Import Concepts & Sets */}
            {selectedToolId === 'cm02_import' && (
              <div className="space-y-4">
                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400">
                  <Server className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Using saved <strong>OpenMRS 3.x</strong> connection credentials from Settings & Connections.</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <label htmlFor="cm02_concepts_file_input" className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                      Concepts JSON File <span className="text-rose-500">*</span>
                    </label>
                    <FileDropzone
                      id="cm02_concepts_file_input"
                      accept=".json"
                      filePath={inputs.cm02_concepts_file}
                      uploading={uploadingField === 'cm02_concepts_file'}
                      onFileSelect={(selectedFile) => handleFileUpload(selectedFile, 'cm02_concepts_file')}
                      onRemove={() => handleInputChange('cm02_concepts_file', '')}
                      helperText="Drag & drop OpenMRS 3 Concepts JSON file"
                    />
                  </div>
                  <div className="space-y-1">
                    <label htmlFor="cm02_sets_file_input" className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                      Concept Sets JSON File (Optional)
                    </label>
                    <FileDropzone
                      id="cm02_sets_file_input"
                      accept=".json"
                      filePath={inputs.cm02_sets_file}
                      uploading={uploadingField === 'cm02_sets_file'}
                      onFileSelect={(selectedFile) => handleFileUpload(selectedFile, 'cm02_sets_file')}
                      onRemove={() => handleInputChange('cm02_sets_file', '')}
                      helperText="Optional Concept Sets JSON file"
                    />
                  </div>
                </div>
                <div className="flex items-center justify-center pt-1">
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={preflightLoading}
                    onClick={handlePreflightCheck}
                  >
                    Pre-flight Check Classes
                  </Button>
                </div>
                {preflightResult && (
                  <div className="p-3 bg-slate-50 dark:bg-slate-850 rounded-lg border border-slate-200 dark:border-slate-800 text-xs">
                    {preflightResult.error ? (
                      <p className="text-rose-500 font-semibold">{preflightResult.error}</p>
                    ) : (
                      <div className="space-y-1">
                        <p className="font-semibold text-teal-700 dark:text-teal-400">Pre-flight Validation Result:</p>
                        <p>Classes Checked: {preflightResult.classes_checked || 'OK'}</p>
                        {preflightResult.missing_classes?.length > 0 && (
                          <p className="text-amber-600">Missing Classes: {preflightResult.missing_classes.join(', ')}</p>
                        )}
                      </div>
                    )}
                  </div>
                )}
                <DirectoryPicker
                  label="Import Report Output Directory"
                  value={inputs.cm02_output_dir}
                  onChange={(val) => handleInputChange('cm02_output_dir', val)}
                  helperText="Select or browse the target directory where the import CSV report will be saved"
                />
              </div>
            )}

            {/* CM-03: Export Concept Set */}
            {selectedToolId === 'cm03_export_set' && (
              <div className="space-y-4">
                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400">
                  <Server className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Using saved <strong>OpenMRS 3.x</strong> connection credentials from Settings & Connections.</span>
                </div>

                <div className="space-y-2">
                  <label htmlFor="cm03_concept_set_input" className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                    Concept Set Name or UUID <span className="text-rose-500">*</span>
                  </label>
                  <div className="flex gap-2">
                    <div className="flex-1">
                      <TextInput
                        id="cm03_concept_set_input"
                        value={inputs.cm03_concept_set_name || inputs.cm03_concept_set_uuid || ''}
                        onChange={(e) => {
                          const val = e.target.value;
                          handleInputChange('cm03_concept_set_name', val);
                          handleInputChange('cm03_concept_set_uuid', val);
                          setSelectedSet(null);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault();
                            handleSearchConceptSets();
                          }
                        }}
                        placeholder="Search by name (e.g. Heparins, Antenatal Care) or enter UUID..."
                      />
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => handleSearchConceptSets()}
                      loading={searchSetLoading}
                      className="shrink-0 flex items-center gap-1.5"
                    >
                      <Search className="w-4 h-4" />
                      <span>Search OpenMRS</span>
                    </Button>
                  </div>
                  <p className="text-xs text-slate-500">
                    Type a concept set name and click <strong>Search OpenMRS</strong> to look up matching sets on your live server, or enter the name/UUID directly.
                  </p>
                </div>

                {/* Search Results Display */}
                {searchSetResults && (
                  <div className="p-3 bg-slate-50 dark:bg-slate-850 rounded-lg border border-slate-200 dark:border-slate-800 space-y-2 text-xs">
                    <div className="flex items-center justify-between text-slate-600 dark:text-slate-400">
                      <span className="font-semibold text-slate-700 dark:text-slate-300">
                        Matching Concept Sets ({searchSetResults.length}):
                      </span>
                      {searchSetResults.length > 0 && (
                        <span>Click a concept set to select it for export</span>
                      )}
                    </div>

                    {searchSetResults.length === 0 ? (
                      <p className="text-slate-500 italic py-2">
                        No concept sets found matching your search term. Try a different keyword.
                      </p>
                    ) : (
                      <div className="grid grid-cols-1 gap-2 max-h-56 overflow-y-auto pr-1">
                        {searchSetResults.map((item) => {
                          const isSelected = (inputs.cm03_concept_set_uuid === item.uuid) || (selectedSet?.uuid === item.uuid);
                          return (
                            <button
                              key={item.uuid}
                              type="button"
                              onClick={() => handleSelectConceptSet(item)}
                              className={`text-left p-2.5 rounded-md border transition-all flex items-center justify-between gap-3 ${
                                isSelected
                                  ? 'bg-teal-50 dark:bg-teal-950/40 border-teal-500 text-teal-950 dark:text-teal-200 ring-1 ring-teal-500'
                                  : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-teal-400'
                              }`}
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-2">
                                  <span className="font-semibold text-sm text-slate-900 dark:text-white truncate">
                                    {item.display}
                                  </span>
                                  {item.concept_class && (
                                    <span className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                                      {item.concept_class}
                                    </span>
                                  )}
                                  {item.members_count !== undefined && (
                                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-teal-100 dark:bg-teal-900/50 text-teal-700 dark:text-teal-300 font-medium">
                                      {item.members_count} members
                                    </span>
                                  )}
                                </div>
                                <p className="text-[11px] font-mono text-slate-500 dark:text-slate-400 truncate mt-0.5">
                                  UUID: {item.uuid}
                                </p>
                              </div>
                              {isSelected ? (
                                <span className="flex items-center gap-1 text-xs font-semibold text-teal-600 dark:text-teal-400 shrink-0">
                                  <CheckCircle2 className="w-4 h-4 text-teal-500" />
                                  Selected
                                </span>
                              ) : (
                                <span className="text-xs text-slate-400 hover:text-teal-600 dark:hover:text-teal-400 shrink-0 font-medium">
                                  Select &rarr;
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* Selected Set Details Badge */}
                {selectedSet && (
                  <div className="p-2.5 rounded-lg bg-teal-500/10 border border-teal-500/20 text-xs text-teal-700 dark:text-teal-300 flex items-center justify-between">
                    <div>
                      <span className="font-semibold">Selected Concept Set: </span>
                      <span>{selectedSet.display}</span>
                      <span className="font-mono text-[11px] text-teal-600 dark:text-teal-400 ml-2">
                        ({selectedSet.uuid})
                      </span>
                    </div>
                    {selectedSet.members_count !== undefined && (
                      <span className="font-medium text-xs">
                        {selectedSet.members_count} direct members
                      </span>
                    )}
                  </div>
                )}

                <DirectoryPicker
                  label="Export Destination Directory"
                  value={inputs.cm03_output_dir}
                  onChange={(val) => handleInputChange('cm03_output_dir', val)}
                  helperText="Select or browse the target directory where the exported JSON files and zip bundle will be saved"
                />
              </div>
            )}

            {/* CM-04: DHIS2 Metadata / Data Dictionary Converter */}
            {selectedToolId === 'cm04_dhis2_conv' && (
              <div className="space-y-4">
                {/* 1. Source Option Choice: Metadata JSON vs Data Dictionary CSV */}
                <div>
                  <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2 block">
                    Choose Conversion Source <span className="text-rose-500">*</span>
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        handleInputChange('cm04_source_type', 'json');
                        handleInputChange('cm04_file_path', '');
                        setCm04Programs([]);
                        setInputs((prev) => ({ ...prev, cm04_selected_programs: [] }));
                      }}
                      className={`p-3 rounded-lg border text-left transition-all flex items-start gap-3 cursor-pointer ${
                        (inputs.cm04_source_type || 'json') === 'json'
                          ? 'bg-teal-50/70 dark:bg-teal-950/40 border-teal-500 ring-1 ring-teal-500 text-teal-950 dark:text-teal-200'
                          : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
                      }`}
                    >
                      <div className={`p-2 rounded-md shrink-0 ${
                        (inputs.cm04_source_type || 'json') === 'json' ? 'bg-teal-500 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'
                      }`}>
                        <FileText className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="font-semibold text-xs text-slate-900 dark:text-slate-100">
                          DHIS2 Metadata JSON File
                        </div>
                        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                          Full DHIS2 tracker export (.json) containing programs, stages, sections, and data elements
                        </p>
                      </div>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        handleInputChange('cm04_source_type', 'dictionary');
                        handleInputChange('cm04_file_path', '');
                        setCm04Programs([]);
                        setInputs((prev) => ({ ...prev, cm04_selected_programs: [] }));
                      }}
                      className={`p-3 rounded-lg border text-left transition-all flex items-start gap-3 cursor-pointer ${
                        inputs.cm04_source_type === 'dictionary'
                          ? 'bg-teal-50/70 dark:bg-teal-950/40 border-teal-500 ring-1 ring-teal-500 text-teal-950 dark:text-teal-200'
                          : 'bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
                      }`}
                    >
                      <div className={`p-2 rounded-md shrink-0 ${
                        inputs.cm04_source_type === 'dictionary' ? 'bg-teal-500 text-white' : 'bg-slate-100 dark:bg-slate-800 text-slate-500'
                      }`}>
                        <FileSpreadsheet className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="font-semibold text-xs text-slate-900 dark:text-slate-100">
                          Data Dictionary CSV / Excel File
                        </div>
                        <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                          Data dictionary export (.csv, .xlsx) with Stage Name, Section Name, and Data Elements
                        </p>
                      </div>
                    </button>
                  </div>
                </div>

                {/* 2. Single File Upload / Browse Input based on chosen option */}
                <div className="p-3 bg-slate-50 dark:bg-slate-850 rounded-lg border border-slate-200 dark:border-slate-800 space-y-2">
                  <label htmlFor="cm04_file_upload" className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                    {inputs.cm04_source_type === 'dictionary'
                      ? 'Upload Data Dictionary File (.csv, .xlsx) *'
                      : 'Upload DHIS2 Metadata JSON File (.json) *'}
                  </label>
                  <FileDropzone
                    id="cm04_file_upload"
                    accept={inputs.cm04_source_type === 'dictionary' ? '.csv,.xlsx,.xls,.tsv' : '.json'}
                    filePath={inputs.cm04_file_path}
                    uploading={uploadingField === 'cm04_file_path'}
                    onFileSelect={(selectedFile) => handleFileUpload(selectedFile, 'cm04_file_path')}
                    onRemove={() => {
                      handleInputChange('cm04_file_path', '');
                      setCm04Programs([]);
                    }}
                    helperText={inputs.cm04_source_type === 'dictionary' ? 'Data dictionary spreadsheet (.csv, .xlsx)' : 'DHIS2 metadata export (.json)'}
                  />
                  {inputs.cm04_file_path && !cm04LoadingPrograms && (
                    <div className="pt-1">
                      <Button
                        type="button"
                        size="xs"
                        variant="secondary"
                        onClick={() => handleFetchPrograms(inputs.cm04_file_path)}
                        loading={cm04LoadingPrograms}
                        className="shrink-0"
                      >
                        Re-scan Programs
                      </Button>
                    </div>
                  )}
                </div>

                {/* Loading indicator while inspecting */}
                {cm04LoadingPrograms && (
                  <div className="p-4 rounded-lg bg-teal-50 dark:bg-teal-950/30 border border-teal-200 dark:border-teal-800/40 text-center space-y-2">
                    <div className="animate-spin inline-block w-5 h-5 border-2 border-teal-500 border-t-transparent rounded-full" />
                    <p className="text-xs text-teal-700 dark:text-teal-300 font-medium">
                      Inspecting file and fetching available programs...
                    </p>
                  </div>
                )}

                {/* 3. Program Selection Checklist */}
                {!cm04LoadingPrograms && cm04Programs && cm04Programs.length > 0 && (
                  <div className="p-3.5 bg-white dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800 space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
                      <div>
                        <span className="font-semibold text-xs text-slate-900 dark:text-white">
                          Available Programs in File ({cm04Programs.length}):
                        </span>
                        <span className="ml-2 text-[11px] text-teal-600 dark:text-teal-400 font-medium">
                          ({inputs.cm04_selected_programs?.length || 0} selected)
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={handleSelectAllPrograms}
                          className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:underline cursor-pointer"
                        >
                          {inputs.cm04_selected_programs?.length === cm04Programs.length
                            ? 'Deselect All'
                            : 'Select All'}
                        </button>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-60 overflow-y-auto pr-1">
                      {cm04Programs.map((prog) => {
                        const progKey = prog.id || prog.name;
                        const isChecked = (inputs.cm04_selected_programs || []).includes(progKey);
                        return (
                          <label
                            key={progKey}
                            className={`p-2.5 rounded-md border text-xs cursor-pointer transition-all flex items-start gap-2.5 ${
                              isChecked
                                ? 'bg-teal-50/60 dark:bg-teal-950/30 border-teal-400 dark:border-teal-600 text-slate-900 dark:text-slate-100 ring-1 ring-teal-400/50'
                                : 'bg-slate-50 dark:bg-slate-850 border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-400 hover:border-slate-300'
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => toggleProgramSelection(progKey)}
                              className="mt-0.5 rounded border-slate-300 dark:border-slate-700 text-teal-600 focus:ring-teal-500 cursor-pointer"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="font-semibold text-slate-900 dark:text-slate-100 truncate">
                                {prog.name}
                              </div>
                              <div className="flex items-center gap-2 mt-0.5 text-[10px] text-slate-500">
                                {prog.id && prog.id !== prog.name && (
                                  <span className="font-mono bg-slate-200 dark:bg-slate-800 px-1 rounded">
                                    ID: {prog.id}
                                  </span>
                                )}
                                {prog.stages_count !== undefined && (
                                  <span>{prog.stages_count} stage(s)</span>
                                )}
                                {prog.elements_count !== undefined && (
                                  <span>{prog.elements_count} elements</span>
                                )}
                              </div>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* 4. Output Destination */}
                <DirectoryPicker
                  label="Output Directory (Export Destination)"
                  value={inputs.cm04_output_dir}
                  onChange={(val) => handleInputChange('cm04_output_dir', val)}
                  helperText="Select or browse the target directory where the converted program concept folders and zip archive will be saved"
                />
              </div>
            )}

            {/* CM-05: Bulk Folder Importer */}
            {selectedToolId === 'cm05_bulk_import' && (
              <div className="space-y-4">
                {/* 1. Folder Path Selector & Scan */}
                <div className="grid grid-cols-1 md:grid-cols-4 gap-2 items-end">
                  <div className="md:col-span-3">
                    <DirectoryPicker
                      label="Program Directory Path (Server or Local Folder Tree)"
                      value={inputs.cm05_folder_path}
                      onChange={(val) => {
                        handleInputChange('cm05_folder_path', val);
                        if (val && !val.startsWith('[Local')) {
                          handleScanBulkFolder(val, false);
                        }
                      }}
                      allowFileUpload={true}
                      presetDirs={[
                        '/data/exports/dhis2-concepts',
                        '/data/exports/dhis2-concepts/Maternal Inpatient Data',
                        '/data/exports/dhis2-concepts/Neonatal Care Form',
                        '/data/exports/Tests',
                        '/data/exports',
                      ]}
                      helperText="Select or enter any folder (e.g. a parent folder, a program folder, or a stage folder). The importer will recursively navigate all folder levels inside it and import concepts and sets in order."
                    />
                  </div>
                  <div className="pb-1">
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full h-10 flex items-center justify-center gap-1.5"
                      disabled={cm05Scanning || !inputs.cm05_folder_path}
                      onClick={() => handleScanBulkFolder(inputs.cm05_folder_path, true)}
                    >
                      <RotateCcw className={`w-3.5 h-3.5 ${cm05Scanning ? 'animate-spin' : ''}`} />
                      {cm05Scanning ? 'Scanning...' : 'Scan Folder'}
                    </Button>
                  </div>
                </div>

                {/* 3. Or Upload ZIP archive of concepts */}
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 block">
                    Or Upload Concept Folder Archive (.zip)
                  </label>
                  <FileDropzone
                    id="cm05_zip_upload"
                    accept=".zip"
                    filePath={inputs.cm05_folder_path?.endsWith('.zip') ? inputs.cm05_folder_path : ''}
                    uploading={uploadingField === 'cm05_folder_path'}
                    onFileSelect={(selectedFile) => handleFileUpload(selectedFile, 'cm05_folder_path')}
                    onRemove={() => handleInputChange('cm05_folder_path', '')}
                    helperText="Upload a concept zip exported from CM-04 to automatically extract and import"
                  />
                </div>

                {/* 4. Scan Result Summary Card */}
                {cm05ScanResult && (
                  <div className="p-3.5 rounded-lg border border-primary-500/30 bg-primary-50/20 dark:bg-primary-950/20 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                        <span className="text-xs font-semibold text-slate-800 dark:text-slate-100">
                          Folder Scan Ready: {cm05ScanResult.folders_count} folder(s) discovered
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono font-semibold">
                          {cm05ScanResult.total_concepts} Concepts
                        </span>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400 font-mono font-semibold">
                          {cm05ScanResult.total_sets} Concept Sets
                        </span>
                        <button
                          type="button"
                          onClick={() => setCm05ShowTree(!cm05ShowTree)}
                          className="text-xs text-primary-600 hover:underline ml-1"
                        >
                          {cm05ShowTree ? 'Hide Order' : 'View Import Order'}
                        </button>
                      </div>
                    </div>
                    <p className="text-[11px] text-slate-500 dark:text-slate-400 font-mono truncate">
                      Resolved Path: {cm05ScanResult.resolved_path}
                    </p>

                    {cm05ShowTree && cm05ScanResult.preview && (
                      <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-700/60 max-h-48 overflow-y-auto space-y-1 font-mono text-[11px]">
                        <p className="text-xs font-semibold font-sans text-slate-700 dark:text-slate-300 mb-1">
                          Bottom-Up Import Order (Children Before Parents):
                        </p>
                        {cm05ScanResult.preview.map((step, idx) => (
                          <div key={idx} className="flex items-center justify-between py-0.5 px-2 rounded hover:bg-slate-100 dark:hover:bg-slate-800">
                            <span className="text-slate-700 dark:text-slate-300 truncate">
                              [{idx + 1}] {step.rel_path}
                            </span>
                            <span className="text-slate-400 text-[10px] shrink-0 ml-2">
                              {step.concepts_count} concepts • {step.sets_count} sets
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400">
                  <Server className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Using saved <strong>OpenMRS 3.x</strong> connection credentials from Settings & Connections.</span>
                </div>

                <DirectoryPicker
                  label="Import Report Output Directory"
                  value={inputs.cm05_output_dir}
                  onChange={(val) => handleInputChange('cm05_output_dir', val)}
                  helperText="Select or browse the target directory where the bulk import CSV report will be saved"
                />
              </div>
            )}

            {/* CM-06: Generate Form Schemas */}
            {selectedToolId === 'cm06_gen_schemas' && (
              <div className="space-y-4">
                {/* 1. DHIS2 Metadata JSON (required) */}
                <div className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900/40 space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                      <span>DHIS2 Metadata JSON (required)</span>
                      <span className="text-rose-500">*</span>
                    </label>
                    <button
                      type="button"
                      disabled={cm06LoadingPrograms || !inputs.cm06_metadata_file?.trim()}
                      onClick={() => handleLoadCm06Metadata()}
                      className="inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded-md bg-teal-600 hover:bg-teal-700 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
                    >
                      <RefreshCw className={`w-3 h-3 ${cm06LoadingPrograms ? 'animate-spin' : ''}`} />
                      {cm06LoadingPrograms ? 'Loading...' : 'Load Metadata'}
                    </button>
                  </div>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="text"
                      value={inputs.cm06_metadata_file}
                      onChange={(e) => handleInputChange('cm06_metadata_file', e.target.value)}
                      placeholder="/data/uploads/metadata.json or server path"
                      className="flex-1 text-xs px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono"
                    />
                    <label className={`inline-flex items-center justify-center px-3 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer text-slate-700 dark:text-slate-300 shrink-0 ${uploadingField === 'cm06_metadata_file' ? 'opacity-60 cursor-wait' : ''}`}>
                      {uploadingField === 'cm06_metadata_file' ? (
                        <span className="flex items-center gap-1.5">
                          <RefreshCw className="w-3.5 h-3.5 animate-spin text-teal-600" />
                          Uploading...
                        </span>
                      ) : (
                        'Browse...'
                      )}
                      <input
                        type="file"
                        accept=".json"
                        className="hidden"
                        disabled={uploadingField === 'cm06_metadata_file'}
                        onClick={(e) => { e.target.value = null; }}
                        onChange={(e) => {
                          if (e.target.files?.[0]) {
                            handleFileUpload(e.target.files[0], 'cm06_metadata_file');
                          }
                        }}
                      />
                    </label>
                  </div>
                  <div className="flex items-center justify-between text-[11px] pt-0.5">
                    <div className="flex items-center gap-1.5 text-slate-500">
                      <span>Server Quick Pick:</span>
                      <button
                        type="button"
                        onClick={() => {
                          handleInputChange('cm06_metadata_file', '/data/uploads/metadata.json');
                          handleLoadCm06Metadata('/data/uploads/metadata.json');
                        }}
                        className="font-mono text-teal-600 dark:text-teal-400 hover:underline"
                      >
                        /data/uploads/metadata.json
                      </button>
                    </div>
                    {cm06Programs.length > 0 && (
                      <span className="text-teal-600 dark:text-teal-400 font-medium">
                        ✓ Loaded {cm06Programs.length} program(s)
                      </span>
                    )}
                  </div>
                </div>

                {/* 2. OpenMRS 3X Concepts CSV (required) */}
                <div className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900/40 space-y-2">
                  <label className="text-xs font-semibold text-slate-800 dark:text-slate-200 block">
                    OpenMRS 3X Concepts CSV (required) <span className="text-rose-500">*</span>
                  </label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="text"
                      value={inputs.cm06_concepts_file}
                      onChange={(e) => handleInputChange('cm06_concepts_file', e.target.value)}
                      placeholder="/data/exports/concepts.csv or /data/uploads/concepts.csv"
                      className="flex-1 text-xs px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono"
                    />
                    <label className={`inline-flex items-center justify-center px-3 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer text-slate-700 dark:text-slate-300 shrink-0 ${uploadingField === 'cm06_concepts_file' ? 'opacity-60 cursor-wait' : ''}`}>
                      {uploadingField === 'cm06_concepts_file' ? (
                        <span className="flex items-center gap-1.5">
                          <RefreshCw className="w-3.5 h-3.5 animate-spin text-teal-600" />
                          Uploading...
                        </span>
                      ) : (
                        'Browse...'
                      )}
                      <input
                        type="file"
                        accept=".csv"
                        className="hidden"
                        disabled={uploadingField === 'cm06_concepts_file'}
                        onClick={(e) => { e.target.value = null; }}
                        onChange={(e) => {
                          if (e.target.files?.[0]) {
                            handleFileUpload(e.target.files[0], 'cm06_concepts_file');
                          }
                        }}
                      />
                    </label>
                  </div>
                  <div className="flex items-center gap-1.5 text-[11px] text-slate-500 pt-0.5">
                    <span>Server Quick Pick:</span>
                    <button
                      type="button"
                      onClick={() => handleInputChange('cm06_concepts_file', '/data/uploads/concepts.csv')}
                      className="font-mono text-teal-600 dark:text-teal-400 hover:underline"
                    >
                      /data/uploads/concepts.csv
                    </button>
                  </div>
                </div>

                {/* 3. Use DHIS2 Data Dictionary (XLSX) */}
                <div className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900/40 space-y-2">
                  <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={inputs.cm06_use_dictionary}
                      onChange={(e) => handleInputChange('cm06_use_dictionary', e.target.checked)}
                      className="rounded border-slate-300 dark:border-slate-700 text-teal-600 focus:ring-teal-500 cursor-pointer"
                    />
                    <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                      Use DHIS2 Data Dictionary (XLSX)
                    </span>
                  </label>
                  {inputs.cm06_use_dictionary ? (
                    <div className="flex flex-col sm:flex-row gap-2 pt-1">
                      <input
                        type="text"
                        value={inputs.cm06_data_dictionary}
                        onChange={(e) => handleInputChange('cm06_data_dictionary', e.target.value)}
                        placeholder="/data/uploads/data_dictionary.xlsx"
                        className="flex-1 text-xs px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono"
                      />
                      <label className={`inline-flex items-center justify-center px-3 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer text-slate-700 dark:text-slate-300 shrink-0 ${uploadingField === 'cm06_data_dictionary' ? 'opacity-60 cursor-wait' : ''}`}>
                        {uploadingField === 'cm06_data_dictionary' ? (
                          <span className="flex items-center gap-1.5">
                            <RefreshCw className="w-3.5 h-3.5 animate-spin text-teal-600" />
                            Uploading...
                          </span>
                        ) : (
                          'Browse...'
                        )}
                        <input
                          type="file"
                          accept=".xlsx,.xls"
                          className="hidden"
                          disabled={uploadingField === 'cm06_data_dictionary'}
                          onClick={(e) => { e.target.value = null; }}
                          onChange={(e) => {
                            if (e.target.files?.[0]) {
                              handleFileUpload(e.target.files[0], 'cm06_data_dictionary');
                            }
                          }}
                        />
                      </label>
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 dark:text-slate-500 italic">
                      Data dictionary disabled. Schema generator will match using concepts CSV and DHIS2 data element names.
                    </p>
                  )}
                  {inputs.cm06_use_dictionary && (
                    <div className="flex items-center gap-1.5 text-[11px] text-slate-500 pt-0.5">
                      <span>Server Quick Pick:</span>
                      <button
                        type="button"
                        onClick={() => handleInputChange('cm06_data_dictionary', '/data/uploads/NCF_DD.xlsx')}
                        className="font-mono text-teal-600 dark:text-teal-400 hover:underline"
                      >
                        /data/uploads/NCF_DD.xlsx
                      </button>
                    </div>
                  )}
                </div>

                {/* 4. Output Directory */}
                <DirectoryPicker
                  label="Output Directory:"
                  value={inputs.cm06_output_dir}
                  onChange={(val) => handleInputChange('cm06_output_dir', val)}
                  helperText="Select or browse directory where generated .form.json and mapping CSV reports will be saved"
                />

                {/* 5. Encounter Type UUID (optional) */}
                <TextInput
                  label="Encounter Type UUID (optional):"
                  value={inputs.cm06_encounter_type}
                  onChange={(e) => handleInputChange('cm06_encounter_type', e.target.value)}
                  placeholder="e.g. e22e39fd-7db2-45e7-80f1-60fa0d7a4378"
                  helperText="Optional OpenMRS encounter type UUID to include in form schemas"
                />

                <div className="border-t border-slate-200 dark:border-slate-700/60 my-2" />

                {/* 6. Select Program */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                      Select Program: <span className="text-rose-500">*</span>
                    </label>
                    {cm06Programs.length > 0 && (
                      <span className="text-[11px] text-slate-500 dark:text-slate-400">
                        {cm06Programs.length} program(s) loaded
                      </span>
                    )}
                  </div>
                  {cm06Programs.length > 0 ? (
                    <select
                      value={inputs.cm06_program_name}
                      onChange={(e) => handleSelectCm06Program(e.target.value)}
                      className="w-full text-xs px-3 py-2.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-medium focus:ring-2 focus:ring-teal-500"
                    >
                      {cm06Programs.map((p) => (
                        <option key={p.id || p.name} value={p.name}>
                          {p.name} ({p.stages_count || p.stages?.length || 0} stage{p.stages_count === 1 ? '' : 's'})
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="flex gap-2">
                      <TextInput
                        value={inputs.cm06_program_name}
                        onChange={(e) => handleInputChange('cm06_program_name', e.target.value)}
                        placeholder="Load metadata above to pick a program, or enter program name..."
                      />
                      <button
                        type="button"
                        onClick={() => handleLoadCm06Metadata()}
                        disabled={!inputs.cm06_metadata_file?.trim() || cm06LoadingPrograms}
                        className="px-3 py-2 text-xs font-medium rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-300 dark:border-slate-700 hover:bg-slate-200 shrink-0"
                      >
                        Load Programs
                      </button>
                    </div>
                  )}
                </div>

                {/* 7. Program Stages */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                      Program Stages:
                    </label>
                    {cm06Stages.length > 0 && (
                      <span className="text-[11px] font-mono text-teal-600 dark:text-teal-400 font-semibold">
                        {cm06Stages.length} stage(s)
                      </span>
                    )}
                  </div>
                  <div className="p-3 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-slate-50 dark:bg-slate-900/60 max-h-52 overflow-y-auto space-y-1 font-mono text-xs">
                    {cm06Stages.length > 0 ? (
                      cm06Stages.map((stageName, idx) => (
                        <div
                          key={idx}
                          className="flex items-center gap-2 py-1 px-2.5 rounded bg-white dark:bg-slate-800/80 border border-slate-200/50 dark:border-slate-700/50"
                        >
                          <span className="text-slate-400 text-[10px] w-6 shrink-0 font-sans font-semibold">
                            [{idx + 1}]
                          </span>
                          <span className="text-slate-800 dark:text-slate-200 font-sans text-xs">
                            {stageName}
                          </span>
                        </div>
                      ))
                    ) : (
                      <div className="py-4 text-center text-slate-400 dark:text-slate-500 font-sans text-xs italic">
                        {inputs.cm06_metadata_file
                          ? '(no stages found for selected program)'
                          : '(please load DHIS2 metadata JSON above to view program stages)'}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* CM-07: Export All Concepts */}
            {selectedToolId === 'cm07_export_all' && (
              <div className="space-y-4">
                <div>
                  <label className="text-xs font-semibold text-slate-700 dark:text-slate-300 mb-2 block">
                    Export Format (Select CSV or JSON)
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div
                      onClick={() => {
                        handleInputChange('cm07_format', 'csv');
                        const currentName = inputs.cm07_output_filename || 'openmrs_all_concepts.csv';
                        if (currentName.endsWith('.json')) {
                          handleInputChange('cm07_output_filename', currentName.replace(/\.json$/i, '.csv'));
                        }
                      }}
                      className={`cursor-pointer rounded-xl border p-4 transition-all flex items-start gap-3 select-none ${
                        (inputs.cm07_format || 'csv') === 'csv'
                          ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/30 ring-2 ring-emerald-500/20'
                          : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700'
                      }`}
                    >
                      <input
                        type="radio"
                        id="cm07_fmt_csv"
                        name="cm07_format"
                        value="csv"
                        checked={(inputs.cm07_format || 'csv') === 'csv'}
                        onChange={() => {
                          handleInputChange('cm07_format', 'csv');
                          const currentName = inputs.cm07_output_filename || 'openmrs_all_concepts.csv';
                          if (currentName.endsWith('.json')) {
                            handleInputChange('cm07_output_filename', currentName.replace(/\.json$/i, '.csv'));
                          }
                        }}
                        className="mt-1 h-4 w-4 text-emerald-600 focus:ring-emerald-500 border-slate-300 dark:border-slate-700"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <FileSpreadsheet className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                            CSV Format (.csv)
                          </span>
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300">
                            Standard
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
                          Tabular export compatible with Excel and Google Sheets. Columns: Fully Specified Name, Short Name, UUID, Concept ID, Datatype, Concept Class, Answers.
                        </p>
                      </div>
                    </div>

                    <div
                      onClick={() => {
                        handleInputChange('cm07_format', 'json');
                        const currentName = inputs.cm07_output_filename || 'openmrs_all_concepts.csv';
                        if (currentName.endsWith('.csv')) {
                          handleInputChange('cm07_output_filename', currentName.replace(/\.csv$/i, '.json'));
                        }
                      }}
                      className={`cursor-pointer rounded-xl border p-4 transition-all flex items-start gap-3 select-none ${
                        inputs.cm07_format === 'json'
                          ? 'border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/30 ring-2 ring-emerald-500/20'
                          : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-slate-300 dark:hover:border-slate-700'
                      }`}
                    >
                      <input
                        type="radio"
                        id="cm07_fmt_json"
                        name="cm07_format"
                        value="json"
                        checked={inputs.cm07_format === 'json'}
                        onChange={() => {
                          handleInputChange('cm07_format', 'json');
                          const currentName = inputs.cm07_output_filename || 'openmrs_all_concepts.csv';
                          if (currentName.endsWith('.csv')) {
                            handleInputChange('cm07_output_filename', currentName.replace(/\.csv$/i, '.json'));
                          }
                        }}
                        className="mt-1 h-4 w-4 text-emerald-600 focus:ring-emerald-500 border-slate-300 dark:border-slate-700"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <Code className="w-4 h-4 text-blue-600 dark:text-blue-400 shrink-0" />
                          <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                            JSON Format (.json)
                          </span>
                        </div>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
                          Hierarchical clean JSON structure preserving concept definitions, multilingual names, UUIDs, concept IDs, datatypes, and answer links.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400">
                  <Server className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Using saved <strong>OpenMRS 3.x</strong> connection credentials from Settings & Connections.</span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div className="sm:col-span-2">
                    <DirectoryPicker
                      label="Export Destination Directory"
                      value={inputs.cm07_output_dir}
                      onChange={(val) => handleInputChange('cm07_output_dir', val)}
                      helperText="Directory where the exported concept file will be saved"
                    />
                  </div>
                  <div>
                    <TextInput
                      label="Output Filename"
                      value={inputs.cm07_output_filename || (inputs.cm07_format === 'json' ? 'openmrs_all_concepts.json' : 'openmrs_all_concepts.csv')}
                      onChange={(e) => handleInputChange('cm07_output_filename', e.target.value)}
                      placeholder={inputs.cm07_format === 'json' ? 'openmrs_all_concepts.json' : 'openmrs_all_concepts.csv'}
                      helperText={`Target: ${inputs.cm07_output_dir || '/data/exports'}/${inputs.cm07_output_filename || (inputs.cm07_format === 'json' ? 'openmrs_all_concepts.json' : 'openmrs_all_concepts.csv')}`}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* CM-08: Enhanced Form Generator */}
            {selectedToolId === 'cm08_enhanced_gen' && (
              <div className="space-y-4">
                {/* 1. DHIS2 Metadata JSON */}
                <div className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900/40 space-y-2">
                  <label className="text-xs font-semibold text-slate-800 dark:text-slate-200 block">
                    DHIS2 Metadata JSON: <span className="text-rose-500">*</span>
                  </label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="text"
                      value={inputs.cm08_metadata_file}
                      onChange={(e) => handleInputChange('cm08_metadata_file', e.target.value)}
                      placeholder="/data/uploads/metadata.json"
                      className="flex-1 text-xs px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono"
                    />
                    <label className={`inline-flex items-center justify-center px-3 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer text-slate-700 dark:text-slate-300 shrink-0 ${uploadingField === 'cm08_metadata_file' ? 'opacity-60 cursor-wait' : ''}`}>
                      {uploadingField === 'cm08_metadata_file' ? (
                        <span className="flex items-center gap-1.5">
                          <RefreshCw className="w-3.5 h-3.5 animate-spin text-teal-600" />
                          Uploading...
                        </span>
                      ) : (
                        'Browse...'
                      )}
                      <input
                        type="file"
                        accept=".json"
                        className="hidden"
                        disabled={uploadingField === 'cm08_metadata_file'}
                        onClick={(e) => { e.target.value = null; }}
                        onChange={(e) => {
                          if (e.target.files?.[0]) {
                            handleFileUpload(e.target.files[0], 'cm08_metadata_file');
                          }
                        }}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => handleLoadCm08Metadata()}
                      disabled={!inputs.cm08_metadata_file?.trim() || cm08LoadingPrograms}
                      className="inline-flex items-center justify-center px-3 py-2 text-xs font-medium rounded-md bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white shrink-0 transition-colors"
                    >
                      {cm08LoadingPrograms ? (
                        <span className="flex items-center gap-1.5">
                          <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                          Loading...
                        </span>
                      ) : (
                        'Load Metadata'
                      )}
                    </button>
                  </div>
                  <div className="flex items-center justify-between text-[11px] pt-0.5">
                    <div className="flex items-center gap-1.5 text-slate-500">
                      <span>Server Quick Pick:</span>
                      <button
                        type="button"
                        onClick={() => {
                          handleInputChange('cm08_metadata_file', '/data/uploads/metadata.json');
                          handleLoadCm08Metadata('/data/uploads/metadata.json');
                        }}
                        className="font-mono text-teal-600 dark:text-teal-400 hover:underline"
                      >
                        /data/uploads/metadata.json
                      </button>
                    </div>
                    {cm08Programs.length > 0 && (
                      <span className="text-teal-600 dark:text-teal-400 font-medium">
                        ✓ Loaded {cm08Programs.length} program(s)
                      </span>
                    )}
                  </div>
                </div>

                {/* 2. Concepts CSV */}
                <div className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900/40 space-y-2">
                  <label className="text-xs font-semibold text-slate-800 dark:text-slate-200 block">
                    Concepts CSV: <span className="text-rose-500">*</span>
                  </label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <input
                      type="text"
                      value={inputs.cm08_concepts_file}
                      onChange={(e) => handleInputChange('cm08_concepts_file', e.target.value)}
                      placeholder="/data/exports/openmrs_all_concepts.csv or /data/uploads/concepts.csv"
                      className="flex-1 text-xs px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono"
                    />
                    <label className={`inline-flex items-center justify-center px-3 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer text-slate-700 dark:text-slate-300 shrink-0 ${uploadingField === 'cm08_concepts_file' ? 'opacity-60 cursor-wait' : ''}`}>
                      {uploadingField === 'cm08_concepts_file' ? (
                        <span className="flex items-center gap-1.5">
                          <RefreshCw className="w-3.5 h-3.5 animate-spin text-teal-600" />
                          Uploading...
                        </span>
                      ) : (
                        'Browse...'
                      )}
                      <input
                        type="file"
                        accept=".csv"
                        className="hidden"
                        disabled={uploadingField === 'cm08_concepts_file'}
                        onClick={(e) => { e.target.value = null; }}
                        onChange={(e) => {
                          if (e.target.files?.[0]) {
                            handleFileUpload(e.target.files[0], 'cm08_concepts_file');
                          }
                        }}
                      />
                    </label>
                  </div>
                  <div className="flex items-center gap-1.5 text-[11px] text-slate-500 pt-0.5">
                    <span>Server Quick Pick:</span>
                    <button
                      type="button"
                      onClick={() => handleInputChange('cm08_concepts_file', '/data/exports/openmrs_all_concepts.csv')}
                      className="font-mono text-teal-600 dark:text-teal-400 hover:underline"
                    >
                      /data/exports/openmrs_all_concepts.csv
                    </button>
                    <span className="text-slate-300 dark:text-slate-700">|</span>
                    <button
                      type="button"
                      onClick={() => handleInputChange('cm08_concepts_file', '/data/uploads/concepts.csv')}
                      className="font-mono text-teal-600 dark:text-teal-400 hover:underline"
                    >
                      /data/uploads/concepts.csv
                    </button>
                  </div>
                </div>

                {/* 3. Use DHIS2 Data Dictionary (XLSX) */}
                <div className="p-3.5 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-white dark:bg-slate-900/40 space-y-2">
                  <label className="inline-flex items-center gap-2 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={inputs.cm08_use_dictionary}
                      onChange={(e) => handleInputChange('cm08_use_dictionary', e.target.checked)}
                      className="rounded border-slate-300 dark:border-slate-700 text-teal-600 focus:ring-teal-500 cursor-pointer"
                    />
                    <span className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                      Use DHIS2 Data Dictionary (XLSX)
                    </span>
                  </label>
                  {inputs.cm08_use_dictionary ? (
                    <div className="flex flex-col sm:flex-row gap-2 pt-1">
                      <input
                        type="text"
                        value={inputs.cm08_data_dictionary}
                        onChange={(e) => handleInputChange('cm08_data_dictionary', e.target.value)}
                        placeholder="/data/uploads/NCF_DD.xlsx"
                        className="flex-1 text-xs px-3 py-2 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-mono"
                      />
                      <label className={`inline-flex items-center justify-center px-3 py-2 text-xs font-medium rounded-md border border-slate-300 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer text-slate-700 dark:text-slate-300 shrink-0 ${uploadingField === 'cm08_data_dictionary' ? 'opacity-60 cursor-wait' : ''}`}>
                        {uploadingField === 'cm08_data_dictionary' ? (
                          <span className="flex items-center gap-1.5">
                            <RefreshCw className="w-3.5 h-3.5 animate-spin text-teal-600" />
                            Uploading...
                          </span>
                        ) : (
                          'Browse...'
                        )}
                        <input
                          type="file"
                          accept=".xlsx,.xls"
                          className="hidden"
                          disabled={uploadingField === 'cm08_data_dictionary'}
                          onClick={(e) => { e.target.value = null; }}
                          onChange={(e) => {
                            if (e.target.files?.[0]) {
                              handleFileUpload(e.target.files[0], 'cm08_data_dictionary');
                            }
                          }}
                        />
                      </label>
                    </div>
                  ) : (
                    <p className="text-[11px] text-slate-400 dark:text-slate-500 italic">
                      Data dictionary disabled. Enhanced generator will match using concepts CSV and DHIS2 data element names.
                    </p>
                  )}
                  {inputs.cm08_use_dictionary && (
                    <div className="flex items-center gap-1.5 text-[11px] text-slate-500 pt-0.5">
                      <span>Server Quick Pick:</span>
                      <button
                        type="button"
                        onClick={() => handleInputChange('cm08_data_dictionary', '/data/uploads/NCF_DD.xlsx')}
                        className="font-mono text-teal-600 dark:text-teal-400 hover:underline"
                      >
                        /data/uploads/NCF_DD.xlsx
                      </button>
                    </div>
                  )}
                </div>

                {/* 4. Output Directory */}
                <DirectoryPicker
                  label="Output Directory:"
                  value={inputs.cm08_output_dir}
                  onChange={(val) => handleInputChange('cm08_output_dir', val)}
                  helperText="Select or browse the target directory where enhanced form schemas with rules will be saved"
                />

                {/* 5. Encounter Type UUID (optional) */}
                <TextInput
                  label="Encounter Type UUID (optional):"
                  value={inputs.cm08_encounter_type}
                  onChange={(e) => handleInputChange('cm08_encounter_type', e.target.value)}
                  placeholder="e.g. e22e39fd-7db2-45e7-80f1-60fa0d7a4378"
                  helperText="Optional OpenMRS encounter type UUID to include in form schemas"
                />

                <div className="border-t border-slate-200 dark:border-slate-700/60 my-2" />

                {/* 6. Select Program */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                      Select Program: <span className="text-rose-500">*</span>
                    </label>
                    {cm08Programs.length > 0 && (
                      <span className="text-[11px] text-slate-500 dark:text-slate-400">
                        {cm08Programs.length} program(s) loaded
                      </span>
                    )}
                  </div>
                  {cm08Programs.length > 0 ? (
                    <select
                      value={inputs.cm08_program_name}
                      onChange={(e) => handleSelectCm08Program(e.target.value)}
                      className="w-full text-xs px-3 py-2.5 rounded-md border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 font-medium focus:ring-2 focus:ring-teal-500"
                    >
                      {cm08Programs.map((p) => (
                        <option key={p.id || p.name} value={p.name}>
                          {p.name} ({p.stages_count || p.stages?.length || 0} stage{p.stages_count === 1 ? '' : 's'})
                        </option>
                      ))}
                    </select>
                  ) : (
                    <div className="flex gap-2">
                      <TextInput
                        value={inputs.cm08_program_name}
                        onChange={(e) => handleInputChange('cm08_program_name', e.target.value)}
                        placeholder="Load metadata above to pick a program, or enter program name..."
                      />
                      <button
                        type="button"
                        onClick={() => handleLoadCm08Metadata()}
                        disabled={!inputs.cm08_metadata_file?.trim() || cm08LoadingPrograms}
                        className="px-3 py-2 text-xs font-medium rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-300 dark:border-slate-700 hover:bg-slate-200 shrink-0"
                      >
                        Load Programs
                      </button>
                    </div>
                  )}
                </div>

                {/* 7. Program Stages */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                      Program Stages:
                    </label>
                    {cm08Stages.length > 0 && (
                      <span className="text-[11px] font-mono text-teal-600 dark:text-teal-400 font-semibold">
                        {cm08Stages.length} stage(s)
                      </span>
                    )}
                  </div>
                  <div className="p-3 rounded-lg border border-slate-200 dark:border-slate-700/60 bg-slate-50 dark:bg-slate-900/60 max-h-52 overflow-y-auto space-y-1 font-mono text-xs">
                    {cm08Stages.length > 0 ? (
                      cm08Stages.map((stageName, idx) => (
                        <div
                          key={idx}
                          className="flex items-center gap-2 py-1 px-2.5 rounded bg-white dark:bg-slate-800/80 border border-slate-200/50 dark:border-slate-700/50"
                        >
                          <span className="text-slate-400 text-[10px] w-6 shrink-0 font-sans font-semibold">
                            [{idx + 1}]
                          </span>
                          <span className="text-slate-800 dark:text-slate-200 font-sans text-xs">
                            {stageName}
                          </span>
                        </div>
                      ))
                    ) : (
                      <div className="py-4 text-center text-slate-400 dark:text-slate-500 font-sans text-xs italic">
                        {inputs.cm08_metadata_file
                          ? '(no stages found for selected program)'
                          : '(please load DHIS2 metadata JSON above to view program stages)'}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}



            {/* CM-09: Export Form Concepts */}
            {selectedToolId === 'cm09_export_form_concepts' && (
              <div className="space-y-4">
                <DirectoryPicker
                  label="Forms Directory Path"
                  value={inputs.cm09_forms_dir}
                  onChange={(val) => handleInputChange('cm09_forms_dir', val)}
                  helperText="Select or browse the directory containing .form.json schemas"
                  presetDirs={[
                    '/data/schemas/Maternal Inpatient Data',
                    '/data/schemas/Neonatal Care Form',
                    '/data/schemas',
                    '/data/schemas/enhanced',
                  ]}
                />
                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400">
                  <Server className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Using saved <strong>OpenMRS 3.x</strong> connection credentials from Settings & Connections.</span>
                </div>
                <DirectoryPicker
                  label="Exported Concepts Destination Directory"
                  value={inputs.cm09_output_dir}
                  onChange={(val) => handleInputChange('cm09_output_dir', val)}
                  helperText="Select or browse the destination directory where extracted concept JSON files will be saved"
                  presetDirs={[
                    '/data/exports/form-concepts',
                    '/data/exports',
                  ]}
                />
              </div>
            )}

            {/* CM-10: Batch Import Form Schemas */}
            {selectedToolId === 'cm10_import_schemas' && (
              <div className="space-y-4">
                <DirectoryPicker
                  label="Forms Folder / File Path"
                  value={inputs.cm10_forms_dir}
                  onChange={(val) => handleInputChange('cm10_forms_dir', val)}
                  helperText="Select or browse the directory or JSON file containing form schema(s) to import into OpenMRS 3.x"
                  allowFileUpload={true}
                  presetDirs={[
                    '/data/schemas/Maternal Inpatient Data',
                    '/data/schemas/Neonatal Care Form',
                    '/data/schemas',
                    '/data/schemas/enhanced',
                  ]}
                />
                <div className="flex items-center gap-2 p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-xs text-emerald-400">
                  <Server className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>Using saved <strong>OpenMRS 3.x</strong> connection credentials from Settings & Connections.</span>
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              {selectedToolId !== 'cm01_bahmni' && (
                <Button
                  variant="secondary"
                  icon={<RotateCcw className="w-4 h-4 mr-1.5 text-amber-500" />}
                  loading={isStreaming}
                  disabled={isViewer}
                  onClick={() => handleRunTool(true)}
                >
                  Dry-Run Simulation
                </Button>
              )}
              <Button
                variant="primary"
                icon={<Play className="w-4 h-4 mr-1.5" />}
                loading={isStreaming}
                disabled={isViewer}
                onClick={() => handleRunTool(false)}
              >
                Execute {currentTool.name}
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
          title="Operation Execution Log"
        />
      </div>

      <ConfirmDialog
        open={showConfirm}
        targetSystem="openmrs"
        title={`Execute ${currentTool.name}?`}
        message="This will execute real write operations on OpenMRS 3.x server. Are you sure you want to proceed?"
        confirmText="Confirm & Run"
        onConfirm={() => executeActiveTool(false)}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default Openmrs3xToolsPage;
