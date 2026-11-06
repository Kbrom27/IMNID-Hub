import React, { useState, useEffect } from 'react';
import {
  BarChart2,
  Calendar,
  Database,
  Download,
  FileSpreadsheet,
  Server,
  CheckCircle2,
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
  DateInput,
  JobPanel,
  FileDropzone,
  DirectoryPicker,
} from '../../ui';
import { useAuth } from '../../context/AuthContext';
import { useHmisJob } from './useHmisJob';
import {
  HmisConnectionCard,
  Dhis2OrgUnitSelect,
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
];

const HmisRmhReportPage = () => {
  const { isViewer, authHeader } = useAuth();
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
  const [periodType, setPeriodType] = useState('reporting'); // 'reporting' | 'custom'
  const [customStartDate, setCustomStartDate] = useState('');
  const [customEndDate, setCustomEndDate] = useState('');
  const [outputFilename, setOutputFilename] = useState('rmh_report.xlsx');
  const [dhis2System, setDhis2System] = useState('dhis2_online');
  const [programUid, setProgramUid] = useState('Maternal Inpatient Data');
  const [facility, setFacility] = useState('');
  const [ouMode, setOuMode] = useState('SELECTED');
  const [outputDir, setOutputDir] = useState('/data/exports');

  const [openmrsMode, setOpenmrsMode] = useState('live');
  const openmrsVisitType = 'Delivery';
  const [openmrsFacility, setOpenmrsFacility] = useState('');
  const [openmrsCsvFile, setOpenmrsCsvFile] = useState(null);
  const [openmrsCsvPath, setOpenmrsCsvPath] = useState('');
  const [indicatorSearch, setIndicatorSearch] = useState('');

  useEffect(() => {
    if (!dhis2System) return;
    let isMounted = true;
    fetch(`/api/hmis/dhis2/programs?system=${dhis2System}`, { headers: authHeader() })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!isMounted || !data?.programs) return;
        const matched = data.programs.find(
          (p) =>
            p.name?.toLowerCase().includes('maternal') ||
            p.id === 'aLoraiFNkng'
        );
        if (matched) {
          setProgramUid(matched.id);
        }
      })
      .catch(() => {});
    return () => {
      isMounted = false;
    };
  }, [dhis2System, authHeader]);

  const periodCode = calendarInfo?.period_code || `${ethYear}${String(ethMonth).padStart(2, '0')}`;
  const startDate = calendarInfo?.gregorian_start || '';
  const endDate = calendarInfo?.gregorian_end || '';
  const effectiveStart = periodType === 'custom' ? (customStartDate || undefined) : (startDate || undefined);
  const effectiveEnd = periodType === 'custom' ? (customEndDate || undefined) : (endDate || undefined);
  const effectivePeriod = periodType === 'custom'
    ? (customStartDate && customEndDate ? `${customStartDate}_${customEndDate}` : periodCode)
    : periodCode;

  const getSanitizedFilename = (rawName, fallback) => {
    const clean = (rawName || '').trim();
    if (!clean) return fallback;
    return clean.toLowerCase().endsWith('.xlsx') ? clean : `${clean}.xlsx`;
  };

  const handleRunDhis2Report = () => {
    handleSubmitJob('/api/hmis/rmh/aggregate-report', {
      system: dhis2System,
      delivery_program: programUid || 'Maternal Inpatient Data',
      org_unit: facility || undefined,
      ou_mode: ouMode,
      period: effectivePeriod,
      start: effectiveStart,
      end: effectiveEnd,
      output_filename: getSanitizedFilename(outputFilename, 'rmh_report.xlsx'),
      output_dir: outputDir && !outputDir.startsWith('[Local Folder]') ? outputDir.trim() : undefined,
    });
  };

  const handleRunOpenmrsReport = () => {
    handleSubmitJob('/api/hmis/rmh/aggregate-report-openmrs', {
      input_file: openmrsMode === 'csv' ? openmrsCsvPath || (openmrsCsvFile?.name || '') : undefined,
      visit_type: 'Delivery',
      facility_name: openmrsFacility || undefined,
      period: effectivePeriod,
      start: effectiveStart,
      end: effectiveEnd,
      output_filename: getSanitizedFilename(outputFilename, 'rmh_report_openmrs.xlsx'),
      output_dir: outputDir && !outputDir.startsWith('[Local Folder]') ? outputDir.trim() : undefined,
    });
  };

  const renderPeriodSelector = () => (
    <div className="space-y-2 p-3 bg-slate-50/70 dark:bg-slate-900/50 rounded-xl border border-slate-200/80 dark:border-slate-800">
      <div className="flex items-center justify-between pb-1">
        <label className="text-xs font-semibold text-slate-700 dark:text-slate-300">
          Period Selection
        </label>
        <div className="flex items-center gap-1 bg-slate-200/60 dark:bg-slate-800 p-0.5 rounded-lg text-xs font-medium">
          <button
            type="button"
            onClick={() => setPeriodType('reporting')}
            className={`px-3 py-1 rounded-md transition-all ${
              periodType === 'reporting'
                ? 'bg-white dark:bg-slate-900 text-teal-700 dark:text-teal-300 shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            }`}
          >
            Reporting Period (Ethiopian)
          </button>
          <button
            type="button"
            onClick={() => setPeriodType('custom')}
            className={`px-3 py-1 rounded-md transition-all ${
              periodType === 'custom'
                ? 'bg-white dark:bg-slate-900 text-teal-700 dark:text-teal-300 shadow-xs'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
            }`}
          >
            Custom Period (Date Range)
          </button>
        </div>
      </div>

      {periodType === 'reporting' ? (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
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
          <div className="flex items-center gap-2.5 px-3.5 py-2.5 bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 rounded-lg text-xs">
            <Calendar className="w-4 h-4 text-teal-600 dark:text-teal-400 flex-shrink-0" />
            <div className="truncate">
              <span className="font-bold text-teal-900 dark:text-teal-200">
                {startDate || '—'} → {endDate || '—'}
              </span>
              <span className="text-teal-600 dark:text-teal-400 font-medium ml-1.5">
                ({periodCode})
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
          <DateInput
            label="Start Date"
            value={customStartDate}
            onChange={(e) => setCustomStartDate(e.target.value)}
          />
          <DateInput
            label="End Date"
            value={customEndDate}
            onChange={(e) => setCustomEndDate(e.target.value)}
          />
          <div className="flex items-center gap-2.5 px-3.5 py-2.5 bg-teal-50 dark:bg-teal-950/40 border border-teal-200 dark:border-teal-800 rounded-lg text-xs">
            <Calendar className="w-4 h-4 text-teal-600 dark:text-teal-400 flex-shrink-0" />
            <div className="truncate">
              <span className="font-bold text-teal-900 dark:text-teal-200">
                {customStartDate || 'Start'} → {customEndDate || 'End'}
              </span>
              <span className="text-teal-600 dark:text-teal-400 font-medium ml-1.5">
                (Custom Range)
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const handleCsvSelect = async (file) => {
    setOpenmrsCsvFile(file);
    if (file) {
      const path = await handleFileUpload(file);
      if (path) setOpenmrsCsvPath(path);
    }
  };

  const isJobCompleted = jobState?.status === 'completed';
  const resultFileName =
    (Array.isArray(outputArtifacts) && outputArtifacts[0]) ||
    outputArtifacts?.filename ||
    jobState?.result_file ||
    jobState?.artifacts?.output_xlsx ||
    jobState?.artifacts?.output_file;

  const indicatorEntries = Object.entries(computedIndicators || {});
  const filteredIndicators = indicatorEntries.filter(([code, val]) => {
    if (!indicatorSearch) return true;
    const q = indicatorSearch.toLowerCase();
    return code.toLowerCase().includes(q) || String(val).toLowerCase().includes(q);
  });

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="HMIS RMH Report Generator (MoH 01.2)"
        breadcrumbs={[
          { label: 'Reporting', href: '/hmis' },
          { label: 'HMIS RMH Report' },
        ]}
      />

      {/* Source Selection Tabs */}
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

            {renderPeriodSelector()}

            <Dhis2OrgUnitSelect
              system={dhis2System}
              value={facility}
              onChange={setFacility}
              ouMode={ouMode}
              onOuModeChange={setOuMode}
              label="Target Org Unit"
            />

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <TextInput
                label="Output File Name"
                value={outputFilename}
                onChange={(e) => setOutputFilename(e.target.value)}
                placeholder="rmh_report.xlsx"
              />
              <DirectoryPicker
                label="Output Directory"
                value={outputDir}
                onChange={setOutputDir}
              />
            </div>

            <div className="flex items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="primary"
                onClick={handleRunDhis2Report}
                disabled={isViewer || isStreaming}
              >
                <BarChart2 className="w-4 h-4 mr-1.5" />
                Generate RMH Report
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
              <CardTitle className="text-sm">OpenMRS 3 Maternal Health Extraction</CardTitle>
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
                {renderPeriodSelector()}
                <OpenmrsLocationSelect
                  value={openmrsFacility}
                  onChange={setOpenmrsFacility}
                  label="Location / Ward"
                />
              </div>
            ) : (
              <div className="space-y-2">
                <FileDropzone
                  label="Upload OpenMRS Delivery Encounters CSV"
                  accept=".csv"
                  onFileSelect={handleCsvSelect}
                />
                {openmrsCsvFile && (
                  <div className="px-3 py-2 bg-teal-50 dark:bg-teal-950/30 border border-teal-200 dark:border-teal-800 rounded-lg text-xs flex items-center justify-between text-teal-800 dark:text-teal-200">
                    <span className="font-medium truncate">{openmrsCsvFile.name}</span>
                    <span className="text-teal-600/70">
                      {(openmrsCsvFile.size / 1024).toFixed(1)} KB
                    </span>
                  </div>
                )}
                {renderPeriodSelector()}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <TextInput
                label="Output File Name"
                value={outputFilename}
                onChange={(e) => setOutputFilename(e.target.value)}
                placeholder="rmh_report_openmrs.xlsx"
              />
              <DirectoryPicker
                label="Output Directory"
                value={outputDir}
                onChange={setOutputDir}
              />
            </div>

            <div className="flex items-center justify-center gap-3 pt-3 border-t border-slate-100 dark:border-slate-800">
              <Button
                variant="primary"
                onClick={handleRunOpenmrsReport}
                disabled={isViewer || isStreaming}
              >
                <BarChart2 className="w-4 h-4 mr-1.5" />
                Generate RMH Report from OpenMRS
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
        showDownloadButtons={false}
      />

      {/* Indicators Table */}
      {indicatorEntries.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <CardTitle className="text-sm">
                <FileSpreadsheet className="w-4 h-4 text-teal-600" />
                Computed MoH 01.2 Indicators ({filteredIndicators.length})
              </CardTitle>
              <div className="w-full sm:w-64">
                <TextInput
                  placeholder="Filter indicators..."
                  value={indicatorSearch}
                  onChange={(e) => setIndicatorSearch(e.target.value)}
                  className="text-xs"
                />
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="max-h-96 overflow-y-auto border border-slate-200 dark:border-slate-800 rounded-lg">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="bg-slate-50 dark:bg-slate-900 text-slate-500 sticky top-0 border-b border-slate-200 dark:border-slate-800">
                  <tr>
                    <th className="py-2.5 px-4 font-semibold">Indicator Code</th>
                    <th className="py-2.5 px-4 font-semibold text-right">Computed Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono">
                  {filteredIndicators.map(([code, val]) => (
                    <tr
                      key={code}
                      className="hover:bg-slate-50/80 dark:hover:bg-slate-900/40 transition-colors"
                    >
                      <td className="py-2 px-4 text-slate-800 dark:text-slate-200">{code}</td>
                      <td className="py-2 px-4 text-right">
                        {val === null || val === undefined ? (
                          <span className="text-slate-400 font-normal italic">—</span>
                        ) : val === 'Not available' ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400 border border-slate-200 dark:border-slate-700 italic">
                            Not available
                          </span>
                        ) : (
                          <span className="text-teal-700 dark:text-teal-400 font-bold">{val}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {filteredIndicators.length === 0 && (
                    <tr>
                      <td colSpan="2" className="py-4 text-center text-slate-400 italic">
                        No indicators matching filter
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

export default HmisRmhReportPage;
