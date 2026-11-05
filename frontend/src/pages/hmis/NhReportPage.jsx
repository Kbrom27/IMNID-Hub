import React, { useState } from 'react';
import { FileSpreadsheet, Calendar, Upload, Database, BarChart3, CheckCircle2, Download } from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  TextInput,
  Select,
  Checkbox,
  JobPanel,
  FileDropzone,
  ConfirmDialog,
  Alert,
} from '../../ui';
import { useAuth } from '../../context/AuthContext';
import { useHmisJob } from './useHmisJob';

const ETH_MONTHS = [
  { val: 1, name: 'Meskerem (Sep - Oct)' },
  { val: 2, name: 'Tikimt (Oct - Nov)' },
  { val: 3, name: 'Hidar (Nov - Dec)' },
  { val: 4, name: 'Tahsas (Dec - Jan)' },
  { val: 5, name: 'Tir (Jan - Feb)' },
  { val: 6, name: 'Yakatit (Feb - Mar)' },
  { val: 7, name: 'Magabit (Mar - Apr)' },
  { val: 8, name: 'Miyazya (Apr - May)' },
  { val: 9, name: 'Ginbot (May - Jun)' },
  { val: 10, name: 'Sene (Jun - Jul)' },
  { val: 11, name: 'Hamle (Jul - Aug)' },
  { val: 12, name: 'Nehase (Aug - Sep)' },
  { val: 13, name: 'Pagumen (Sep)' },
];

/**
 * NH (HMIS 04.2) Neonatal Health & NICU Register Page
 * Generates authoritative NICU registers and calculates monthly aggregate neonatal indicators.
 */
