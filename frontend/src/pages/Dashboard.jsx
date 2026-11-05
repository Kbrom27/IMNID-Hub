import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Server,
  Activity,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  Zap,
  Database,
  ArrowLeftRight,
  Boxes,
  FileSpreadsheet,
  Clock,
  ArrowRight,
  Info,
  ShieldCheck,
  Play,
  RotateCcw,
} from 'lucide-react';
import {
  PageHeader,
  Button,
  KpiCard,
  ServerTile,
  OperationsTable,
  AttentionNeeded,
  Tooltip,
  Skeleton,
} from '../ui';
import { useConnections } from '../context/ConnectionContext';

/**
 * Operations Dashboard Page
 * High-legibility "health-tech operations" cockpit.
 *
 * Scannable in 5 seconds:
 * 1. "Is the system healthy?" -> KPI strip + overall connection counter
 * 2. "What needs my attention?" -> Collapsible "Attention Needed" warning strip
 * 3. "What do I do next?" -> Quick launch module cards + Test All connections
 */
const Dashboard = () => {
  const {
    summary,
    loading: connLoading,
    secondsAgo,
    fetchStatus,
    testSingle,
    testAll,
    testingAll,
  } = useConnections();

  const [stats, setStats] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [loadingStats, setLoadingStats] = useState(true);

  // Load backend stats and job executions
  const loadStatsAndJobs = useCallback(async () => {
    try {
      const [statsRes, jobsRes] = await Promise.all([
        fetch('/api/dashboard/stats'),
        fetch('/api/jobs'),
      ]);
      if (statsRes.ok) setStats(await statsRes.json());
      if (jobsRes.ok) {
        const jData = await jobsRes.json();
        setJobs(Array.isArray(jData) ? jData : jData.jobs || []);
      }
    } catch (e) {
      console.error('Failed to load dashboard operational telemetry:', e);
    } finally {
      setLoadingStats(false);
    }
  }, []);

  useEffect(() => {
    loadStatsAndJobs();
    const timer = setInterval(loadStatsAndJobs, 20000);
    return () => clearInterval(timer);
  }, [loadStatsAndJobs]);

  const handleRefreshAll = () => {
    loadStatsAndJobs();
    fetchStatus();
  };

  // KPI Calculations
  const totalJobsCount = stats?.job_stats?.total ?? jobs.length;
  const completedJobsCount =
    stats?.job_stats?.completed ?? jobs.filter((j) => j.status === 'completed').length;
  const failedJobsCount =
    stats?.job_stats?.failed ?? jobs.filter((j) => j.status === 'failed' || j.status === 'canceled').length;
  const runningJobsCount = jobs.filter((j) => j.status === 'running').length;

  const successRate =
    totalJobsCount > 0
      ? ((completedJobsCount / totalJobsCount) * 100).toFixed(1)
      : '100.0';

  const failedJobsList = useMemo(() => {
    return jobs.filter((j) => (j.status || '').toLowerCase() === 'failed');
  }, [jobs]);

  return (
    <div className="space-y-6 w-full">
      {/* 1. Shared PageHeader with Breadcrumb, Title, Subtitle, and Primary Actions */}
      <PageHeader
        title="System Overview"
        subtitle="Unified health data integration, pipelines, and server connections monitor"
        breadcrumbs={[{ label: 'Overview', to: '/' }]}
        actions={
          <>
            {/* Secondary Job Monitor Link */}
            <Link
              to="/jobs"
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-200 shadow-xs transition-colors"
            >
              <Activity className="w-3.5 h-3.5 text-slate-500" />
              <span>Job Monitor</span>
            </Link>

            {/* Refresh Control with Relative Time indicator */}
            <Tooltip content={`Telemetry last refreshed ${secondsAgo}s ago. Click to refresh now.`}>
              <button
                type="button"
                onClick={handleRefreshAll}
                disabled={loadingStats || connLoading}
                className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-200 shadow-xs transition-colors cursor-pointer"
                aria-label="Refresh telemetry"
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 ${
                    loadingStats || connLoading ? 'animate-spin text-teal-600' : 'text-slate-500'
                  }`}
                />
                <span className="hidden sm:inline font-sans tabular-nums text-slate-500 dark:text-slate-400">
                  {secondsAgo}s ago
                </span>
              </button>
            </Tooltip>

            {/* Primary Action Button: Test All Connections */}
            <Button
              variant="primary"
              onClick={testAll}
              loading={testingAll}
              icon={<Play className="w-3.5 h-3.5 fill-current" />}
              size="sm"
              className="shadow-xs"
            >
              {testingAll ? 'Testing Endpoints...' : 'Test all connections'}
            </Button>
          </>
        }
      />

      {/* 2. KPI Cards Row (4 Columns in Responsive Grid) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* KPI 1: Total Executions */}
        <KpiCard
          title="Total Executions"
          value={totalJobsCount}
          subtext="Lifetime background pipelines"
          icon={<Activity className="w-4 h-4" />}
          variant="slate"
          loading={loadingStats}
        />

        {/* KPI 2: Successful Executions with % Rate */}
        <KpiCard
          title="Successful"
          value={completedJobsCount}
          subtext={
            <span>
              <strong className="text-emerald-600 dark:text-emerald-400">{successRate}%</strong> success rate
              {failedJobsCount > 0 && (
                <span className="text-slate-500 dark:text-slate-400 ml-1">
                  · <span className="text-rose-600 dark:text-rose-400 font-medium">{failedJobsCount} failed</span> (lifetime)
                </span>
              )}
            </span>
          }
          icon={<CheckCircle2 className="w-4 h-4" />}
          variant="emerald"
          loading={loadingStats}
        />

        {/* KPI 3: Active Workers in Running Threadpool */}
        <KpiCard
          title="Active Workers"
          value={runningJobsCount}
          subtext={
            runningJobsCount > 0
              ? 'Jobs currently running in threadpool'
              : 'Idle threadpool (awaiting jobs)'
          }
          icon={<RefreshCw className={`w-4 h-4 ${runningJobsCount > 0 ? 'animate-spin' : ''}`} />}
          variant="teal"
          loading={loadingStats}
          badge={
            runningJobsCount > 0 ? (
              <span className="inline-flex items-center gap-1 text-xs font-sans px-2 py-0.5 rounded-full bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 font-bold border border-teal-200 dark:border-teal-800">
                RUNNING
              </span>
            ) : null
          }
        />

        {/* KPI 4: Configured Servers (Single Source of Truth) */}
        <KpiCard
          title="Configured Servers"
          value={`${summary.connectedCount} of ${summary.totalCount}`}
          subtext={
            summary.offlineCount > 0 ? (
              <span className="text-rose-600 dark:text-rose-400 font-semibold">
                {summary.offlineCount} server{summary.offlineCount > 1 ? 's' : ''} unreachable
              </span>
            ) : (
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                All target systems connected
              </span>
            )
          }
          icon={<Server className="w-4 h-4" />}
          variant={summary.overallHealth === 'operational' ? 'emerald' : summary.overallHealth === 'degraded' ? 'amber' : 'rose'}
          loading={connLoading}
        />
      </div>

      {/* 3. Attention Needed Strip (Rendered ONLY if issues exist, compact by default) */}
      <AttentionNeeded
        offlineServers={summary.offlineSystems}
        failedJobs={failedJobsList}
        onTestServer={testSingle}
      />

      {/* 4. Two-Column Operational Layout:
          - Left (7 of 12 columns): Recent Operations Table
          - Right (5 of 12 columns): Server Status (grouped by category)
      */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Column: Recent Operations (7 Columns) */}
        <div className="lg:col-span-7 xl:col-span-7 space-y-4">
          <OperationsTable jobs={jobs} limit={7} />
        </div>

        {/* Right Column: Server Status grouped by category (5 Columns) */}
        <div className="lg:col-span-5 xl:col-span-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-teal-600 dark:text-teal-400" />
              <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
                Server Status
              </h2>
            </div>
            <Link
              to="/settings"
              className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 dark:hover:text-teal-300 flex items-center gap-1"
            >
              <span>Manage Credentials</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          {/* Group 1: DHIS2 Instances */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs px-1 text-slate-600 dark:text-slate-300 font-medium">
              <span className="uppercase tracking-[0.04em] text-xs font-bold">
                {summary.groups.dhis2.title}
              </span>
              <span className="font-sans tabular-nums text-xs">
                {summary.groups.dhis2.connected}/{summary.groups.dhis2.total} Connected
              </span>
            </div>
            <div className="space-y-2">
              {summary.groups.dhis2.systems.map((sys) => (
                <ServerTile
                  key={sys.key}
                  server={sys}
                  onTest={testSingle}
                  isTesting={sys.isTesting}
                />
              ))}
            </div>
          </div>

          {/* Group 2: Clinical Systems */}
          <div className="space-y-2 pt-2">
            <div className="flex items-center justify-between text-xs px-1 text-slate-600 dark:text-slate-300 font-medium">
              <span className="uppercase tracking-[0.04em] text-xs font-bold">
                {summary.groups.clinical.title}
              </span>
              <span className="font-sans tabular-nums text-xs">
                {summary.groups.clinical.connected}/{summary.groups.clinical.total} Connected
              </span>
            </div>
            <div className="space-y-2">
              {summary.groups.clinical.systems.map((sys) => (
                <ServerTile
                  key={sys.key}
                  server={sys}
                  onTest={testSingle}
                  isTesting={sys.isTesting}
                />
              ))}
            </div>
          </div>

          {/* Group 3: Core Services */}
          <div className="space-y-2 pt-2">
            <div className="flex items-center justify-between text-xs px-1 text-slate-600 dark:text-slate-300 font-medium">
              <span className="uppercase tracking-[0.04em] text-xs font-bold">
                {summary.groups.core.title}
              </span>
              <span className="font-sans tabular-nums text-xs">
                {summary.groups.core.connected}/{summary.groups.core.total} Connected
              </span>
            </div>
            <div className="space-y-2">
              {summary.groups.core.systems.map((sys) => (
                <ServerTile
                  key={sys.key}
                  server={sys}
                  onTest={testSingle}
                  isTesting={sys.isTesting}
                />
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* 5. Quick Actions Strip */}
      <div className="space-y-3 pt-2">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <Zap className="w-4 h-4 text-teal-600 dark:text-teal-400" />
            Quick Launch Modules
          </h2>
          <span className="text-xs text-slate-400">Launch workflows directly</span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
          <Link
            to="/hmis"
            className="p-4 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 hover:shadow-card-hover transition-all group flex flex-col justify-between"
          >
            <div>
              <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition-transform mb-2.5 border border-teal-200/60 dark:border-teal-900/40">
                <FileSpreadsheet className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">HMIS Reporting</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                RMH, NCH, NICU, Delivery, and MOH Aggregate
              </p>
            </div>
          </Link>

          <Link
            to="/data-management"
            className="p-4 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 hover:shadow-card-hover transition-all group flex flex-col justify-between"
          >
            <div>
              <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition-transform mb-2.5 border border-teal-200/60 dark:border-teal-900/40">
                <Database className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">Data Management</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                Exports, cleaning, direct sync, and record linking
              </p>
            </div>
          </Link>

          <Link
            to="/interop"
            className="p-4 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 hover:shadow-card-hover transition-all group flex flex-col justify-between"
          >
            <div>
              <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition-transform mb-2.5 border border-teal-200/60 dark:border-teal-900/40">
                <ArrowLeftRight className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">Interoperability</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                OpenMRS 3, Bahmni, mediator, and mappings
              </p>
            </div>
          </Link>

          <Link
            to="/smartcare"
            className="p-4 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 hover:shadow-card-hover transition-all group flex flex-col justify-between"
          >
            <div>
              <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition-transform mb-2.5 border border-teal-200/60 dark:border-teal-900/40">
                <Zap className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">SmartCare</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                Legacy demographics to OpenMRS 3.x
              </p>
            </div>
          </Link>

          <Link
            to="/concepts"
            className="p-4 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 hover:shadow-card-hover transition-all group flex flex-col justify-between"
          >
            <div>
              <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition-transform mb-2.5 border border-teal-200/60 dark:border-teal-900/40">
                <Boxes className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-900 dark:text-slate-100">Concepts & Forms</h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 line-clamp-2">
                Schema tools, validators, and dictionaries
              </p>
            </div>
          </Link>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
