import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useAuth } from '../context/AuthContext';
import {
  RotateCcw,
  Terminal,
  Download,
  X,
  StopCircle,
  Search,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  RotateCw,
  FileText,
  Clock,
} from 'lucide-react';
import { PageHeader, StatusBadge, Tooltip } from '../ui';

function formatRelativeTime(isoString) {
  if (!isoString) return 'Just now';
  try {
    const diffSec = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
    if (diffSec < 60) return `${Math.max(1, diffSec)}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
  } catch {
    return 'Recently';
  }
}

function formatDateTime(isoString) {
  if (!isoString) return 'N/A';
  try {
    const d = new Date(isoString);
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return isoString;
  }
}

function formatDuration(startIso, endIso) {
  if (!startIso) return '—';
  try {
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    const durationSec = Math.max(0, Math.floor((end - start) / 1000));
    if (durationSec < 60) return `${durationSec}s`;
    const min = Math.floor(durationSec / 60);
    const sec = durationSec % 60;
    return `${min}m ${sec}s`;
  } catch {
    return '—';
  }
}

export const JobHistory = () => {
  const { authHeader, isViewer } = useAuth();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterModule, setFilterModule] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [pageSize, setPageSize] = useState(15);
  const [expandedErrorRow, setExpandedErrorRow] = useState(null);

  // Telemetry refresh age
  const [lastRefreshedAt, setLastRefreshedAt] = useState(Date.now());
  const [secondsAgo, setSecondsAgo] = useState(0);

  // Active Streaming Log modal
  const [activeJob, setActiveJob] = useState(null);
  const [liveLogs, setLiveLogs] = useState([]);
  const [liveState, setLiveState] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const terminalEndRef = useRef(null);
  const eventSourceRef = useRef(null);

  const fetchJobs = async () => {
    setLoading(true);
    try {
      const url = filterModule ? `/api/jobs?module=${filterModule}&limit=100` : '/api/jobs?limit=100';
      const res = await fetch(url, { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setJobs(data.jobs || []);
        setLastRefreshedAt(Date.now());
        setSecondsAgo(0);
      }
    } catch (e) {
      console.error('Failed to fetch jobs:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchJobs();
    const timer = setInterval(fetchJobs, 12000);
    return () => clearInterval(timer);
  }, [filterModule]);

  // Seconds ago tracker
  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsAgo(Math.floor((Date.now() - lastRefreshedAt) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [lastRefreshedAt]);

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [liveLogs]);

  // Filtered and searched jobs
  const filteredJobs = useMemo(() => {
    return jobs.filter((j) => {
      const status = (j.status || '').toLowerCase();
      if (filterStatus === 'completed' && status !== 'completed') return false;
      if (filterStatus === 'failed' && status !== 'failed') return false;
      if (filterStatus === 'running' && status !== 'running') return false;
      if (filterStatus === 'cancelled' && status !== 'cancelled' && status !== 'canceled') return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const idMatch = String(j.id || '').toLowerCase().includes(q);
        const actionMatch = String(j.action || '').toLowerCase().includes(q);
        const pipeMatch = String(j.pipeline || '').toLowerCase().includes(q);
        const modMatch = String(j.module || '').toLowerCase().includes(q);
        if (!idMatch && !actionMatch && !pipeMatch && !modMatch) return false;
      }
      return true;
    });
  }, [jobs, filterStatus, searchQuery]);

  const visibleJobs = useMemo(() => {
    return filteredJobs.slice(0, pageSize);
  }, [filteredJobs, pageSize]);

  // Counts by status
  const counts = useMemo(() => {
    return {
      all: jobs.length,
      running: jobs.filter((j) => (j.status || '').toLowerCase() === 'running').length,
      completed: jobs.filter((j) => (j.status || '').toLowerCase() === 'completed').length,
      failed: jobs.filter((j) => (j.status || '').toLowerCase() === 'failed').length,
      cancelled: jobs.filter((j) => {
        const s = (j.status || '').toLowerCase();
        return s === 'cancelled' || s === 'canceled';
      }).length,
    };
  }, [jobs]);

  const openLogViewer = (job) => {
    setActiveJob(job);
    setLiveLogs([]);
    setLiveState(job);
    startStream(job.id);
  };

  const closeLogViewer = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setActiveJob(null);
    setIsStreaming(false);
    fetchJobs();
  };

  const startStream = (jobId) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setIsStreaming(true);
    const es = new EventSource(`/api/jobs/${jobId}/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data);
        if (parsed.type === 'log') {
          setLiveLogs((prev) => [...prev, parsed.data]);
        } else if (parsed.type === 'state') {
          setLiveState(parsed.data);
          if (['completed', 'failed', 'canceled'].includes(parsed.data.status)) {
            setIsStreaming(false);
          }
        }
      } catch (e) {
        console.error(e);
      }
    };

    es.onerror = () => {
      setIsStreaming(false);
      es.close();
    };
  };

  const cancelJob = async (jobId) => {
    try {
      await fetch(`/api/jobs/${jobId}/cancel`, {
        method: 'POST',
        headers: authHeader(),
      });
      fetchJobs();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="space-y-6 w-full">
      {/* 1. Shared PageHeader without subtitle */}
      <PageHeader
        title="Job Monitor"
        breadcrumbs={[{ label: 'Overview', to: '/' }, { label: 'Job Monitor' }]}
        actions={
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-sans tabular-nums hidden sm:inline">
              {secondsAgo}s ago
            </span>
            <button
              type="button"
              onClick={fetchJobs}
              disabled={loading}
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-750 text-slate-700 dark:text-slate-200 text-sm font-semibold shadow-2xs transition-colors cursor-pointer"
              title="Refresh job executions list"
            >
              <RotateCcw className={`w-4 h-4 ${loading ? 'animate-spin text-teal-600' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        }
      />

      {/* 2. Compact Filter Bar: Status Chips + Module Chips + Search in one tight container */}
      <div className="bg-white dark:bg-slate-900 p-3 rounded-xl border border-slate-200/90 dark:border-slate-800 shadow-2xs space-y-2.5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5">
          {/* Status Filter Chips */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {[
              { id: 'all', label: 'All', count: counts.all },
              { id: 'running', label: 'Running', count: counts.running },
              { id: 'completed', label: 'Completed', count: counts.completed },
              { id: 'failed', label: 'Failed', count: counts.failed },
              { id: 'cancelled', label: 'Cancelled', count: counts.cancelled },
            ].map((tab) => {
              const active = filterStatus === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setFilterStatus(tab.id)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 cursor-pointer ${
                    active
                      ? 'bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 shadow-2xs'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span
                    className={`font-sans tabular-nums text-xs font-semibold px-1.5 py-0.2 rounded-full ${
                      active
                        ? 'bg-white/20 dark:bg-black/20 text-white dark:text-slate-900'
                        : 'bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
                    }`}
                  >
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Search Box */}
          <div className="relative w-full md:w-64">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search ID, action, module..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/80 text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-1 focus:ring-teal-500"
            />
          </div>
        </div>

        {/* Module Filter Chips without 'Filter Module:' label per Section B9 */}
        <div className="flex items-center gap-1 flex-wrap pt-1 border-t border-slate-100 dark:border-slate-800 text-xs">
          {['', 'system', 'smartcare', 'data-management', 'interop', 'concepts', 'hmis'].map((mod) => (
            <button
              key={mod}
              type="button"
              onClick={() => setFilterModule(mod)}
              className={`px-2 py-0.5 rounded-md text-xs font-semibold transition-colors cursor-pointer ${
                filterModule === mod
                  ? 'bg-teal-500/15 text-teal-700 dark:text-teal-300 border border-teal-500/30'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
            >
              {mod === '' ? 'All Modules' : mod}
            </button>
          ))}
        </div>
      </div>

      {/* 3. Jobs Table with Sticky Header */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200/90 dark:border-slate-800 shadow-xs overflow-hidden">
        <div className="overflow-x-auto max-h-[620px]">
          <table className="w-full text-left border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-slate-50 dark:bg-slate-800/95 backdrop-blur-xs border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 font-bold uppercase tracking-wider text-[11px]">
              <tr>
                <th className="py-3 px-4">Job ID</th>
                <th className="py-3 px-4">Action / Pipeline</th>
                <th className="py-3 px-4">Module</th>
                <th className="py-3 px-4 text-center">Status</th>
                <th className="py-3 px-4">Progress</th>
                <th className="py-3 px-4">Started</th>
                <th className="py-3 px-4">Duration</th>
                <th className="py-3 px-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/80">
              {visibleJobs.length === 0 ? (
                <tr>
                  <td colSpan="8" className="py-12 text-center text-slate-400">
                    No job executions match the current filters.
                  </td>
                </tr>
              ) : (
                visibleJobs.map((j) => {
                  const concreteAction =
                    j.action && j.action !== 'general' ? j.action : j.pipeline || `${j.module}_pipeline`;
                  const isFailed = (j.status || '').toLowerCase() === 'failed';
                  const isRunning = (j.status || '').toLowerCase() === 'running';
                  const isCompleted = (j.status || '').toLowerCase() === 'completed';
                  const isCancelled =
                    (j.status || '').toLowerCase() === 'cancelled' ||
                    (j.status || '').toLowerCase() === 'canceled';

                  const progressPct =
                    typeof j.progress === 'number'
                      ? j.progress
                      : isCompleted
                      ? 100
                      : isCancelled
                      ? 100
                      : 0;

                  const fullTime = formatDateTime(j.created_at || j.started_at);
                  const relTime = formatRelativeTime(j.created_at || j.started_at);
                  const duration = formatDuration(j.created_at || j.started_at, j.completed_at);
                  const errorText = j.error_message || j.error || j.status_message;
                  const isErrorExpanded = expandedErrorRow === j.id;

                  return (
                    <React.Fragment key={j.id}>
                      <tr className="hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors">
                        {/* Job ID: Monospace strictly */}
                        <td className="py-3 px-4 font-mono font-semibold text-slate-700 dark:text-slate-300 select-all">
                          {String(j.id).slice(0, 8)}
                        </td>

                        {/* Action / Pipeline Name */}
                        <td className="py-3 px-4 font-semibold text-slate-900 dark:text-slate-100">
                          <div>{concreteAction}</div>
                          {isFailed && errorText && (
                            <button
                              type="button"
                              onClick={() => setExpandedErrorRow(isErrorExpanded ? null : j.id)}
                              className="mt-0.5 inline-flex items-center gap-1 text-[11px] text-rose-600 dark:text-rose-400 hover:underline font-medium"
                            >
                              <span>View error summary</span>
                              {isErrorExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                            </button>
                          )}
                        </td>

                        {/* Module Chip (Normal font) */}
                        <td className="py-3 px-4">
                          <span className="px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-semibold border border-slate-200 dark:border-slate-700 capitalize text-xs">
                            {j.module || 'System'}
                          </span>
                        </td>

                        {/* Status Badge */}
                        <td className="py-3 px-4 text-center">
                          <StatusBadge status={j.status} />
                        </td>

                        {/* Progress Bar (Normal font with tabular-nums) */}
                        <td className="py-3 px-4">
                          <div className="w-28">
                            {isRunning && (
                              <div className="text-right text-[11px] font-sans tabular-nums font-semibold text-teal-600 dark:text-teal-400 mb-0.5">
                                {progressPct}%
                              </div>
                            )}
                            <div className="h-2 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                              <div
                                className={`h-full transition-all duration-300 ${
                                  isCompleted
                                    ? 'bg-emerald-500'
                                    : isRunning
                                    ? 'bg-teal-500 animate-pulse'
                                    : isFailed
                                    ? 'bg-rose-500'
                                    : isCancelled
                                    ? 'bg-slate-400 dark:bg-slate-600' // neutral gray for cancelled
                                    : 'bg-slate-400'
                                }`}
                                style={{ width: `${progressPct}%` }}
                              />
                            </div>
                          </div>
                        </td>

                        {/* Started Time (Normal font with full timestamp tooltip) */}
                        <td className="py-3 px-4 text-slate-600 dark:text-slate-300 font-sans tabular-nums">
                          <Tooltip content={`Started at ${fullTime}`}>
                            <span className="cursor-help flex items-center gap-1">
                              <Clock className="w-3.5 h-3.5 text-slate-400" />
                              <span>{relTime}</span>
                            </span>
                          </Tooltip>
                        </td>

                        {/* Duration */}
                        <td className="py-3 px-4 text-slate-600 dark:text-slate-400 font-sans tabular-nums">
                          {duration}
                        </td>

                        {/* Row Actions */}
                        <td className="py-3 px-4 text-right space-x-1.5 whitespace-nowrap">
                          {isFailed && (
                            <Tooltip content="Retry this pipeline">
                              <button
                                type="button"
                                onClick={() => openLogViewer(j)}
                                className="px-2 py-1 text-xs font-semibold text-teal-700 dark:text-teal-300 bg-teal-50 dark:bg-teal-950/40 hover:bg-teal-100 dark:hover:bg-teal-900/60 border border-teal-200 dark:border-teal-800 rounded transition"
                              >
                                <RotateCw className="w-3.5 h-3.5" />
                              </button>
                            </Tooltip>
                          )}

                          <button
                            type="button"
                            onClick={() => openLogViewer(j)}
                            className="px-2.5 py-1 text-xs font-semibold text-slate-700 dark:text-slate-200 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-200 dark:border-slate-700 rounded transition cursor-pointer"
                          >
                            Logs
                          </button>

                          {isRunning && !isViewer && (
                            <button
                              type="button"
                              onClick={() => cancelJob(j.id)}
                              className="px-2.5 py-1 text-xs font-semibold text-rose-700 dark:text-rose-300 bg-rose-50 dark:bg-rose-950/40 hover:bg-rose-100 dark:hover:bg-rose-900/60 border border-rose-200 dark:border-rose-800 rounded transition cursor-pointer"
                            >
                              Cancel
                            </button>
                          )}
                        </td>
                      </tr>

                      {/* Expandable Error Summary Drawer */}
                      {isFailed && isErrorExpanded && (
                        <tr className="bg-rose-50/50 dark:bg-rose-950/20">
                          <td colSpan="8" className="p-4 border-t border-rose-100 dark:border-rose-900/60">
                            <div className="flex items-start gap-2.5 text-xs text-rose-700 dark:text-rose-300">
                              <AlertCircle className="w-4 h-4 text-rose-500 flex-shrink-0 mt-0.5" />
                              <div className="space-y-1 min-w-0">
                                <span className="font-bold">Failure Details:</span>
                                <p className="font-mono text-xs bg-white/70 dark:bg-slate-900/80 p-2.5 rounded border border-rose-200 dark:border-rose-900/80 break-all select-all">
                                  {errorText || 'No diagnostic message returned by worker process'}
                                </p>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Table Footer with Load More / Pagination */}
        <div className="px-5 py-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs">
          <span className="text-slate-500 dark:text-slate-400 font-sans tabular-nums font-medium">
            Showing {visibleJobs.length} of {filteredJobs.length} matching jobs ({jobs.length} total)
          </span>

          {visibleJobs.length < filteredJobs.length && (
            <button
              type="button"
              onClick={() => setPageSize((prev) => prev + 15)}
              className="px-3.5 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-750 font-semibold transition cursor-pointer"
            >
              Load More Executions ({filteredJobs.length - visibleJobs.length} remaining)
            </button>
          )}
        </div>
      </div>

      {/* 4. Streaming Log Modal */}
      {activeJob && (
        <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden text-slate-200 animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="px-6 py-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Terminal className="w-5 h-5 text-teal-400" />
                <div>
                  <h3 className="font-bold text-sm text-white">
                    {liveState?.action || activeJob.action}
                  </h3>
                  <p className="text-xs text-slate-400 font-mono">Job ID: {activeJob.id} · Module: {activeJob.module}</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {liveState?.status === 'running' && !isViewer && (
                  <button
                    onClick={() => cancelJob(activeJob.id)}
                    className="flex items-center gap-1 px-3 py-1 bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 rounded-lg text-xs font-semibold transition"
                  >
                    <StopCircle className="w-3.5 h-3.5" />
                    <span>Cancel</span>
                  </button>
                )}

                <a
                  href={`/api/jobs/${activeJob.id}/logs`}
                  download
                  className="flex items-center gap-1 px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 rounded-lg text-xs font-medium transition"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download</span>
                </a>

                <button
                  onClick={closeLogViewer}
                  className="p-1 text-slate-400 hover:text-white rounded transition"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Progress Bar Header */}
            <div className="px-6 py-3 bg-slate-950/50 border-b border-slate-800/80 flex items-center justify-between text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-slate-400">Status:</span>
                <span className="font-bold uppercase text-teal-400">{liveState?.status || activeJob.status}</span>
                <span className="text-slate-500">·</span>
                <span className="text-slate-300">{liveState?.message || 'Processing...'}</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-36 h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-teal-400 transition-all duration-300"
                    style={{ width: `${liveState?.progress || 0}%` }}
                  ></div>
                </div>
                <span className="font-sans tabular-nums text-teal-400 font-bold">{liveState?.progress || 0}%</span>
              </div>
            </div>

            {/* Terminal Window */}
            <div className="flex-1 overflow-y-auto p-6 font-mono text-xs bg-slate-950 space-y-1 select-text">
              {liveLogs.length === 0 ? (
                <div className="text-slate-500 italic">Waiting for log stream events...</div>
              ) : (
                liveLogs.map((item, idx) => (
                  <div key={idx} className="flex items-start gap-2 leading-relaxed">
                    <span className="text-slate-600 select-none">[{item.timestamp}]</span>
                    <span
                      className={
                        item.level === 'ERROR'
                          ? 'text-rose-400 font-bold'
                          : item.level === 'WARN'
                          ? 'text-amber-400'
                          : 'text-teal-400'
                      }
                    >
                      [{item.level}]
                    </span>
                    <span className="text-slate-300 break-all">{item.text}</span>
                  </div>
                ))
              )}
              <div ref={terminalEndRef} />
            </div>

            {/* Footer */}
            <div className="px-6 py-2.5 bg-slate-950 border-t border-slate-800/80 text-xs text-slate-500 flex items-center justify-between font-sans">
              <span>Streaming via Server-Sent Events (SSE)</span>
              {isStreaming ? (
                <span className="flex items-center gap-1.5 text-teal-400 font-medium">
                  <span className="w-2 h-2 rounded-full bg-teal-400 animate-pulse"></span>
                  Active Stream
                </span>
              ) : (
                <span className="text-slate-400">Stream Closed</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default JobHistory;
