import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  Server,
  Activity,
  CheckCircle2,
  XCircle,
  MinusCircle,
  Copy,
  Check,
  RefreshCw,
  Zap,
  Database,
  ArrowLeftRight,
  Boxes,
  FileSpreadsheet,
  Clock,
  ArrowRight,
  Info,
  AlertCircle
} from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardDescription, CardContent, Badge, Button, StatusBadge } from '../ui';

const Dashboard = () => {
  const [stats, setStats] = useState(null);
  const [connections, setConnections] = useState({});
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [testingSystem, setTestingSystem] = useState(null);
  const [copiedKey, setCopiedKey] = useState(null);

  const loadData = async () => {
    try {
      const [statsRes, connRes, jobsRes] = await Promise.all([
        fetch('/api/dashboard/stats'),
        fetch('/api/connections/status'),
        fetch('/api/jobs')
      ]);
      if (statsRes.ok) setStats(await statsRes.json());
      if (connRes.ok) setConnections(await connRes.json());
      if (jobsRes.ok) {
        const jData = await jobsRes.json();
        setJobs(Array.isArray(jData) ? jData : jData.jobs || []);
      }
    } catch (e) {
      console.error('Failed to load dashboard data:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 20000);
    return () => clearInterval(timer);
  }, []);

  const testSingle = async (systemKey) => {
    const sys = connections[systemKey];
    if (!sys) return;
    setTestingSystem(systemKey);
    try {
      const res = await fetch('/api/connections/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system: systemKey,
          base_url: sys.configured_url || sys.base_url || '',
          username: sys.username || '',
          secret: ''
        })
      });
      const data = await res.json();
      setConnections(prev => ({
        ...prev,
        [systemKey]: {
          ...prev[systemKey],
          result: data,
          status: data.ok ? 'connected' : data.status === 'not_configured' ? 'not_configured' : 'unreachable'
        }
      }));
    } catch (e) {
      console.error(e);
    } finally {
      setTestingSystem(null);
    }
  };

  const handleCopyUrl = (systemKey, url) => {
    if (!url) return;
    navigator.clipboard.writeText(url);
    setCopiedKey(systemKey);
    setTimeout(() => setCopiedKey(null), 1500);
  };

  const systemsList = [
    { key: 'dhis2_online', name: 'DHIS2 Online', desc: 'National Data Warehouse' },
    { key: 'dhis2_offline', name: 'DHIS2 Offline', desc: 'Facility Local Instance' },
    { key: 'dhis2_moh', name: 'DHIS2 MOH Central', desc: 'National Aggregate Server' },
    { key: 'openmrs', name: 'OpenMRS 3.x', desc: 'Hospital Clinical EMR' },
    { key: 'bahmni', name: 'Bahmni 0.93', desc: 'Legacy EMR Platform' },
    { key: 'redcap', name: 'REDCap', desc: 'Research Clinical Registry' },
    { key: 'mediator', name: 'Mediator Service', desc: 'FastAPI Microservice' },
  ];

  return (
    <div className="space-y-6 w-full">
      {/* Standard PageHeader */}
      <PageHeader
        title="System Overview"
        description="Unified health data integration, pipelines, and server connections monitor"
        actions={
          <div className="flex items-center gap-2.5">
            <Link
              to="/jobs"
              className="flex items-center gap-2 px-4 py-2.5 bg-teal-600 hover:bg-teal-700 text-white rounded-lg text-sm font-semibold shadow-sm transition"
            >
              <Activity className="w-4 h-4" />
              <span>Job Monitor</span>
            </Link>
            <button
              onClick={loadData}
              className="p-2.5 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-lg text-sm font-semibold border border-slate-200 dark:border-slate-800 transition"
              title="Refresh All"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-teal-600' : ''}`} />
            </button>
          </div>
        }
      />

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
            Total Executions
          </div>
          <div className="text-2xl font-bold text-slate-800 dark:text-slate-100 mt-1">
            {stats?.job_stats?.total ?? jobs.length}
          </div>
          <div className="text-xs text-slate-500 mt-1">Background jobs</div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider">
            Successful
          </div>
          <div className="text-2xl font-bold text-emerald-700 dark:text-emerald-300 mt-1">
            {stats?.job_stats?.completed ?? jobs.filter(j => j.status === 'completed').length}
          </div>
          <div className="text-xs text-emerald-600/80 dark:text-emerald-400/80 mt-1">
            Completed with success
          </div>
        </div>

        {/* Active Workers with Explicit Computation Explanation */}
        <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm relative group">
          <div className="flex items-center justify-between">
            <div className="text-xs font-semibold text-teal-600 dark:text-teal-400 uppercase tracking-wider">
              Active Workers
            </div>
            <Info className="w-3.5 h-3.5 text-slate-400 cursor-help" />
          </div>
          <div className="text-2xl font-bold text-teal-700 dark:text-teal-300 mt-1">
            {jobs.filter(j => j.status === 'running').length}
          </div>
          <div className="text-xs text-teal-600/80 dark:text-teal-400/80 mt-1 truncate" title="Computed as backend jobs currently in 'running' execution state">
            Jobs in running threadpool
          </div>
        </div>

        <div className="bg-white dark:bg-slate-900 p-5 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
            Configured Servers
          </div>
          <div className="text-2xl font-bold text-slate-800 dark:text-slate-100 mt-1">
            {systemsList.filter((sys) => {
              const c = connections[sys.key];
              return c && c.configured === true && c.status !== 'not_configured';
            }).length}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {systemsList.filter((sys) => {
              const c = connections[sys.key];
              return c && c.configured === true && c.status !== 'not_configured' && (c.status === 'connected' || c.result?.ok === true);
            }).length} connected
          </div>
        </div>
      </div>

      {/* Server Connections Status Grid */}
      <div className="bg-white dark:bg-slate-900 p-6 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">
              Server Connections & Endpoints
            </h2>
          </div>
          <Link
            to="/settings"
            className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 dark:hover:text-teal-300 flex items-center gap-1"
          >
            Manage Credentials <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {systemsList.map((sys) => {
            const data = connections[sys.key];
            const isConf = data?.configured !== false;
            const isConnected = data?.status === 'connected' || data?.result?.ok === true;
            const isUnreachable = isConf && (data?.status === 'unreachable' || data?.result?.ok === false);
            const isTesting = testingSystem === sys.key;
            const effectiveUrl = data?.effective_url || data?.base_url || '';
            const sourceBadge = data?.source === 'vault' ? 'Saved in vault' : 'From environment';

            return (
              <div
                key={sys.key}
                className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/60 dark:bg-slate-800/40 hover:bg-slate-50 dark:hover:bg-slate-800/70 transition flex flex-col justify-between space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold text-sm text-slate-800 dark:text-slate-100 flex items-center gap-2">
                      <Server className="w-4 h-4 text-teal-600 dark:text-teal-400" />
                      {sys.name}
                    </div>
                    <div className="text-[11px] text-slate-400 mt-0.5">{sys.desc}</div>
                  </div>

                  <div>
                    {!isConf ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700">
                        <MinusCircle className="w-3 h-3 text-slate-400" />
                        Not Configured
                      </span>
                    ) : isConnected ? (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                        <CheckCircle2 className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
                        Connected
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-100 dark:bg-rose-950/60 text-rose-800 dark:text-rose-300 border border-rose-200 dark:border-rose-800">
                        <XCircle className="w-3 h-3 text-rose-600 dark:text-rose-400" />
                        Offline
                      </span>
                    )}
                  </div>
                </div>

                {/* Monospace Plain URL with Copy Button & Source Badge */}
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="font-semibold uppercase tracking-wider">Effective URL</span>
                    <span className="bg-slate-200 dark:bg-slate-700 px-1.5 py-0.2 rounded text-[10px] text-slate-600 dark:text-slate-300">
                      {sourceBadge}
                    </span>
                  </div>
                  <div className="flex items-center gap-1 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-1 px-2">
                    <span className="text-xs font-mono text-slate-700 dark:text-slate-300 truncate flex-1">
                      {effectiveUrl || '—'}
                    </span>
                    <button
                      onClick={() => handleCopyUrl(sys.key, effectiveUrl)}
                      className="p-1 text-slate-400 hover:text-teal-600 dark:hover:text-teal-400 rounded transition"
                      title="Copy URL"
                    >
                      {copiedKey === sys.key ? (
                        <Check className="w-3.5 h-3.5 text-emerald-600" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                </div>

                <div className="flex items-center justify-between text-xs pt-1 border-t border-slate-200/60 dark:border-slate-800">
                  <span className="text-slate-500 font-medium">
                    {data?.result?.latency_ms ? `${data.result.latency_ms} ms` : '—'}
                  </span>
                  <button
                    onClick={() => testSingle(sys.key)}
                    disabled={isTesting}
                    className="px-2.5 py-1 text-xs font-semibold text-teal-700 dark:text-teal-300 bg-teal-50 dark:bg-teal-950/40 hover:bg-teal-100 dark:hover:bg-teal-900/60 border border-teal-200 dark:border-teal-800 rounded transition flex items-center gap-1 cursor-pointer"
                  >
                    <RefreshCw className={`w-3 h-3 ${isTesting ? 'animate-spin' : ''}`} />
                    <span>{isTesting ? 'Testing...' : 'Test'}</span>
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Quick Launch Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
        <Link
          to="/hmis"
          className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 hover:shadow-md transition group flex flex-col justify-between"
        >
          <div>
            <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition mb-2.5">
              <FileSpreadsheet className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-xs text-slate-800 dark:text-slate-100">HMIS Reporting</h3>
            <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">RMH, NCH, NICU, Delivery, and MOH Aggregate</p>
          </div>
        </Link>

        <Link
          to="/data-management"
          className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 hover:shadow-md transition group flex flex-col justify-between"
        >
          <div>
            <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition mb-2.5">
              <Database className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-xs text-slate-800 dark:text-slate-100">Data Management</h3>
            <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">Exports, cleaning, sync, metadata, and linking</p>
          </div>
        </Link>

        <Link
          to="/interop"
          className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 hover:shadow-md transition group flex flex-col justify-between"
        >
          <div>
            <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition mb-2.5">
              <ArrowLeftRight className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-xs text-slate-800 dark:text-slate-100">Interoperability</h3>
            <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">OpenMRS 3, Bahmni, mediator, and mappings</p>
          </div>
        </Link>

        <Link
          to="/smartcare"
          className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 hover:shadow-md transition group flex flex-col justify-between"
        >
          <div>
            <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition mb-2.5">
              <Zap className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-xs text-slate-800 dark:text-slate-100">SmartCare</h3>
            <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">Legacy demographics to OpenMRS 3.x</p>
          </div>
        </Link>

        <Link
          to="/concepts"
          className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 hover:shadow-md transition group flex flex-col justify-between"
        >
          <div>
            <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 group-hover:scale-105 transition mb-2.5">
              <Boxes className="w-4 h-4" />
            </div>
            <h3 className="font-semibold text-xs text-slate-800 dark:text-slate-100">Concepts & Forms</h3>
            <p className="text-[11px] text-slate-400 mt-1 line-clamp-2">Schema tools, validators, and dictionaries</p>
          </div>
        </Link>
      </div>

      {/* Recent Jobs Table */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <h2 className="text-base font-bold text-slate-800 dark:text-slate-100">Recent Operations</h2>
          <Link to="/jobs" className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 flex items-center gap-1">
            View All Jobs <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
        <div className="divide-y divide-slate-100 dark:divide-slate-800/80">
          {!jobs || jobs.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-400">
              No recent jobs. Launch an operation from the sidebar modules.
            </div>
          ) : (
            jobs.slice(0, 6).map((j) => {
              const concreteAction = (j.action && j.action !== 'general') ? j.action : (j.pipeline || `${j.module}_pipeline`);
              return (
                <div key={j.id} className="p-4 px-6 flex items-center justify-between hover:bg-slate-50/60 dark:hover:bg-slate-800/40 transition">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-500 font-mono text-xs font-bold">
                      {j.id}
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-slate-800 dark:text-slate-200">{concreteAction}</div>
                      <div className="text-xs text-slate-400">Module: {j.module} · {j.created_at?.slice(0, 19).replace('T', ' ')}</div>
                    </div>
                  </div>

                  <div className="flex items-center gap-4">
                    <div className="w-28 hidden sm:block">
                      <div className="h-1.5 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full ${
                            j.status === 'completed'
                              ? 'bg-emerald-500'
                              : j.status === 'running'
                              ? 'bg-blue-500 animate-pulse'
                              : j.status === 'failed'
                              ? 'bg-rose-500'
                              : 'bg-slate-400'
                          }`}
                          style={{ width: `${j.progress || (j.status === 'completed' ? 100 : 0)}%` }}
                        ></div>
                      </div>
                      <div className="text-[10px] text-right text-slate-400 mt-1">{j.progress}%</div>
                    </div>

                    <StatusBadge status={j.status} />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