const NhReportPage = () => {
  const { isViewer } = useAuth();
  const {
    ethYear,
    ethMonth,
    calendarInfo,
    handleYearMonthChange,
    handleFileUpload,
    activeJobId,
    jobState,
    liveLogs,
    isStreaming,
    outputArtifacts,
    computedIndicators,
    handleSubmitJob,
    handleCancelJob,
    resetJob,
  } = useHmisJob();

  const [subTab, setSubTab] = useState('csv'); // 'csv', 'dhis2', 'aggregate'
  const [csvFile, setCsvFile] = useState(null);
  const [csvFilePath, setCsvFilePath] = useState('');
  const [region, setRegion] = useState('');
  const [facility, setFacility] = useState('');
  const [sheetPerFacility, setSheetPerFacility] = useState(false);
  const [startDate, setStartDate] = useState(calendarInfo?.gregorian_start || '');
  const [endDate, setEndDate] = useState(calendarInfo?.gregorian_end || '');
  const [programUid, setProgramUid] = useState('Neonatal Care Form');
  const [datasetUid, setDatasetUid] = useState('');
  const [period, setPeriod] = useState(calendarInfo?.period_code || '201702');
  const [dryRun, setDryRun] = useState(true);
  const [showConfirm, setShowConfirm] = useState(false);

  const handleFileChange = async (file) => {
    setCsvFile(file);
    if (file) {
      const path = await handleFileUpload(file);
      if (path) setCsvFilePath(path);
    } else {
      setCsvFilePath('');
    }
  };

  const handleRunCsvRegister = () => {
    handleSubmitJob('/api/hmis/nh/nicu-register-csv', {
      input_file: csvFilePath || (csvFile ? csvFile.name : ''),
      region: region || undefined,
      facility: facility || undefined,
      sheet_per_facility: sheetPerFacility,
      start: startDate || undefined,
      end: endDate || undefined,
    });
  };

  const handleRunDhis2Register = () => {
    handleSubmitJob('/api/hmis/nh/nicu-register-dhis2', {
      program_uid: programUid,
      start: startDate || undefined,
      end: endDate || undefined,
      ou_mode: 'DESCENDANTS',
      org_unit: facility || undefined,
      sheet_per_facility: sheetPerFacility,
    });
  };

  const handleRunAggregate = () => {
    setShowConfirm(false);
    handleSubmitJob('/api/hmis/nh/aggregate-report', {
      program_uid: programUid,
      org_unit: facility || undefined,
      period,
      start: startDate || undefined,
      end: endDate || undefined,
      dataset: datasetUid || undefined,
      dry_run: dryRun,
      submit: !dryRun,
    });
  };

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Neonatal Health & NICU Register (HMIS 04.2)"
        breadcrumbs={[
          { label: 'HMIS Reporting', href: '/hmis' },
          { label: 'NICU Register (04.2)' },
        ]}
      />

      {/* Ethiopian Calendar Banner Card */}
      <Card>
        <CardContent className="p-5 sm:p-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-blue-100 dark:bg-blue-950 text-blue-700 dark:text-blue-300">
              <Calendar className="w-5 h-5" />
            </div>
            <div>
              <span className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider block">
                Reporting Period (Ethiopian Calendar)
              </span>
              <span className="text-xs text-slate-500">
                Window: <code className="text-blue-600 font-semibold">{calendarInfo?.gregorian_start || '...'}</code> to{' '}
                <code className="text-blue-600 font-semibold">{calendarInfo?.gregorian_end || '...'}</code> (Period:{' '}
                {calendarInfo?.period_code || '...'})
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <label htmlFor="nh-eth-year" className="sr-only">Ethiopian Year</label>
            <select
              id="nh-eth-year"
              aria-label="Ethiopian Year"
              value={ethYear}
              onChange={(e) => handleYearMonthChange(Number(e.target.value), ethMonth)}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
            >
              {[2015, 2016, 2017, 2018, 2019].map((y) => (
                <option key={y} value={y}>
                  {y} E.C.
                </option>
              ))}
            </select>
            <label htmlFor="nh-eth-month" className="sr-only">Ethiopian Month</label>
            <select
              id="nh-eth-month"
              aria-label="Ethiopian Month"
              value={ethMonth}
              onChange={(e) => handleYearMonthChange(ethYear, Number(e.target.value))}
              className="text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900"
            >
              {ETH_MONTHS.map((m) => (
                <option key={m.val} value={m.val}>
                  {m.name}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      {/* Mode Subtabs */}
      <div className="flex border-b border-slate-200 dark:border-slate-800 gap-6">
        <button
          onClick={() => setSubTab('csv')}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
            subTab === 'csv'
              ? 'border-blue-600 text-blue-600 dark:text-blue-400'
              : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
          }`}
        >
          <FileSpreadsheet className="w-4 h-4" />
          From CSV Export (HM-05)
        </button>
        <button
          onClick={() => setSubTab('dhis2')}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
            subTab === 'dhis2'
              ? 'border-blue-600 text-blue-600 dark:text-blue-400'
              : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
          }`}
        >
          <Database className="w-4 h-4" />
          From Live DHIS2 (HM-06)
        </button>
        <button
          onClick={() => setSubTab('aggregate')}
          className={`pb-3 text-sm font-semibold flex items-center gap-2 border-b-2 transition-colors ${
            subTab === 'aggregate'
              ? 'border-blue-600 text-blue-600 dark:text-blue-400'
              : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          Monthly Aggregate Indicators (HM-07)
        </button>
      </div>

      {/* Subtab 1: CSV */}
      {subTab === 'csv' && (
        <Card>
          <CardHeader>
            <CardTitle>Generate NICU Register from CSV</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <FileDropzone
              accept=".csv"
              maxSizeMb={50}
              file={csvFile}
              onFileSelect={handleFileChange}
              helperText="Upload CSV export of Neonatal Care Form"
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <TextInput
                label="Region Filter"
                placeholder="e.g. Oromia or Amhara"
                value={region}
                onChange={(e) => setRegion(e.target.value)}
              />
              <TextInput
                label="Facility Filter"
                placeholder="e.g. Asella Referral Hospital"
                value={facility}
                onChange={(e) => setFacility(e.target.value)}
              />
            </div>
            <Checkbox
              label="Generate separate Excel worksheet per facility"
              checked={sheetPerFacility}
              onChange={(e) => setSheetPerFacility(e.target.checked)}
            />
            <div className="flex justify-center pt-2">
              <Button
                variant="primary"
                onClick={handleRunCsvRegister}
                disabled={!csvFilePath || isStreaming || isViewer}
              >
                Generate 04.2 NICU Register
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Subtab 2: DHIS2 Live */}
      {subTab === 'dhis2' && (
        <Card>
          <CardHeader>
            <CardTitle>Generate NICU Register from Live DHIS2 Tracker</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <TextInput
                label="Neonatal Program UID or Name"
                value={programUid}
                onChange={(e) => setProgramUid(e.target.value)}
              />
              <TextInput
                label="Target Org Unit (Facility UID)"
                placeholder="Leave blank for entire hierarchy"
                value={facility}
                onChange={(e) => setFacility(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <TextInput
                type="date"
                label="Start Date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
              <TextInput
                type="date"
                label="End Date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <Checkbox
              label="Generate separate Excel worksheet per facility"
              checked={sheetPerFacility}
              onChange={(e) => setSheetPerFacility(e.target.checked)}
            />
            <div className="flex justify-center pt-2">
              <Button
                variant="primary"
                onClick={handleRunDhis2Register}
                disabled={isStreaming || isViewer}
              >
                Fetch & Build Live NICU Register
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Subtab 3: Aggregate */}
      {subTab === 'aggregate' && (
        <Card>
          <CardHeader>
            <CardTitle>04.2 NH Monthly Aggregate Indicators</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <TextInput
                label="Reporting Period (YYYYMM)"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              />
              <TextInput
                label="Facility Org Unit UID"
                placeholder="Target facility UID"
                value={facility}
                onChange={(e) => setFacility(e.target.value)}
              />
            </div>
            <TextInput
              label="Aggregate Dataset UID (04.2)"
              placeholder="e.g. ds042Uid..."
              value={datasetUid}
              onChange={(e) => setDatasetUid(e.target.value)}
            />
            <div className="p-3 bg-slate-50 dark:bg-slate-900 rounded-lg space-y-2">
              <span className="text-xs font-semibold text-slate-800 dark:text-slate-200 block">
                Execution Mode:
              </span>
              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="nh_dry_run"
                  checked={dryRun}
                  onChange={() => setDryRun(true)}
                  className="text-blue-600 focus:ring-blue-500"
                />
                <span>Dry Run</span>
              </label>
              <label className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="radio"
                  name="nh_dry_run"
                  checked={!dryRun}
                  onChange={() => setDryRun(false)}
                  className="text-blue-600 focus:ring-blue-500"
                />
                <span className="font-bold text-blue-600">
                  Live Submission
                </span>
              </label>
            </div>
            <div className="flex justify-center pt-2">
              <Button
                variant={dryRun ? 'primary' : 'danger'}
                onClick={() => (dryRun ? handleRunAggregate() : setShowConfirm(true))}
                disabled={isStreaming || isViewer}
              >
                {dryRun ? 'Calculate 04.2 Indicators' : 'Submit 04.2 Report to DHIS2'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Computed Indicators Result Display */}
      {computedIndicators && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-emerald-600" />
              Calculated 04.2 Indicators & Tallies
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
              {Object.entries(computedIndicators).map(([key, val]) => (
                <div
                  key={key}
                  className="p-3 rounded-lg bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800"
                >
                  <span className="text-[11px] font-medium text-slate-500 block truncate" title={key}>
                    {key}
                  </span>
                  <span className="text-lg font-bold text-blue-700 dark:text-blue-400">
                    {typeof val === 'number' ? val.toLocaleString() : String(val)}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Job Execution Panel */}
      <JobPanel
        jobId={activeJobId}
        status={jobState?.status || (isStreaming ? 'running' : 'idle')}
        progress={jobState?.progress || 0}
        logs={liveLogs}
        artifacts={outputArtifacts}
        onCancel={handleCancelJob}
        onReset={resetJob}
      />

      <ConfirmDialog
        open={showConfirm}
        targetSystem="dhis2_online"
        title="Confirm Live DHIS2 Submission"
        message="You are about to submit live aggregate data to DHIS2. This will overwrite existing data values for the selected facility and reporting period. Proceed?"
        confirmLabel="Submit to DHIS2"
        variant="danger"
        onConfirm={handleRunAggregate}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default NhReportPage;
