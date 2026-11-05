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
 * RMH (HMIS 01.2) Delivery Register Page
 * Generates authoritative Delivery registers and calculates monthly aggregate indicators.
 */
const RmhReportPage = () => {
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
  const [programUid, setProgramUid] = useState('Maternal Inpatient Data');
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
    handleSubmitJob('/api/hmis/rmh/delivery-register-csv', {
      input_file: csvFilePath || (csvFile ? csvFile.name : ''),
      region: region || undefined,
      facility: facility || undefined,
      sheet_per_facility: sheetPerFacility,
      start: startDate || undefined,
      end: endDate || undefined,
    });
  };

  const handleRunDhis2Register = () => {
    handleSubmitJob('/api/hmis/rmh/delivery-register-dhis2', {
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
    handleSubmitJob('/api/hmis/rmh/aggregate-report', {
      delivery_program: programUid,
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
        title="Routine Maternal Health Register (HMIS 01.2)"
        breadcrumbs={[
          { label: 'HMIS Reporting', href: '/hmis' },
          { label: 'RMH Register (01.2)' },
        ]}
      />

      {/* Ethiopian Calendar Banner Card */}
      <Card>
        <CardContent className="p-5 sm:p-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300">
              <Calendar className="w-5 h-5" />
            </div>
            <div>
              <span className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-wider block">
                Reporting Period (Ethiopian Calendar)
              </span>
              <span className="text-xs text-slate-500">
                {calendarInfo ? `${calendarInfo.gregorian_start} to ${calendarInfo.gregorian_end}` : 'Loading dates...'}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Select
              id="rmh-eth-year"
              aria-label="Ethiopian Year"
              value={ethYear}
              onChange={(e) => handleYearMonthChange(parseInt(e.target.value), ethMonth)}
              options={[2015, 2016, 2017, 2018].map((y) => ({ value: y, label: `Year ${y} E.C.` }))}
            />
            <Select
              id="rmh-eth-month"
              aria-label="Ethiopian Month"
              value={ethMonth}
              onChange={(e) => handleYearMonthChange(ethYear, parseInt(e.target.value))}
              options={ETH_MONTHS.map((m) => ({ value: m.val, label: `${m.val}. ${m.name}` }))}
            />
          </div>
        </CardContent>
      </Card>

      {/* Mode Sub-tabs */}
      <div className="flex border-b border-slate-200 dark:border-slate-800 gap-4 text-xs font-semibold">
        <button
          onClick={() => setSubTab('csv')}
          className={`pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors ${
            subTab === 'csv'
              ? 'border-emerald-600 text-emerald-700 dark:text-emerald-400'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <FileSpreadsheet className="w-4 h-4" />
          <span>Generate from CSV Extract</span>
        </button>
        <button
          onClick={() => setSubTab('dhis2')}
          className={`pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors ${
            subTab === 'dhis2'
              ? 'border-emerald-600 text-emerald-700 dark:text-emerald-400'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <Database className="w-4 h-4" />
          <span>Live DHIS2 Tracker Extract</span>
        </button>
        <button
          onClick={() => setSubTab('aggregate')}
          className={`pb-2.5 flex items-center gap-1.5 border-b-2 transition-colors ${
            subTab === 'aggregate'
              ? 'border-emerald-600 text-emerald-700 dark:text-emerald-400'
              : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          <BarChart3 className="w-4 h-4" />
          <span>Monthly Aggregate Indicators</span>
        </button>
      </div>

      {/* CSV TAB */}
      {subTab === 'csv' && (
        <Card>
          <CardHeader>
            <CardTitle>Generate Register from Offline CSV Tracker Extract</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <FileDropzone
              accept=".csv"
              value={csvFile}
              onChange={handleFileChange}
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <TextInput label="Region Filter (Optional)" value={region} onChange={(e) => setRegion(e.target.value)} />
              <TextInput label="Facility Filter (Optional)" value={facility} onChange={(e) => setFacility(e.target.value)} />
            </div>
            <Checkbox
              label="Split into one worksheet per facility"
              checked={sheetPerFacility}
              onChange={setSheetPerFacility}
            />
            <div className="flex justify-center pt-2">
              <Button
                variant="primary"
                size="md"
                loading={isStreaming}
                disabled={!csvFilePath || isViewer}
                onClick={handleRunCsvRegister}
              >
                Generate 01.2 Delivery Register
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* DHIS2 LIVE TAB */}
      {subTab === 'dhis2' && (
        <Card>
          <CardHeader>
            <CardTitle>Direct Extraction from DHIS2 Tracker Server</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <TextInput
                label="Maternal Inpatient Program UID"
                value={programUid}
                onChange={(e) => setProgramUid(e.target.value)}
              />
              <TextInput label="Facility Filter (Optional)" value={facility} onChange={(e) => setFacility(e.target.value)} />
              <TextInput label="Start Date (Gregorian)" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              <TextInput label="End Date (Gregorian)" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </div>
            <Checkbox
              label="Split into one worksheet per facility"
              checked={sheetPerFacility}
              onChange={setSheetPerFacility}
            />
            <div className="flex justify-center pt-2">
              <Button
                variant="primary"
                size="md"
                loading={isStreaming}
                disabled={isViewer}
                onClick={handleRunDhis2Register}
              >
                Query & Generate Register
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* AGGREGATE TAB */}
      {subTab === 'aggregate' && (
        <Card>
          <CardHeader>
            <CardTitle>Monthly Aggregate Indicators (HMIS 01.2)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <TextInput
                label="DHIS2 Aggregate Dataset UID"
                value={datasetUid}
                onChange={(e) => setDatasetUid(e.target.value)}
                placeholder="e.g. b5Xb7B9h3Qv"
              />
              <TextInput
                label="Reporting Period Code"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                placeholder="201702"
              />
            </div>
            <Checkbox
              label="Dry-run simulation only (Compute indicators without committing to DHIS2)"
              checked={dryRun}
              onChange={setDryRun}
            />
            <div className="flex justify-center pt-2">
              <Button
                variant={dryRun ? 'secondary' : 'primary'}
                size="md"
                loading={isStreaming}
                disabled={isViewer}
                onClick={() => {
                  if (dryRun) handleRunAggregate();
                  else setShowConfirm(true);
                }}
              >
                {dryRun ? 'Compute Monthly Tallies (Dry-Run)' : 'Commit Aggregates to DHIS2'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Computed Indicators Output Table */}
      {computedIndicators && (
        <Card>
          <CardHeader>
            <CardTitle>Computed HMIS 01.2 Monthly Tallies</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="border border-slate-200 dark:border-slate-800 rounded-lg overflow-x-auto max-h-[360px]">
              <table className="w-full text-left text-xs font-mono">
                <thead className="bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 uppercase text-[10px] tracking-wider sticky top-0">
                  <tr>
                    <th className="p-3">Data Element / Indicator</th>
                    <th className="p-3">Category Option</th>
                    <th className="p-3 text-right">Computed Count</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {Object.entries(computedIndicators).map(([key, val], idx) => (
                    <tr key={idx} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40">
                      <td className="p-2.5 font-sans font-semibold text-slate-800 dark:text-slate-200">{key}</td>
                      <td className="p-2.5 text-slate-500">default</td>
                      <td className="p-2.5 text-right font-bold text-teal-600 dark:text-teal-400 text-sm">
                        {typeof val === 'object' ? JSON.stringify(val) : val}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      <JobPanel
        jobId={activeJobId}
        jobState={jobState}
        logs={liveLogs}
        isStreaming={isStreaming}
        onCancel={handleCancelJob}
        onReset={resetJob}
        title="HMIS Register Processing"
      />

      <ConfirmDialog
        open={showConfirm}
        targetSystem="dhis2_online"
        title="Commit Monthly HMIS 01.2 Aggregates?"
        message={`This will post computed aggregate values for period "${period}" directly into DHIS2 Dataset "${datasetUid}". Do you want to proceed?`}
        confirmText="Confirm & Post"
        onConfirm={handleRunAggregate}
        onCancel={() => setShowConfirm(false)}
      />
    </div>
  );
};

export default RmhReportPage;
