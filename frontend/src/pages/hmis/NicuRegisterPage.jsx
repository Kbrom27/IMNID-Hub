import React, { useState } from 'react';
import {
  FileSpreadsheet,
  Calendar,
  Database,
  Server,
  Upload,
  Download,
  CheckCircle2,
  Table,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Button,
  TextInput,
  Select,
  Checkbox,
  JobPanel,
  FileDropzone,
  DirectoryPicker,
  Alert,
} from '../../ui';
import { useAuth } from '../../context/AuthContext';
import { useHmisJob } from './useHmisJob';
import {
  HmisConnectionCard,
  Dhis2ProgramSelect,
  Dhis2OrgUnitSelect,
  OpenmrsVisitTypeSelect,
  OpenmrsLocationSelect,
} from './HmisServerSelectors';

const ETH_MONTHS = [
  { val: 1, name: 'Meskerem (Sep–Oct)' },
  { val: 2, name: 'Tikimt (Oct–Nov)' },
  { val: 3, name: 'Hidar (Nov–Dec)' },
  { val: 4, name: 'Tahsas (Dec–Jan)' },
  { val: 5, name: 'Tir (Jan–Feb)' },
  { val: 6, name: 'Yakatit (Feb–Mar)' },
  { val: 7, name: 'Magabit (Mar–Apr)' },
  { val: 8, name: 'Miyazya (Apr–May)' },
  { val: 9, name: 'Ginbot (May–Jun)' },
  { val: 10, name: 'Sene (Jun–Jul)' },
  { val: 11, name: 'Hamle (Jul–Aug)' },
  { val: 12, name: 'Nehase (Aug–Sep)' },
  { val: 13, name: 'Pagumen (Sep)' },
];

const TAB_ITEMS = [
  { key: 'dhis2', label: 'DHIS2 Tracker', icon: Database },
  { key: 'openmrs', label: 'OpenMRS 3', icon: Server },
  { key: 'csv', label: 'CSV Extract', icon: FileSpreadsheet },
];

