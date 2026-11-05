import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../context/AuthContext';
import { useConnections } from '../context/ConnectionContext';
import {
  Zap,
  Server,
  Play,
  RotateCcw,
  Eye,
  FileSpreadsheet,
  Upload,
  Check,
  Building2,
  AlertTriangle,
  FileText,
  Code,
  ListFilter,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Download,
  Calendar,
  Phone,
  MapPin,
  User,
  Lock,
  ArrowRight,
  ArrowLeft,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  Badge,
  FileDropzone,
  JobPanel,
  ConfirmDialog,
  Alert,
  Switch,
  Tabs,
} from '../ui';
import StatusBadge from '../ui/StatusBadge';
import { useToast } from '../ui/ToastProvider';

const SmartcarePage = () => {
  const { authHeader, isViewer } = useAuth();
  const { showToast } = useToast();

  // Shared connections context for single source of truth (Requirement B3)
  const { summary, testSingle, testingMap } = useConnections();
  const openmrsSystem = summary?.list?.find((s) => s.key === 'openmrs');
  const isTestingOpenmrs = Boolean(testingMap?.openmrs || openmrsSystem?.isTesting);

  // SmartCare-specific metadata state
  const [locations, setLocations] = useState([]);
  const [availableFiles, setAvailableFiles] = useState([]);

  // Active wizard step: 1 (CSV Source), 2 (Configure & Audit), 3 (Confirm Scope), 4 (Live Migration)
  const [activeStep, setActiveStep] = useState(1);

  // File upload / selection state (Step 1)
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadedInfo, setUploadedInfo] = useState(null);
  const [uploadError, setUploadError] = useState('');

  // Configuration options (Step 2)
  const [rowLimit, setRowLimit] = useState('500');
  const [includeLegacyId, setIncludeLegacyId] = useState(true);
  const [fieldMappings, setFieldMappings] = useState({
    // OpenMRS 3: Basic Info (Demographics & Identifiers)
    patient_id: '',
    patient_guid: '',
    given_name: '',
    middle_name: '',
    family_name: '',
    gender: '',
    birthdate_mode: 'separate', // 'separate' | 'all_in_one'
    birthdate: '',
    birth_year: '',
    birth_month: '',
    birth_day: '',
    age_enrollment: '',
    // OpenMRS 3: Contact Details (Phone & Address Hierarchy)
    phone: '',
    woreda: '',
    zone: '',
    region: '',
    kebele: '',
    house_number: '',
  });

  const detectInitialMappings = (headers = []) => {
    if (!headers || headers.length === 0) return;
    const lowerMap = {};
    headers.forEach((h) => {
      lowerMap[h.toLowerCase().replace(/[^a-z0-9]/g, '')] = h;
    });

    const findCol = (candidates) => {
      for (const c of candidates) {
        const norm = c.toLowerCase().replace(/[^a-z0-9]/g, '');
        if (lowerMap[norm]) return lowerMap[norm];
      }
      for (const h of headers) {
        const hNorm = h.toLowerCase().replace(/[^a-z0-9]/g, '');
        for (const c of candidates) {
          const norm = c.toLowerCase().replace(/[^a-z0-9]/g, '');
          if (hNorm.includes(norm)) return h;
        }
      }
      return '';
    };

    const hasBirthYear = Boolean(findCol(['birthyear', 'birth_year', 'byear', 'year']));
    const hasBirthMonth = Boolean(findCol(['birthmonth', 'birth_month', 'bmonth', 'month']));
    const hasSingleDob = Boolean(findCol(['birthdate', 'dob', 'dateofbirth', 'birth_date', 'date_of_birth']));

    const initialMode = hasBirthYear || hasBirthMonth ? 'separate' : hasSingleDob ? 'all_in_one' : 'separate';

    setFieldMappings({
      patient_id: findCol(['patientid', 'patient_id', 'mrn', 'cardnumber', 'id']),
      patient_guid: findCol(['patientguid', 'patient_guid', 'guid', 'uuid']),
      given_name: findCol(['firstname', 'first_name', 'givenname', 'given_name', 'name']),
      middle_name: findCol(['middlename', 'middle_name', 'fathername', 'father_name']),
      family_name: findCol(['surname', 'sur_name', 'familyname', 'family_name', 'lastname', 'last_name', 'grandfather']),
      gender: findCol(['sex', 'gender']),
      birthdate_mode: initialMode,
      birthdate: findCol(['birthdate', 'dob', 'dateofbirth', 'birth_date', 'date_of_birth']),
      birth_year: findCol(['birthyear', 'birth_year', 'year']),
      birth_month: findCol(['birthmonth', 'birth_month', 'month']),
      birth_day: findCol(['birthday', 'birth_day', 'day']),
      age_enrollment: findCol(['ageatdateofenrollment', 'ageatenrollment', 'enrollmentage', 'age']),
      phone: findCol(['phone', 'spousephone', 'telephone', 'phonenumber', 'mobile']),
      woreda: findCol(['districtname', 'district_name', 'woreda', 'cityvillage', 'district', 'city']),
      zone: findCol(['zone', 'countydistrict']),
      region: findCol(['region', 'stateprovince']),
      kebele: findCol(['kebele', 'address3']),
      house_number: findCol(['housenumber', 'address1', 'house_number']),
    });
  };

  // Dry Run state (Step 2)
  const [dryRunRunning, setDryRunRunning] = useState(false);
  const [dryRunResult, setDryRunResult] = useState(null);
  const [dryRunError, setDryRunError] = useState('');
  const [activeTab, setActiveTab] = useState('preview');

  // Execution & Confirmation Modal (Step 3)
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const [importing, setImporting] = useState(false);

  // Active Job & Live SSE Streaming (Step 4)
  const [activeJobId, setActiveJobId] = useState(null);
  const [jobState, setJobState] = useState(null);
  const [liveLogs, setLiveLogs] = useState([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const eventSourceRef = useRef(null);

  // Load SmartCare metadata (preset files, locations) on mount
  useEffect(() => {
    fetchMetadata();
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const fetchMetadata = async () => {
    try {
      const scRes = await fetch('/api/smartcare/status', { headers: authHeader() });
      if (scRes.ok) {
        const scData = await scRes.json();
        setLocations(scData.connection?.locations || []);
        setAvailableFiles(scData.available_files || []);
      }
    } catch (err) {
      console.warn('Could not fetch SmartCare metadata:', err);
    }
  };

  const handleFileUpload = async (selectedFile) => {
    if (!selectedFile) return;

    setFile(selectedFile);
    setUploadError('');
    setUploading(true);
    setDryRunResult(null);

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const res = await fetch('/api/smartcare/upload', {
        method: 'POST',
        headers: authHeader(),
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to upload CSV file');
      }

      const data = await res.json();
      setUploadedInfo(data);
      detectInitialMappings(data.headers || []);
      setActiveStep(2);
      showToast(
        `Parsed ${Number(data.total_rows || 0).toLocaleString()} rows from ${data.filename}`,
        'success',
        'Upload Successful'
      );
      fetchMetadata();
    } catch (err) {
      setUploadError(err.message);
      showToast(err.message, 'error', 'Upload Failed');
    } finally {
      setUploading(false);
    }
  };

  const handleSelectPresetFile = (selectedPath) => {
    if (!selectedPath) return;
    const found = availableFiles.find((f) => f.filepath === selectedPath);
    if (found) {
      setFile(null);
      setUploadedInfo({
        filename: found.filename,
        filepath: found.filepath,
        total_rows: found.total_rows,
        headers: found.headers || [],
      });
      detectInitialMappings(found.headers || []);
      setDryRunResult(null);
      setUploadError('');
      setActiveStep(2);
      showToast(
        `Selected ${found.filename} (${Number(found.total_rows || 0).toLocaleString()} records)`,
        'info',
        'File Selected'
      );
    }
  };

  const runDryRun = async () => {
    if (!uploadedInfo) return;

    setDryRunRunning(true);
    setDryRunError('');
    setDryRunResult(null);

    try {
      const res = await fetch('/api/smartcare/dry-run', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({
          filepath: uploadedInfo.filepath,
          limit: rowLimit ? parseInt(rowLimit, 10) : null,
          config: {
            include_legacy_id: includeLegacyId,
            field_mappings: fieldMappings,
          },
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Dry run audit failed');
      }

      const result = await res.json();
      setDryRunResult(result);
      showToast(
        `Audited ${Number(result.summary?.total_records || result.summary?.total_rows || 0).toLocaleString()} records: ${Number(result.summary?.valid_records || 0).toLocaleString()} valid`,
        'success',
        'Dry Run Complete'
      );
    } catch (err) {
      setDryRunError(err.message);
      showToast(err.message, 'error', 'Dry Run Error');
    } finally {
      setDryRunRunning(false);
    }
  };

  const handleStartImport = async () => {
    setShowConfirmModal(false);
    setImporting(true);
    setLiveLogs([]);
    setJobState({ status: 'running', progress: 0, message: 'Initiating migration job...' });
    setActiveStep(4);

    try {
      const res = await fetch('/api/smartcare/import', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeader(),
        },
        body: JSON.stringify({
          filepath: uploadedInfo.filepath,
          limit: rowLimit ? parseInt(rowLimit, 10) : null,
          config: {
            include_legacy_id: includeLegacyId,
            field_mappings: fieldMappings,
          },
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to dispatch migration job');
      }

      const data = await res.json();
      setActiveJobId(data.job_id);
      showToast(
        `Job ${data.job_id} is running in background`,
        'info',
        'Job Dispatched'
      );

      startEventStream(data.job_id);
    } catch (err) {
      showToast(err.message, 'error', 'Execution Failed');
    } finally {
      setImporting(false);
    }
  };

  const fetchLatestJobState = async (jobId) => {
    if (!jobId) return null;
    try {
      const res = await fetch(`/api/jobs/${jobId}`, { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setJobState(data);
        if (['completed', 'failed', 'canceled'].includes(data.status)) {
          setIsStreaming(false);
          if (eventSourceRef.current) {
            eventSourceRef.current.close();
          }
        }
        return data;
      }
    } catch (e) {
      console.warn('Could not fetch latest job state:', e);
    }
    return null;
  };

  const startEventStream = (jobId) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsStreaming(true);
    const token = localStorage.getItem('imnid_token');
    const sseUrl = `/api/jobs/${jobId}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`;
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    const handlePayload = (parsed) => {
      if (!parsed) return;
      if (parsed.type === 'log' || parsed.event === 'log') {
        const item = parsed.data ?? parsed.item ?? parsed.line;
        setLiveLogs((prev) => [...prev, item]);
      } else if (parsed.type === 'progress' || parsed.event === 'progress') {
        setJobState((prev) => ({ ...(prev || {}), ...(parsed.data || parsed) }));
      } else if (parsed.type === 'status' || parsed.type === 'state' || parsed.event === 'status') {
        const stateData = parsed.data || parsed;
        setJobState((prev) => ({ ...(prev || {}), ...stateData }));
        if (['completed', 'failed', 'canceled'].includes(stateData.status)) {
          setIsStreaming(false);
          es.close();
          fetchLatestJobState(jobId);
        }
      }
    };

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        handlePayload(parsed);
      } catch (e) {
        if (event.data) setLiveLogs((prev) => [...prev, event.data]);
      }
    };

    es.addEventListener('log', (event) => {
      try {
        const parsed = JSON.parse(event.data);
        const item = parsed.item || parsed.line || parsed;
        setLiveLogs((prev) => [...prev, item]);
      } catch {
        if (event.data) setLiveLogs((prev) => [...prev, event.data]);
      }
    });

    es.addEventListener('progress', (event) => {
      try {
        const data = JSON.parse(event.data);
        setJobState((prev) => ({ ...(prev || {}), ...data }));
      } catch (e) {
        console.error('Progress event parse error:', e);
      }
    });

    es.addEventListener('status', (event) => {
      try {
        const data = JSON.parse(event.data);
        setJobState((prev) => ({ ...(prev || {}), ...data }));
        if (['completed', 'failed', 'canceled'].includes(data.status)) {
          setIsStreaming(false);
          es.close();
          fetchLatestJobState(jobId);
        }
      } catch (e) {
        console.error('Status event parse error:', e);
      }
    });

    es.onerror = () => {
      console.warn('SSE disconnected, fetching latest job state.');
      fetchLatestJobState(jobId);
    };

    fetchLatestJobState(jobId);

    const pollTimer = setInterval(async () => {
      const state = await fetchLatestJobState(jobId);
      if (state && ['completed', 'failed', 'canceled'].includes(state.status)) {
        clearInterval(pollTimer);
        setIsStreaming(false);
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
        }
      }
    }, 2000);
  };

  const handleCancelJob = async () => {
    if (!activeJobId) return;
    try {
      await fetch(`/api/jobs/${activeJobId}/cancel`, {
        method: 'POST',
        headers: authHeader(),
      });
      showToast('Sent termination signal to worker', 'warning', 'Cancel Requested');
    } catch (e) {
      console.error(e);
    }
  };

  const handleClearFile = () => {
    setUploadedInfo(null);
    setFile(null);
    setDryRunResult(null);
    setDryRunError('');
    setActiveStep(1);
  };

  const uploadedHeaders = uploadedInfo?.headers || [];

  // Steps definition for 4-Step Stepper Bar
  const steps = [
    { step: 1, title: 'CSV Source', desc: 'Select or Upload CSV' },
    { step: 2, title: 'Configure & Audit', desc: 'Luhn, UUID & Dry-Run' },
    { step: 3, title: 'Confirm Scope', desc: 'Target & Facility Verify' },
    { step: 4, title: 'Live Migration', desc: 'Stream OpenMRS Imports' },
  ];

  const handleStepClick = (stepNum) => {
    if (stepNum === 1) setActiveStep(1);
    else if (stepNum === 2 && uploadedInfo) setActiveStep(2);
    else if (stepNum === 3 && uploadedInfo) setActiveStep(3);
    else if (stepNum === 4 && activeJobId) setActiveStep(4);
  };

  return (
    <div className="space-y-6 w-full pb-16">
      {/* Top Header with Shared Single-Source-of-Truth Connection Badge (Requirement B3) */}
      <PageHeader
        title="SmartCare to OpenMRS 3.x Migration"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Migration', to: '/smartcare' },
          { label: 'SmartCare to OpenMRS 3.x' },
        ]}
        actions={
          <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-xs shadow-xs">
            <Server className="w-4 h-4 text-teal-600 dark:text-teal-400 shrink-0" />
            <div className="flex flex-col text-left">
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-slate-800 dark:text-slate-200">OpenMRS 3.x</span>
                <StatusBadge status={isTestingOpenmrs ? 'testing' : (openmrsSystem?.state || 'unknown')} size="xs" />
              </div>
              <span className="text-[11px] font-mono text-slate-400 truncate max-w-[210px]" title={openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}>
                {openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}
              </span>
            </div>
            <button
              type="button"
              onClick={() => testSingle('openmrs')}
              disabled={isTestingOpenmrs}
              className="ml-2 text-xs text-teal-600 dark:text-teal-400 hover:text-teal-700 dark:hover:text-teal-300 font-semibold cursor-pointer disabled:opacity-50"
            >
              {isTestingOpenmrs ? 'Testing...' : 'Retest'}
            </button>
          </div>
        }
      />

      {/* Stepper Bar */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 p-2 shadow-xs h-12 flex items-center">
        <div className="grid grid-cols-4 gap-2 w-full h-full">
          {steps.map((s) => {
            const isCompleted = (s.step === 1 && uploadedInfo) ||
                                (s.step === 2 && dryRunResult) ||
                                (s.step === 3 && activeJobId) ||
                                (s.step === 4 && activeJobId && ['completed', 'failed', 'canceled'].includes(jobState?.status));
            const isCurrent = activeStep === s.step;
            const isUnlocked = s.step === 1 || (s.step <= 3 && uploadedInfo) || (s.step === 4 && activeJobId);

            return (
              <button
                key={s.step}
                type="button"
                disabled={!isUnlocked}
                onClick={() => handleStepClick(s.step)}
                className={`flex items-center justify-center gap-2 px-3 rounded-lg text-xs sm:text-sm font-semibold transition-all h-full ${
                  isCurrent
                    ? 'bg-teal-50 dark:bg-teal-950/60 text-teal-800 dark:text-teal-200 border border-teal-300 dark:border-teal-700 shadow-2xs'
                    : isCompleted
                    ? 'bg-emerald-50/50 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-850 cursor-pointer'
                    : isUnlocked
                    ? 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer'
                    : 'opacity-40 text-slate-400 cursor-not-allowed'
                }`}
              >
                <span
                  className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                    isCurrent
                      ? 'bg-teal-600 text-white'
                      : isCompleted
                      ? 'bg-emerald-500 text-white'
                      : 'bg-slate-200 dark:bg-slate-800 text-slate-600 dark:text-slate-400'
                  }`}
                >
                  {isCompleted ? <Check className="w-3.5 h-3.5 stroke-[3]" /> : s.step}
                </span>
                <span className="truncate">{s.title}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Step 1: File Upload & Preset Selection */}
      {activeStep === 1 ? (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2.5">
              <span className="w-6 h-6 rounded-full bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 text-xs font-bold flex items-center justify-center">
                1
              </span>
              <CardTitle className="text-base sm:text-lg font-bold">CSV Data Source</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Row with Preset on left and Dropzone on right */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 items-stretch">
              {/* Preset Selector */}
              <div className="p-4 bg-slate-50 dark:bg-slate-850/60 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col justify-between min-h-[130px]">
                <label
                  htmlFor="smartcare-preset-select"
                  className="text-sm font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2"
                >
                  <FileSpreadsheet className="w-4 h-4 text-teal-600 dark:text-teal-400" />
                  <span>Preset Server File</span>
                </label>
                <select
                  id="smartcare-preset-select"
                  aria-label="Select Available File"
                  value={uploadedInfo?.filepath || ''}
                  onChange={(e) => handleSelectPresetFile(e.target.value)}
                  className="h-10 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 py-2 px-3 font-medium text-slate-800 dark:text-slate-200 w-full focus:outline-hidden focus:ring-2 focus:ring-teal-500 shadow-xs"
                >
                  <option value="">-- Choose preset CSV --</option>
                  {availableFiles.map((f) => (
                    <option key={f.filepath} value={f.filepath}>
                      {f.filename} ({Number(f.total_rows || 0).toLocaleString()} rows)
                    </option>
                  ))}
                </select>
              </div>

              {/* Dropzone on the right */}
              <FileDropzone
                accept=".csv"
                file={file}
                onFileSelect={handleFileUpload}
              />
            </div>

            {uploading && (
              <div className="text-xs text-teal-600 flex items-center gap-2 justify-center py-1">
                <div className="w-3.5 h-3.5 border-2 border-teal-600 border-t-transparent rounded-full animate-spin"></div>
                <span>Uploading and verifying CSV...</span>
              </div>
            )}

            {uploadError && <Alert variant="error" description={uploadError} />}

            {uploadedInfo && (
              <div className="p-2.5 bg-emerald-50/70 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-xl text-xs text-emerald-900 dark:text-emerald-300 flex items-center justify-between gap-3 shadow-2xs">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <span className="font-semibold">{uploadedInfo.filename} ({Number(uploadedInfo.total_rows || 0).toLocaleString()} records)</span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        /* Collapsed Step 1 Summary */
        <div className="p-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-2xs flex items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
            <Check className="w-4 h-4 text-emerald-600" />
            <span className="font-semibold">Step 1:</span>
            <span>{uploadedInfo?.filename || 'CSV loaded'} ({Number(uploadedInfo?.total_rows || 0).toLocaleString()} records)</span>
          </div>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setActiveStep(1)}
            icon={<RotateCcw className="w-3 h-3" />}
          >
            Change
          </Button>
        </div>
      )}

      {/* Step 2: Configuration & Dry-Run Validation Panel */}
      {!uploadedInfo ? (
        /* Locked Step 2 Placeholder */
        <div className="p-4 bg-slate-50/50 dark:bg-slate-850/30 border border-slate-200/60 dark:border-slate-800/60 rounded-xl flex items-center justify-between gap-4 opacity-60">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-800 text-slate-400 flex items-center justify-center text-xs font-bold shrink-0">
              2
            </div>
            <div>
              <div className="text-sm font-bold text-slate-600 dark:text-slate-400">
                Step 2: Migration Configuration & Dry-Run Audit
              </div>
              <div className="text-xs text-slate-400">
                Select or upload a CSV file in Step 1 to unlock configuration and validation.
              </div>
            </div>
          </div>
          <span className="text-xs text-slate-400 flex items-center gap-1 font-medium">
            <Lock className="w-3.5 h-3.5" /> Locked
          </span>
        </div>
      ) : activeStep !== 2 ? (
        /* Collapsed Step 2 Summary */
        <div className="p-4 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xs flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-full ${dryRunResult ? 'bg-emerald-500 text-white' : 'bg-teal-600 text-white'} flex items-center justify-center text-xs font-bold shrink-0`}>
              {dryRunResult ? <Check className="w-4 h-4 stroke-[3]" /> : '2'}
            </div>
            <div>
              <div className="text-sm font-bold text-slate-800 dark:text-slate-200">
                Step 2: Configuration & Audit
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                {dryRunResult
                  ? `Audited: ${(dryRunResult.summary?.valid_records ?? 0).toLocaleString()} valid records • Batch limit: ${rowLimit ? `${rowLimit} rows` : 'Full dataset'}`
                  : `Configured: ${rowLimit ? `${rowLimit} rows limit` : 'Full dataset'} • UUID: ${includeLegacyId ? 'Enabled' : 'Disabled'}`}
              </div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setActiveStep(2)}
          >
            Edit Configuration
          </Button>
        </div>
      ) : (
        /* Full Step 2 Card */
        <Card>
          <CardHeader>
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <span className="w-6 h-6 rounded-full bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 text-xs font-bold flex items-center justify-center">
                  2
                </span>
                Migration Configuration & Dry-Run Audit
              </CardTitle>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Audits Luhn MRN, 36-char UUID normalization & OpenMRS payload
              </span>
            </div>
            <CardDescription>
              Specify testing limits, optional facility location overrides, and execute a non-destructive dry-run.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Aligned 3-Column Controls Grid (Requirement E9: Align Legacy UUID label/toggle with other 2 columns) */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {/* Row Limit */}
              <div className="p-3.5 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col justify-between shadow-xs">
                <label
                  htmlFor="smartcare-limit-select"
                  className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 block"
                >
                  Row Limit for Testing
                </label>
                <div className="mt-2.5">
                  <select
                    id="smartcare-limit-select"
                    aria-label="Row Limit for Testing"
                    value={rowLimit}
                    onChange={(e) => setRowLimit(e.target.value)}
                    className="w-full h-10 text-sm rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500 shadow-xs"
                  >
                    <option value="10">First 10 rows (Fast test)</option>
                    <option value="100">First 100 rows</option>
                    <option value="500">First 500 rows (Standard)</option>
                    <option value="2000">First 2,000 rows</option>
                    <option value="">All rows (Full dataset)</option>
                  </select>
                </div>
              </div>

              {/* Target System (OpenMRS 3.x Vault) */}
              <div className="p-3.5 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col justify-between shadow-xs">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    Target System
                  </span>
                  <StatusBadge status={isTestingOpenmrs ? 'testing' : (openmrsSystem?.state || 'unknown')} size="xs" />
                </div>
                <div className="mt-2.5 flex items-center justify-between h-10">
                  <div className="min-w-0 pr-2">
                    <div className="text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                      <Server className="w-3.5 h-3.5 text-teal-600 dark:text-teal-400 shrink-0" />
                      <span className="truncate">OpenMRS 3.x Vault</span>
                    </div>
                    <div className="text-[11px] font-mono text-slate-400 truncate" title={openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}>
                      {openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}
                    </div>
                  </div>
                  {openmrsSystem?.latencyMs != null && (
                    <span className="text-xs font-sans tabular-nums text-slate-500 shrink-0">
                      {openmrsSystem.latencyMs}ms
                    </span>
                  )}
                </div>
              </div>

              {/* Include Legacy UUID */}
              <div className="p-3.5 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 flex flex-col justify-between shadow-xs">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    Legacy UUID Identifier
                  </span>
                  <Badge variant={includeLegacyId ? 'primary' : 'neutral'} size="xs">
                    {includeLegacyId ? 'Enabled' : 'Disabled'}
                  </Badge>
                </div>
                <div className="mt-2.5 flex items-center justify-between h-10">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                    Attach Legacy GUID
                  </span>
                  <Switch
                    id="include-legacy-id-switch"
                    checked={includeLegacyId}
                    onChange={setIncludeLegacyId}
                  />
                </div>
              </div>
            </div>

            {/* Core SmartCare to OpenMRS 3.x Field Mappings */}
            <div className="p-4 bg-slate-50/90 dark:bg-slate-850/80 rounded-xl border border-slate-200 dark:border-slate-800 space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-200 dark:border-slate-700/60 pb-3">
                <div>
                  <div className="font-bold text-sm text-slate-800 dark:text-slate-100 flex items-center gap-2">
                    <Server className="w-4 h-4 text-teal-600 dark:text-teal-400" />
                    <span>OpenMRS 3.x Patient Registration Field Mappings</span>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                    Target fields correspond directly to OpenMRS 3.x registration parts. Select which column from the uploaded SmartCare dataset syncs into each OpenMRS 3 field.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => detectInitialMappings(uploadedHeaders)}
                    icon={<RotateCcw className="w-3 h-3" />}
                  >
                    Auto-Detect Columns
                  </Button>
                </div>
              </div>

              {/* OpenMRS 3 Registration Fields Grid */}
              <div className="space-y-4">
                {/* Part 1: Basic Info (Demographics & Identifiers) */}
                <div>
                  <div className="text-xs font-bold text-teal-800 dark:text-teal-300 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                    <User className="w-3.5 h-3.5" />
                    <span>1. Basic Info (Demographics & Identifiers)</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    {/* Primary Identifier (MRN) */}
                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                          Primary Identifier (MRN)
                          <span className="text-rose-500">*</span>
                        </label>
                        <Badge variant="primary" size="xs">Luhn Check Digit</Badge>
                      </div>
                      <select
                        value={fieldMappings.patient_id}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, patient_id: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- Select Uploaded Column --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    {/* Secondary / Legacy Identifier */}
                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200">
                          Legacy Identifier (Legacy ID)
                        </label>
                        <Badge variant="neutral" size="xs">Optional</Badge>
                      </div>
                      <select
                        value={fieldMappings.patient_guid}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, patient_guid: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    {/* Gender / Sex */}
                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                        Gender / Sex
                        <span className="text-rose-500">*</span>
                      </label>
                      <select
                        value={fieldMappings.gender}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, gender: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- Select Uploaded Column --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Name Fields */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3">
                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                        Given Name (First Name)
                        <span className="text-rose-500">*</span>
                      </label>
                      <select
                        value={fieldMappings.given_name}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, given_name: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- Select Uploaded Column --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <label className="text-xs font-bold text-slate-800 dark:text-slate-200">
                        Middle Name
                      </label>
                      <select
                        value={fieldMappings.middle_name}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, middle_name: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                        Family Name (Last Name)
                        <span className="text-rose-500">*</span>
                      </label>
                      <select
                        value={fieldMappings.family_name}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, family_name: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- Select Uploaded Column --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>

                {/* Part 2: OpenMRS 3 Date of Birth (DOB) Field Mapping */}
                <div className="p-3.5 bg-white dark:bg-slate-900 rounded-xl border border-teal-200/80 dark:border-teal-900/60 space-y-3">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-100 dark:border-slate-800 pb-2">
                    <label className="text-xs font-bold text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                      <Calendar className="w-4 h-4 text-teal-600 dark:text-teal-400" />
                      <span>Date of Birth</span>
                      <span className="text-rose-500">*</span>
                    </label>

                    {/* Mode Toggle Pills */}
                    <div className="flex items-center gap-1 bg-slate-100 dark:bg-slate-800 p-1 rounded-lg">
                      <button
                        type="button"
                        onClick={() => setFieldMappings((prev) => ({ ...prev, birthdate_mode: 'all_in_one' }))}
                        className={`px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                          fieldMappings.birthdate_mode === 'all_in_one'
                            ? 'bg-teal-600 text-white shadow-xs'
                            : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
                        }`}
                      >
                        Single Date Column
                      </button>
                      <button
                        type="button"
                        onClick={() => setFieldMappings((prev) => ({ ...prev, birthdate_mode: 'separate' }))}
                        className={`px-2.5 py-1 text-xs font-bold rounded-md transition-all ${
                          fieldMappings.birthdate_mode === 'separate'
                            ? 'bg-teal-600 text-white shadow-xs'
                            : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
                        }`}
                      >
                        Separately (Day, Month, Year)
                      </button>
                    </div>
                  </div>

                  {fieldMappings.birthdate_mode === 'all_in_one' ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                      <div className="space-y-1">
                        <label className="text-xs font-bold text-slate-700 dark:text-slate-300 block">
                          Date of Birth Column: <span className="text-rose-500">*</span>
                        </label>
                        <select
                          value={fieldMappings.birthdate}
                          onChange={(e) => setFieldMappings((prev) => ({ ...prev, birthdate: e.target.value }))}
                          className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="">-- Select Uploaded Column --</option>
                          {uploadedHeaders.map((col) => (
                            <option key={col} value={col}>{col}</option>
                          ))}
                        </select>
                      </div>

                      <div className="space-y-1">
                        <label className="text-xs font-bold text-slate-700 dark:text-slate-300 block">
                          Age at Registration / Enrollment:
                        </label>
                        <select
                          value={fieldMappings.age_enrollment}
                          onChange={(e) => setFieldMappings((prev) => ({ ...prev, age_enrollment: e.target.value }))}
                          className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                        >
                          <option value="">-- (Optional / None) --</option>
                          {uploadedHeaders.map((col) => (
                            <option key={col} value={col}>{col}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3 pt-1">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-700 dark:text-slate-300 block">
                            Birth Year Column: <span className="text-rose-500">*</span>
                          </label>
                          <select
                            value={fieldMappings.birth_year}
                            onChange={(e) => setFieldMappings((prev) => ({ ...prev, birth_year: e.target.value }))}
                            className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                          >
                            <option value="">-- Select Uploaded Column --</option>
                            {uploadedHeaders.map((col) => (
                              <option key={col} value={col}>{col}</option>
                            ))}
                          </select>
                        </div>

                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-700 dark:text-slate-300 block">
                            Birth Month Column:
                          </label>
                          <select
                            value={fieldMappings.birth_month}
                            onChange={(e) => setFieldMappings((prev) => ({ ...prev, birth_month: e.target.value }))}
                            className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                          >
                            <option value="">-- Select Uploaded Column --</option>
                            {uploadedHeaders.map((col) => (
                              <option key={col} value={col}>{col}</option>
                            ))}
                          </select>
                        </div>

                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-700 dark:text-slate-300 block">
                            Birth Day Column:
                          </label>
                          <select
                            value={fieldMappings.birth_day}
                            onChange={(e) => setFieldMappings((prev) => ({ ...prev, birth_day: e.target.value }))}
                            className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                          >
                            <option value="">-- Select Uploaded Column --</option>
                            {uploadedHeaders.map((col) => (
                              <option key={col} value={col}>{col}</option>
                            ))}
                          </select>
                        </div>
                      </div>

                      <div className="pt-1">
                        <div className="space-y-1">
                          <label className="text-xs font-bold text-slate-700 dark:text-slate-300 block">
                            Age at Registration / Enrollment (Fallback):
                          </label>
                          <select
                            value={fieldMappings.age_enrollment}
                            onChange={(e) => setFieldMappings((prev) => ({ ...prev, age_enrollment: e.target.value }))}
                            className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                          >
                            <option value="">-- (Optional / None) --</option>
                            {uploadedHeaders.map((col) => (
                              <option key={col} value={col}>{col}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Part 3: OpenMRS 3 Contact Details (Phone & Address Hierarchy) */}
                <div>
                  <div className="text-xs font-bold text-teal-800 dark:text-teal-300 uppercase tracking-wider mb-2.5 flex items-center gap-1.5">
                    <Phone className="w-3.5 h-3.5" />
                    <span>2. Contact Details (Phone & Address)</span>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200">
                          Phone Number
                        </label>
                        <Badge variant="neutral" size="xs">Attribute</Badge>
                      </div>
                      <select
                        value={fieldMappings.phone}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, phone: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                          <MapPin className="w-3.5 h-3.5 text-teal-600" />
                          Woreda (City / Village)
                        </label>
                        <Badge variant="neutral" size="xs">Address</Badge>
                      </div>
                      <select
                        value={fieldMappings.woreda}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, woreda: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                          <MapPin className="w-3.5 h-3.5 text-teal-600" />
                          Zone (County / District)
                        </label>
                        <Badge variant="neutral" size="xs">Address</Badge>
                      </div>
                      <select
                        value={fieldMappings.zone}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, zone: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                          <MapPin className="w-3.5 h-3.5 text-teal-600" />
                          Region (State / Province)
                        </label>
                        <Badge variant="neutral" size="xs">Address</Badge>
                      </div>
                      <select
                        value={fieldMappings.region}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, region: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                          <MapPin className="w-3.5 h-3.5 text-teal-600" />
                          Kebele (Address 3)
                        </label>
                        <Badge variant="neutral" size="xs">Address</Badge>
                      </div>
                      <select
                        value={fieldMappings.kebele}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, kebele: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>

                    <div className="p-3 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1">
                          <MapPin className="w-3.5 h-3.5 text-teal-600" />
                          House Number (Address 1)
                        </label>
                        <Badge variant="neutral" size="xs">Address</Badge>
                      </div>
                      <select
                        value={fieldMappings.house_number}
                        onChange={(e) => setFieldMappings((prev) => ({ ...prev, house_number: e.target.value }))}
                        className="w-full h-9 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 font-medium text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-teal-500"
                      >
                        <option value="">-- (Optional / None) --</option>
                        {uploadedHeaders.map((col) => (
                          <option key={col} value={col}>{col}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Step 2 Action Controls */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="secondary"
                size="sm"
                onClick={handleClearFile}
                icon={<RotateCcw className="w-3.5 h-3.5" />}
              >
                Clear / Change File
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={runDryRun}
                disabled={!uploadedInfo || dryRunRunning || importing}
                icon={<Zap className="w-3.5 h-3.5 text-amber-500" />}
              >
                {dryRunRunning ? 'Auditing...' : 'Run Dry Run Audit'}
              </Button>
            </div>

            {dryRunError && <Alert variant="error" description={dryRunError} />}

            {/* Dry Run Results & Visual Tabs */}
            {dryRunResult && (
              <div className="space-y-5 pt-2">
                <div className="p-3.5 bg-emerald-50/80 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded-xl flex items-center justify-between gap-3 shadow-xs">
                  <div className="flex items-center gap-2.5">
                    <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 shrink-0" />
                    <div>
                      <div className="font-bold text-sm text-emerald-900 dark:text-emerald-200">
                        Audit Ready: {(dryRunResult.summary?.valid_records ?? 0).toLocaleString()} valid patient records ready for OpenMRS 3.x
                      </div>
                      <div className="text-xs text-emerald-700 dark:text-emerald-400 mt-0.5">
                        Target: <span className="font-mono font-semibold">{openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}</span> • Proceed to Step 3 to review scope and execute live migration.
                      </div>
                    </div>
                  </div>
                </div>

                {/* Metric Stat Cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  <div className="p-3.5 bg-slate-50 dark:bg-slate-800/60 rounded-xl border border-slate-200 dark:border-slate-700 text-center">
                    <div className="text-[11px] text-slate-500 font-medium">Audited Records</div>
                    <div className="text-2xl font-bold text-slate-800 dark:text-slate-100 mt-1 tabular-nums">
                      {(dryRunResult.summary?.total_records ?? dryRunResult.summary?.total_rows ?? 0).toLocaleString()}
                    </div>
                  </div>

                  <div className="p-3.5 bg-emerald-50 dark:bg-emerald-950/40 rounded-xl border border-emerald-200 dark:border-emerald-800 text-center">
                    <div className="text-[11px] text-emerald-700 dark:text-emerald-300 font-semibold">Valid for Import</div>
                    <div className="text-2xl font-bold text-emerald-800 dark:text-emerald-200 mt-1 tabular-nums">
                      {(dryRunResult.summary?.valid_records ?? 0).toLocaleString()}
                    </div>
                  </div>

                  <div className="p-3.5 bg-amber-50 dark:bg-amber-950/40 rounded-xl border border-amber-200 dark:border-amber-800 text-center">
                    <div className="text-[11px] text-amber-700 dark:text-amber-300 font-semibold">Warnings / Flags</div>
                    <div className="text-2xl font-bold text-amber-800 dark:text-amber-200 mt-1 tabular-nums">
                      {(dryRunResult.summary?.warnings_count ?? dryRunResult.summary?.warnings ?? 0).toLocaleString()}
                    </div>
                  </div>

                  <div className="p-3.5 bg-rose-50 dark:bg-rose-950/40 rounded-xl border border-rose-200 dark:border-rose-800 text-center">
                    <div className="text-[11px] text-rose-700 dark:text-rose-300 font-semibold">Invalid Records</div>
                    <div className="text-2xl font-bold text-rose-800 dark:text-rose-200 mt-1 tabular-nums">
                      {(dryRunResult.summary?.invalid_records ?? dryRunResult.summary?.errors ?? 0).toLocaleString()}
                    </div>
                  </div>
                </div>

                {/* Tab Navigation */}
                <div className="border-b border-slate-200 dark:border-slate-800">
                  <Tabs
                    items={[
                      {
                        id: 'preview',
                        label: 'Records Preview',
                        icon: <FileText className="w-3.5 h-3.5" />,
                        count: dryRunResult.sample_records?.length || 0,
                      },
                      {
                        id: 'issues',
                        label: 'Issues & Warnings',
                        icon: <AlertTriangle className="w-3.5 h-3.5" />,
                        count: dryRunResult.issues?.length || 0,
                      },
                      {
                        id: 'payload',
                        label: 'OpenMRS REST Payload',
                        icon: <Code className="w-3.5 h-3.5" />,
                      },
                    ]}
                    activeId={activeTab}
                    onChange={setActiveTab}
                    variant="underline"
                    size="sm"
                  />
                </div>

                {/* Tab 1: Records Preview Table */}
                {activeTab === 'preview' && (
                  <div className="border border-slate-200 dark:border-slate-800 rounded-xl overflow-x-auto shadow-xs">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-50 dark:bg-slate-850 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 uppercase text-[10px] tracking-wider">
                        <tr>
                          <th className="p-2.5 text-center w-12">Row</th>
                          <th className="p-2.5">MRN (Luhn)</th>
                          <th className="p-2.5">Patient Name</th>
                          <th className="p-2.5 text-center">Gender</th>
                          <th className="p-2.5">Birthdate</th>
                          <th className="p-2.5">OpenMRS UUID</th>
                          <th className="p-2.5">OpenMRS Contact</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800 font-mono">
                        {(!dryRunResult.sample_records || dryRunResult.sample_records.length === 0) ? (
                          <tr>
                            <td colSpan={7} className="py-6 text-center text-slate-400 font-sans">
                              No sample preview records available.
                            </td>
                          </tr>
                        ) : (
                          dryRunResult.sample_records.map((s) => {
                            const meta = s.meta || {};
                            return (
                              <tr key={s.row_num} className="hover:bg-slate-50/80 dark:hover:bg-slate-850/50">
                                <td className="p-2.5 text-center text-slate-400 font-sans">{s.row_num}</td>
                                <td className="p-2.5 font-bold text-teal-700 dark:text-teal-300">
                                  {meta.formatted_mrn || 'N/A'}
                                </td>
                                <td className="p-2.5 font-sans font-semibold text-slate-800 dark:text-slate-200">
                                  {meta.full_name || 'Unknown'}
                                </td>
                                <td className="p-2.5 text-center">
                                  <span
                                    className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                      meta.gender === 'M'
                                        ? 'bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300'
                                        : 'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300'
                                    }`}
                                  >
                                    {meta.gender}
                                  </span>
                                </td>
                                <td className="p-2.5 text-slate-600 dark:text-slate-400">
                                  {meta.birthdate || 'N/A'}
                                  {meta.birthdate_estimated && (
                                    <span className="ml-1 text-[10px] text-amber-500 font-sans font-normal">(est)</span>
                                  )}
                                </td>
                                <td className="p-2.5 text-[11px] text-slate-500 truncate max-w-[190px]" title={meta.canonical_uuid}>
                                  {meta.canonical_uuid || 'N/A'}
                                </td>
                                <td className="p-2.5 font-sans text-xs text-slate-600 dark:text-slate-400 truncate max-w-[220px]">
                                  {meta.address || meta.phone || '—'}
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Tab 2: Issues & Warnings */}
                {activeTab === 'issues' && (
                  <div className="space-y-2">
                    {(!dryRunResult.issues || dryRunResult.issues.length === 0) ? (
                      <div className="p-6 text-center text-emerald-600 dark:text-emerald-400 bg-emerald-50/40 dark:bg-emerald-950/20 rounded-xl border border-emerald-200 dark:border-emerald-800 text-xs">
                        <CheckCircle2 className="w-6 h-6 mx-auto mb-2 text-emerald-500" />
                        No validation issues or schema errors detected across audited records!
                      </div>
                    ) : (
                      <div className="max-h-60 overflow-y-auto space-y-1.5 divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-xl p-3 bg-slate-50/50 dark:bg-slate-900 font-mono text-xs">
                        {dryRunResult.issues.map((issue, idx) => (
                          <div key={idx} className="pt-1.5 first:pt-0 flex items-start gap-2 text-amber-700 dark:text-amber-400">
                            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-500" />
                            <span>{issue}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Tab 3: OpenMRS REST Payload */}
                {activeTab === 'payload' && (
                  <div className="space-y-2">
                    <div className="text-[11px] text-slate-500 flex items-center justify-between">
                      <span>Target endpoint: <code className="font-mono text-teal-600">POST /ws/rest/v1/patient</code></span>
                      <span>Sample row 1 registration payload</span>
                    </div>
                    <div className="p-3 bg-slate-900 rounded-xl border border-slate-800 overflow-x-auto text-[11px] font-mono text-teal-300 max-h-72">
                      <pre>
                        {JSON.stringify(
                          dryRunResult.sample_transformed ||
                            dryRunResult.sample_records?.[0]?.openmrs_payload ||
                            {},
                          null,
                          2
                        )}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Step 3: Target System Confirmation & Import Scope */}
      {!uploadedInfo ? (
        /* Locked Step 3 Placeholder */
        <div className="p-4 bg-slate-50/50 dark:bg-slate-850/30 border border-slate-200/60 dark:border-slate-800/60 rounded-xl flex items-center justify-between gap-4 opacity-60">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-800 text-slate-400 flex items-center justify-center text-xs font-bold shrink-0">
              3
            </div>
            <div>
              <div className="text-sm font-bold text-slate-600 dark:text-slate-400">
                Step 3: Target System Confirmation & Scope
              </div>
              <div className="text-xs text-slate-400">
                Complete Step 1 and Step 2 to review target settings and confirm live migration.
              </div>
            </div>
          </div>
          <span className="text-xs text-slate-400 flex items-center gap-1 font-medium">
            <Lock className="w-3.5 h-3.5" /> Locked
          </span>
        </div>
      ) : activeStep !== 3 ? (
        /* Collapsed Step 3 Summary */
        <div className="p-4 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xs flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-full ${activeJobId ? 'bg-emerald-500 text-white' : 'bg-teal-600 text-white'} flex items-center justify-center text-xs font-bold shrink-0`}>
              {activeJobId ? <Check className="w-4 h-4 stroke-[3]" /> : '3'}
            </div>
            <div>
              <div className="text-sm font-bold text-slate-800 dark:text-slate-200">
                Step 3: Target System Confirmation & Scope
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">
                Target: OpenMRS 3.x ({openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}) • {Number(dryRunResult?.summary?.valid_records ?? (rowLimit || uploadedInfo?.total_rows || 0)).toLocaleString()} records
              </div>
            </div>
          </div>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setActiveStep(3)}
          >
            Review Scope
          </Button>
        </div>
      ) : (
        /* Full Step 3 Card */
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base">
                <span className="w-6 h-6 rounded-full bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 text-xs font-bold flex items-center justify-center">
                  3
                </span>
                Target System Confirmation & Import Scope
              </CardTitle>
              {dryRunResult ? (
                <Badge variant="success">Audit Complete & Verified</Badge>
              ) : (
                <Badge variant="neutral">Ready to Import</Badge>
              )}
            </div>
            <CardDescription>
              Review the migration destination and validated record count before initiating live execution.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="p-4 bg-teal-50/50 dark:bg-teal-950/30 rounded-xl border border-teal-200 dark:border-teal-800 space-y-3 shadow-xs">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-teal-200/60 dark:border-teal-800/60 pb-3">
                <div>
                  <div className="text-sm font-bold text-slate-900 dark:text-slate-100">
                    Ready to migrate {Number(dryRunResult?.summary?.valid_records ?? (rowLimit || uploadedInfo?.total_rows || 0)).toLocaleString()} patient records
                  </div>
                  <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                    Source File: <span className="font-mono font-semibold">{uploadedInfo?.filename}</span>
                  </div>
                </div>
                <div className="text-left sm:text-right">
                  <div className="text-xs font-semibold text-teal-800 dark:text-teal-200 flex items-center sm:justify-end gap-1.5">
                    <span>Target: OpenMRS 3.x</span>
                    <StatusBadge status={isTestingOpenmrs ? 'testing' : (openmrsSystem?.state || 'unknown')} size="xs" />
                  </div>
                  <div className="text-[11px] font-mono text-slate-500 mt-0.5">
                    {openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs text-slate-700 dark:text-slate-300">
                <div>
                  <span className="text-slate-400 block text-[10px]">TARGET SYSTEM</span>
                  <span className="font-semibold text-teal-700 dark:text-teal-300">OpenMRS 3.x Vault</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px]">DOB FORMAT</span>
                  <span className="font-semibold">
                    {fieldMappings.birthdate_mode === 'all_in_one' ? 'Single Date Column' : 'Separate Day/Month/Year'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px]">LEGACY IDENTIFIER</span>
                  <span className="font-semibold">{includeLegacyId ? 'Enabled (GUID)' : 'Disabled'}</span>
                </div>
                <div>
                  <span className="text-slate-400 block text-[10px]">BATCH LIMIT</span>
                  <span className="font-semibold">{rowLimit ? `${rowLimit} rows` : 'All rows (Full dataset)'}</span>
                </div>
              </div>

              <div className="flex items-center justify-center pt-3 border-t border-slate-100 dark:border-slate-800">
                <Button
                  variant="primary"
                  size="md"
                  onClick={() => setShowConfirmModal(true)}
                  disabled={!uploadedInfo || isViewer || importing || !openmrsSystem?.isConnected}
                  icon={<Play className="w-4 h-4 text-white mr-1.5" />}
                  className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                >
                  {importing ? 'Starting...' : 'Import to OpenMRS 3.x'}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Real-Time Execution & SSE Stream */}
      {!activeJobId ? (
        /* Locked Step 4 Placeholder */
        <div className="p-4 bg-slate-50/50 dark:bg-slate-850/30 border border-slate-200/60 dark:border-slate-800/60 rounded-xl flex items-center justify-between gap-4 opacity-60">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-800 text-slate-400 flex items-center justify-center text-xs font-bold shrink-0">
              4
            </div>
            <div>
              <div className="text-sm font-bold text-slate-600 dark:text-slate-400">
                Step 4: Real-Time Execution & SSE Stream
              </div>
              <div className="text-xs text-slate-400">
                Begins automatically when patient migration is initiated.
              </div>
            </div>
          </div>
          <span className="text-xs text-slate-400 flex items-center gap-1 font-medium">
            <Lock className="w-3.5 h-3.5" /> Locked
          </span>
        </div>
      ) : (
        /* Full Step 4 Card */
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2 text-base">
                <span className="w-6 h-6 rounded-full bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 text-xs font-bold flex items-center justify-center">
                  4
                </span>
                Real-Time Execution & SSE Stream
              </CardTitle>
              {jobState?.status && (
                <StatusBadge status={jobState.status} size="sm" />
              )}
            </div>
            <CardDescription>
              Monitors real-time OpenMRS REST calls, progress percent, and error logging.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <JobPanel
              jobId={activeJobId}
              jobState={jobState || { status: isStreaming ? 'running' : 'idle', progress: 0 }}
              logs={liveLogs}
              isStreaming={isStreaming}
              onCancel={handleCancelJob}
              onReset={() => {
                setActiveJobId(null);
                setJobState(null);
                setLiveLogs([]);
                setActiveStep(1);
              }}
            />
          </CardContent>
        </Card>
      )}

      {/* Sticky Wizard Footer Bar (Requirement E9) */}
      <div className="sticky bottom-4 z-20 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md border border-slate-200 dark:border-slate-800 rounded-xl p-3 sm:px-5 shadow-lg grid grid-cols-1 sm:grid-cols-3 items-center gap-3">
        <div className="flex items-center gap-3 justify-start">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setActiveStep((prev) => Math.max(1, prev - 1))}
            disabled={activeStep === 1 || importing}
            icon={<ArrowLeft className="w-3.5 h-3.5" />}
          >
            Back
          </Button>
        </div>

        <div className="flex items-center justify-center gap-2">
          {activeStep === 1 && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setActiveStep(2)}
              disabled={!uploadedInfo}
              icon={<ArrowRight className="w-3.5 h-3.5" />}
            >
              Next: Configure & Audit
            </Button>
          )}

          {activeStep === 2 && (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={runDryRun}
                disabled={!uploadedInfo || dryRunRunning || importing}
                icon={<Zap className="w-3.5 h-3.5 text-amber-500" />}
              >
                {dryRunRunning ? 'Auditing...' : 'Run Dry Run'}
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={() => setActiveStep(3)}
                disabled={!uploadedInfo}
                icon={<ArrowRight className="w-3.5 h-3.5" />}
              >
                Next: Confirm Scope
              </Button>
            </>
          )}

          {activeStep === 3 && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowConfirmModal(true)}
              disabled={!uploadedInfo || isViewer || importing || !openmrsSystem?.isConnected}
              icon={<Play className="w-3.5 h-3.5 text-white" />}
              className="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
            >
              {importing ? 'Starting...' : 'Import to OpenMRS 3.x'}
            </Button>
          )}

          {activeStep === 4 && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setActiveStep(1);
                setActiveJobId(null);
                setJobState(null);
                setLiveLogs([]);
              }}
              icon={<RotateCcw className="w-3.5 h-3.5" />}
            >
              New Migration
            </Button>
          )}
        </div>

        <div className="hidden sm:flex items-center justify-end">
          <span className="text-xs text-slate-500 dark:text-slate-400 font-medium">
            Step {activeStep} of 4: {['CSV Data Source', 'Configure & Audit', 'Target & Scope Confirmation', 'Live Migration'][activeStep - 1]}
          </span>
        </div>
      </div>

      {/* Confirmation Dialog with targetSystem='openmrs' */}
      <ConfirmDialog
        open={showConfirmModal}
        targetSystem="openmrs"
        title="Confirm Live Patient Migration"
        message={`You are about to migrate ${Number(dryRunResult?.summary?.valid_records ?? (rowLimit || uploadedInfo?.total_rows || 0)).toLocaleString()} patient records from ${uploadedInfo?.filename || 'file'} into OpenMRS 3.x (${openmrsSystem?.effectiveUrl || 'http://host.docker.internal/openmrs'}). This creates live patient entities with MRNs (\\d{6}-\\d Luhn check digits).`}
        confirmLabel="Confirm & Start Migration"
        variant="primary"
        onConfirm={handleStartImport}
        onCancel={() => setShowConfirmModal(false)}
      />
    </div>
  );
};

export default SmartcarePage;
