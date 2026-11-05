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
    <div className="space-y-4 w-full">
      {/* 1. Shared PageHeader with Breadcrumb, Title, and Primary Actions (no subtitle per Section A) */}
      <PageHeader
        title="Dashboard"
        breadcrumbs={[{ label: 'Overview', to: '/' }]}
        actions={
          <>
            {/* Refresh Control with Relative Time indicator */}
            <Tooltip content="Refresh telemetry now">
              <button
                type="button"
                onClick={handleRefreshAll}
                disabled={loadingStats || connLoading}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-200 shadow-2xs transition-colors cursor-pointer"
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
              className="shadow-2xs"
            >
              {testingAll ? 'Testing Endpoints...' : 'Test all connections'}
            </Button>
          </>
        }
      />

      {/* 2. KPI Cards Row (4 Columns in Responsive Grid, ~88-94px tall, one short metric only) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* KPI 1: Total Executions */}
        <KpiCard
          title="Total Executions"
          value={totalJobsCount}
          icon={<Activity className="w-4 h-4" />}
          variant="slate"
          loading={loadingStats}
        />

        {/* KPI 2: Successful Executions with % Rate inline */}
        <KpiCard
          title="Successful"
          value={completedJobsCount}
          subtext={`${successRate}%`}
          icon={<CheckCircle2 className="w-4 h-4" />}
          variant="emerald"
          loading={loadingStats}
        />

        {/* KPI 3: Active Workers in Running Threadpool */}
        <KpiCard
          title="Active Workers"
          value={runningJobsCount}
          icon={<RefreshCw className={`w-4 h-4 ${runningJobsCount > 0 ? 'animate-spin' : ''}`} />}
          variant="teal"
          loading={loadingStats}
          badge={
            runningJobsCount > 0 ? (
              <span className="inline-flex items-center gap-1 text-[11px] font-sans px-1.5 py-0.2 rounded-full bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 font-bold border border-teal-200 dark:border-teal-800">
                RUNNING
              </span>
            ) : null
          }
        />

        {/* KPI 4: Configured Servers (5/7 with semantic status colors per Section C) */}
        <KpiCard
          title="Configured Servers"
          value={`${summary.connectedCount}/${summary.totalCount}`}
          icon={<Server className="w-4 h-4" />}
          variant={summary.overallHealth === 'operational' ? 'emerald' : summary.overallHealth === 'degraded' ? 'amber' : 'rose'}
          loading={connLoading}
        />
      </div>

      {/* 3. Attention Needed Strip (Single-line summary bar) */}
      <AttentionNeeded
        offlineServers={summary.offlineSystems}
        failedJobs={failedJobsList}
        onTestServer={testSingle}
      />

      {/* 4. Two-Column Operational Layout:
          - Left (7 of 12 columns): Recent Operations Table (8 single-row items)
          - Right (5 of 12 columns): Server Status (single-row tiles with matching header)
      */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
        {/* Left Column: Recent Operations (7 Columns) */}
        <section aria-label="Recent operations" className="lg:col-span-7 xl:col-span-7">
          <OperationsTable jobs={jobs} limit={8} />
        </section>

        {/* Right Column: Server Status (5 Columns) with identical panel styling */}
        <section aria-label="Server status" className="lg:col-span-5 xl:col-span-5 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100 tracking-tight">
                Server Status
              </h2>
              <span className="text-xs font-sans tabular-nums font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
                {summary.totalCount}
              </span>
            </div>
            <Link
              to="/settings"
              className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 dark:hover:text-teal-300 flex items-center gap-1"
            >
              <span>Manage</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xs overflow-hidden divide-y divide-slate-100 dark:divide-slate-800/80">
            {(summary?.systems || summary?.list || []).map((sys) => (
              <ServerTile
                key={sys.key}
                server={sys}
                onTest={testSingle}
                isTesting={sys.isTesting}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

export default Dashboard;