const NicuRegisterPage = () => {
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

  const [sourceTab, setSourceTab] = useState('dhis2');
  const [facility, setFacility] = useState('');
  const [region, setRegion] = useState('');
  const [sheetPerFacility, setSheetPerFacility] = useState(false);
  const [outputFilename, setOutputFilename] = useState('nicu_register.xlsx');
  const [outputDir, setOutputDir] = useState('/data/exports');
  const [dhis2System, setDhis2System] = useState('dhis2_online');
  const [programUid, setProgramUid] = useState('Neonatal Care Form');
  const [openmrsMode, setOpenmrsMode] = useState('live');
  const [openmrsVisitType, setOpenmrsVisitType] = useState('NICU');
  const [openmrsFacility, setOpenmrsFacility] = useState('');
  const [openmrsCsvFile, setOpenmrsCsvFile] = useState(null);
  const [openmrsCsvPath, setOpenmrsCsvPath] = useState('');
  const [trackerCsvFile, setTrackerCsvFile] = useState(null);
  const [trackerCsvPath, setTrackerCsvPath] = useState('');

  const startDate = calendarInfo?.gregorian_start || '';
  const endDate = calendarInfo?.gregorian_end || '';

  const handleRunDhis2 = () => {
    handleSubmitJob('/api/hmis/nh/nicu-register-dhis2', {
      system: dhis2System,
      program_uid: programUid,
      org_unit: facility || undefined,
      start: startDate || undefined,
      end: endDate || undefined,
      sheet_per_facility: sheetPerFacility,
      output_filename: outputFilename || undefined,
      output_dir: outputDir && !outputDir.startsWith('[Local Folder]') ? outputDir.trim() : undefined,
    });
  };

  const handleRunOpenmrs = () => {
    handleSubmitJob('/api/hmis/nh/nicu-register-openmrs', {
      input_file: openmrsMode === 'csv' ? openmrsCsvPath || (openmrsCsvFile?.name || '') : undefined,
      visit_type: openmrsVisitType,
      facility_name: openmrsFacility || facility || undefined,
      start: startDate || undefined,
      end: endDate || undefined,
      sheet_per_facility: sheetPerFacility,
      output_filename: outputFilename || undefined,
      output_dir: outputDir && !outputDir.startsWith('[Local Folder]') ? outputDir.trim() : undefined,
    });
  };

  const handleRunCsv = () => {
    handleSubmitJob('/api/hmis/nh/nicu-register-csv', {
      input_file: trackerCsvPath || (trackerCsvFile?.name || ''),
      facility: facility || undefined,
      region: region || undefined,
      start: startDate || undefined,
      end: endDate || undefined,
      sheet_per_facility: sheetPerFacility,
      output_filename: outputFilename || undefined,
      output_dir: outputDir && !outputDir.startsWith('[Local Folder]') ? outputDir.trim() : undefined,
    });
  };

  const handleTrackerCsvSelect = async (file) => {
    setTrackerCsvFile(file);
    if (file) {
      const path = await handleFileUpload(file);
      if (path) setTrackerCsvPath(path);
    }
  };

  const handleOpenmrsCsvSelect = async (file) => {
    setOpenmrsCsvFile(file);
    if (file) {
      const path = await handleFileUpload(file);
      if (path) setOpenmrsCsvPath(path);
    }
  };

  const tallies = outputArtifacts?.tallies || {};
  const tallyEntries = Object.entries(tallies);

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="NICU Register Generator"
        breadcrumbs={[
          { label: 'Reporting', href: '/hmis' },
          { label: 'NICU Register' },
        ]}
      />

      {/* Reporting Period */}
      <Card>
        <CardContent className="p-5 sm:p-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
            <Select
              label="Ethiopian Year"
              value={ethYear}
              onChange={(e) => handleYearMonthChange(Number(e.target.value), ethMonth)}
              options={(calendarInfo?.available_years || ['2016', '2017', '2018', '2019']).map((y) => ({
                label: `${y} E.C.`,
                value: Number(y),
              }))}
            />
            <Select
              label="Ethiopian Month"
              value={ethMonth}
              onChange={(e) => handleYearMonthChange(ethYear, Number(e.target.value))}
              options={ETH_MONTHS.map((m) => ({
                label: m.name,
                value: m.val,
              }))}
            />
            <div className="flex items-center gap-3 px-4 py-2.5 bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 rounded-lg text-sm">
              <Calendar className="w-5 h-5 text-teal-600 dark:text-teal-400 flex-shrink-0" />
              <div>
                <span className="font-bold text-teal-900 dark:text-teal-200">
                  {startDate || '—'} → {endDate || '—'}
                </span>
                <span className="text-teal-600 dark:text-teal-400 font-medium ml-2">
                  ({calendarInfo?.period_code || `${ethYear}${String(ethMonth).padStart(2, '0')}`})
                </span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Source Tabs */}
      <div className="flex gap-2 p-1.5 bg-slate-100 dark:bg-slate-800/70 rounded-xl border border-slate-200/80 dark:border-slate-700/80 w-fit">
        {TAB_ITEMS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setSourceTab(key)}
            className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-bold transition-all ${
              sourceTab === key
                ? 'bg-white dark:bg-slate-900 text-teal-700 dark:text-teal-300 shadow-xs border border-slate-200 dark:border-slate-700'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* DHIS2 Tracker Form */}
      {sourceTab === 'dhis2' && (
        <Card>
          <CardContent className="space-y-4">
            <HmisConnectionCard
              type="dhis2"
              selectedSystem={dhis2System}
              onSystemChange={setDhis2System}
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <Dhis2ProgramSelect
                system={dhis2System}
                value={programUid}
                onChange={setProgramUid}
                filterKeyword="Neonatal"
                label="NICU Tracker Program"
              />
              <Dhis2OrgUnitSelect
                system={dhis2System}
                value={facility}
                onChange={setFacility}
                label="Facility"
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <DirectoryPicker label="Output Directory" value={outputDir} onChange={setOutputDir} />
              <TextInput
                label="Output Filename"
                value={outputFilename}
                onChange={(e) => setOutputFilename(e.target.value)}
                placeholder="nicu_register.xlsx"
              />
            </div>
            <Checkbox
              id="nicu-dhis2-sheet-split"
              checked={sheetPerFacility}
              onChange={(e) => setSheetPerFacility(e.target.checked)}
              label="Separate sheet per facility"
            />
            <div className="flex justify-center pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button variant="primary" onClick={handleRunDhis2} disabled={isViewer || isStreaming}>
                <FileSpreadsheet className="w-4 h-4 mr-1.5" />
                Generate Register
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* OpenMRS 3 Form */}
      {sourceTab === 'openmrs' && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm">OpenMRS 3 Extraction</CardTitle>
              <div className="inline-flex rounded-md p-0.5 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setOpenmrsMode('live')}
                  className={`px-2.5 py-1 rounded transition-colors ${
                    openmrsMode === 'live'
                      ? 'bg-white dark:bg-slate-700 text-teal-700 dark:text-teal-300 shadow-sm'
                      : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  Live Server
                </button>
                <button
                  type="button"
                  onClick={() => setOpenmrsMode('csv')}
                  className={`px-2.5 py-1 rounded transition-colors ${
                    openmrsMode === 'csv'
                      ? 'bg-white dark:bg-slate-700 text-teal-700 dark:text-teal-300 shadow-sm'
                      : 'text-slate-500 hover:text-slate-700'
                  }`}
                >
                  CSV Upload
                </button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4 pt-0">
            {openmrsMode === 'live' ? (
              <div className="space-y-3">
                <HmisConnectionCard type="openmrs" />
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  <OpenmrsVisitTypeSelect value={openmrsVisitType} onChange={setOpenmrsVisitType} defaultType="NICU" />
                  <OpenmrsLocationSelect value={openmrsFacility} onChange={setOpenmrsFacility} label="Location" />
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <FileDropzone label="Upload NICU CSV" accept=".csv" onFileSelect={handleOpenmrsCsvSelect} />
                {openmrsCsvFile && (
                  <div className="px-3 py-2 bg-teal-50 dark:bg-teal-950/30 border border-teal-200 dark:border-teal-800 rounded-lg text-xs flex items-center justify-between text-teal-800 dark:text-teal-200">
                    <span className="font-medium truncate">{openmrsCsvFile.name}</span>
                    <span className="text-teal-600/70">{(openmrsCsvFile.size / 1024).toFixed(1)} KB</span>
                  </div>
                )}
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <DirectoryPicker label="Output Directory" value={outputDir} onChange={setOutputDir} />
              <TextInput
                label="Output Filename"
                value={outputFilename}
                onChange={(e) => setOutputFilename(e.target.value)}
                placeholder="nicu_register_openmrs.xlsx"
              />
            </div>
            <Checkbox
              id="nicu-openmrs-sheet-split"
              checked={sheetPerFacility}
              onChange={(e) => setSheetPerFacility(e.target.checked)}
              label="Separate sheet per facility"
            />
            <div className="flex justify-center pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button variant="primary" onClick={handleRunOpenmrs} disabled={isViewer || isStreaming}>
                <FileSpreadsheet className="w-4 h-4 mr-1.5" />
                Generate Register
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* CSV Extract Form */}
      {sourceTab === 'csv' && (
        <Card>
          <CardContent className="space-y-4">
            <FileDropzone label="Upload NICU CSV Extract" accept=".csv" onFileSelect={handleTrackerCsvSelect} />
            {trackerCsvFile && (
              <div className="px-3 py-2 bg-teal-50 dark:bg-teal-950/30 border border-teal-200 dark:border-teal-800 rounded-lg text-xs flex items-center justify-between text-teal-800 dark:text-teal-200">
                <span className="font-medium truncate">{trackerCsvFile.name}</span>
                <span className="text-teal-600/70">{(trackerCsvFile.size / 1024).toFixed(1)} KB</span>
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
              <TextInput label="Facility (optional)" value={facility} onChange={(e) => setFacility(e.target.value)} placeholder="Leave blank for all" />
              <TextInput label="Region (optional)" value={region} onChange={(e) => setRegion(e.target.value)} placeholder="e.g. Amhara" />
              <DirectoryPicker label="Output Directory" value={outputDir} onChange={setOutputDir} />
              <TextInput label="Output Filename" value={outputFilename} onChange={(e) => setOutputFilename(e.target.value)} placeholder="nicu_register.xlsx" />
            </div>
            <Checkbox
              id="nicu-csv-sheet-split"
              checked={sheetPerFacility}
              onChange={(e) => setSheetPerFacility(e.target.checked)}
              label="Separate sheet per facility"
            />
            <div className="flex justify-center pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button variant="primary" onClick={handleRunCsv} disabled={isViewer || isStreaming || (!trackerCsvFile && !trackerCsvPath)}>
                <FileSpreadsheet className="w-4 h-4 mr-1.5" />
                Generate Register
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Job Panel */}
      <JobPanel
        jobId={activeJobId}
        jobState={jobState}
        logs={liveLogs}
        liveLogs={liveLogs}
        isStreaming={isStreaming}
        onCancel={handleCancelJob}
        onReset={resetJob}
        onDismiss={resetJob}
      />

      {/* Success Artifacts */}
      {outputArtifacts && (
        <div className="flex items-center justify-between gap-3 p-4 bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800/60 rounded-lg">
          <div className="flex items-center gap-2.5">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
            <div>
              <span className="text-sm font-semibold text-emerald-900 dark:text-emerald-100">Register Generated</span>
              {outputArtifacts.filename && (
                <span className="text-xs text-emerald-700/70 dark:text-emerald-300/70 ml-2">{outputArtifacts.filename}</span>
              )}
            </div>
          </div>
          {outputArtifacts.filename && (
            <a
              href={`/api/hmis/download/${encodeURIComponent(outputArtifacts.filename)}`}
              download
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              Download .xlsx
            </a>
          )}
        </div>
      )}

      {/* Tallies */}
      {tallyEntries.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">
              <Table className="w-4 h-4 text-teal-600" />
              Summary Tallies
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
              {tallyEntries.map(([label, val]) => (
                <div
                  key={label}
                  className="p-2.5 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700/60 rounded-lg"
                >
                  <span className="text-[11px] text-slate-500 block truncate" title={label}>{label}</span>
                  <span className="font-bold text-sm text-teal-700 dark:text-teal-400 block mt-0.5">{val}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default NicuRegisterPage;
