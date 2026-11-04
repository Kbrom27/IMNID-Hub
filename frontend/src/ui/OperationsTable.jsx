import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Clock,
  RotateCcw,
  FileText,
  AlertCircle,
  ExternalLink,
} from 'lucide-react';
import StatusBadge from './StatusBadge';
import Tooltip from './Tooltip';

export function formatDateTime(isoString) {
  if (!isoString) return '—';
  let clean = String(isoString).replace('T', ' ');
  if (clean.includes('.')) clean = clean.split('.')[0];
  clean = clean.replace(/(\d{4}-\d{2}-\d{2})(\d{2}:\d{2}:\d{2})/, '$1 $2');
  return clean;
}

export function formatRelativeTime(isoString) {
  if (!isoString) return '—';
  try {
    const date = new Date(isoString);
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - date.getTime()) / 1000);
    if (diffSec < 0 || isNaN(diffSec)) return formatDateTime(isoString);
    if (diffSec < 60) return `${Math.max(1, diffSec)}s ago`;
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  } catch {
    return formatDateTime(isoString);
  }
}

export function formatDuration(startedAt, completedAt) {
  if (!startedAt) return '—';
  try {
    const start = new Date(startedAt).getTime();
    const end = completedAt ? new Date(completedAt).getTime() : Date.now();
    const sec = Math.max(0, Math.floor((end - start) / 1000));
    if (sec < 60) return `${sec}s`;
    const min = Math.floor(sec / 60);
    const remSec = sec % 60;
    return `${min}m ${remSec}s`;
  } catch {
    return '—';
  }
}

/**
 * OperationsTable Component
 * High-legibility recent background jobs monitor with filter chips,
 * wide progress bars, monospace ID chips, and error action summaries.
 */
export const OperationsTable = ({
  jobs = [],
  limit = 8,
  showFilters = true,
  className = '',
}) => {
  const [filter, setFilter] = useState('all'); // 'all' | 'running' | 'completed' | 'failed'

  const filteredJobs = useMemo(() => {
    let list = Array.isArray(jobs) ? jobs : [];
    if (filter !== 'all') {
      list = list.filter((j) => (j.status || '').toLowerCase() === filter);
    }
    return list.slice(0, limit);
  }, [jobs, filter, limit]);

  const counts = useMemo(() => {
    const list = Array.isArray(jobs) ? jobs : [];
    return {
      all: list.length,
      running: list.filter((j) => (j.status || '').toLowerCase() === 'running').length,
      completed: list.filter((j) => (j.status || '').toLowerCase() === 'completed').length,
      failed: list.filter((j) => (j.status || '').toLowerCase() === 'failed').length,
    };
  }, [jobs]);

  return (
    <div className={`space-y-3.5 ${className}`}>
      {/* Table Header & Filter Chips */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-teal-600 dark:text-teal-400" />
          <h2 className="text-base font-bold text-slate-900 dark:text-slate-100">
            Recent Operations
          </h2>
          <span className="text-xs font-mono font-medium text-slate-400 dark:text-slate-500 ml-1">
            ({jobs.length})
          </span>
        </div>

        {showFilters && (
          <div className="flex items-center gap-1.5 flex-wrap">
            {[
              { id: 'all', label: 'All', count: counts.all },
              { id: 'running', label: 'Running', count: counts.running },
              { id: 'completed', label: 'Completed', count: counts.completed },
              { id: 'failed', label: 'Failed', count: counts.failed },
            ].map((tab) => {
              const active = filter === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setFilter(tab.id)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
                    active
                      ? 'bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 shadow-xs'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span
                    className={`font-mono text-[10px] px-1 rounded ${
                      active
                        ? 'bg-white/20 dark:bg-black/20 text-white dark:text-slate-900'
                        : 'bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400'
                    }`}
                  >
                    {tab.count}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Operations List Container */}
      <div className="rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm overflow-hidden">
        {filteredJobs.length === 0 ? (
          <div className="p-10 text-center space-y-2">
            <Clock className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto" />
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              No operations found
            </p>
            <p className="text-xs text-slate-400 dark:text-slate-500">
              {filter === 'all'
                ? 'No background tasks have been executed yet. Launch a pipeline from the modules.'
                : `No operations matching the "${filter}" filter state.`}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800/80">
            {filteredJobs.map((j) => {
              const concreteAction =
                j.action && j.action !== 'general' ? j.action : j.pipeline || `${j.module}_pipeline`;
              const progressPct =
                typeof j.progress === 'number'
                  ? j.progress
                  : j.status === 'completed'
                  ? 100
                  : 0;
              const fullTime = formatDateTime(j.created_at || j.started_at);
              const relTime = formatRelativeTime(j.created_at || j.started_at);
              const duration = formatDuration(j.created_at || j.started_at, j.completed_at);
              const isFailed = j.status === 'failed';
              const errorText = j.error_message || j.error || j.status_message;

              return (
                <div
                  key={j.id}
                  className="p-4 px-5 hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3.5"
                >
                  {/* Left: Monospace ID Chip + Job Name + Module + Timestamps */}
                  <div className="flex items-start gap-3 min-w-0 flex-1">
                    <Tooltip content={`Job ID: ${j.id}`}>
                      <span className="font-mono text-xs font-semibold px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 flex-shrink-0 mt-0.5">
                        {String(j.id).slice(0, 8)}
                      </span>
                    </Tooltip>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {concreteAction}
                        </span>
                        <span className="text-[11px] font-medium px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 capitalize">
                          {j.module || 'Data Hub'}
                        </span>
                      </div>

                      {/* Timestamps with full date on hover */}
                      <div className="flex items-center gap-3 text-xs text-slate-400 dark:text-slate-500 mt-1 font-medium">
                        <Tooltip content={`Started at ${fullTime}`}>
                          <span className="cursor-help flex items-center gap-1">
                            <Clock className="w-3.5 h-3.5 text-slate-400" />
                            <span>{relTime}</span>
                          </span>
                        </Tooltip>
                        <span>·</span>
                        <span className="tabular-nums">Duration: {duration}</span>
                      </div>

                      {/* Truncated Error Summary on Failure */}
                      {isFailed && errorText && (
                        <div className="mt-2 p-2 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-2">
                          <AlertCircle className="w-3.5 h-3.5 text-rose-500 flex-shrink-0 mt-0.5" />
                          <span className="truncate">{errorText}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Right: Wider Progress Bar + Status Badge + Actions */}
                  <div className="flex items-center gap-4 flex-shrink-0 sm:self-center">
                    {/* Progress Bar (min 120px) */}
                    <div className="w-32 hidden md:block">
                      <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 mb-1">
                        <span>Progress</span>
                        <span className="tabular-nums font-semibold">{progressPct}%</span>
                      </div>
                      <div className="h-2 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all duration-300 ${
                            j.status === 'completed'
                              ? 'bg-emerald-500'
                              : j.status === 'running'
                              ? 'bg-teal-500 animate-pulse'
                              : j.status === 'failed'
                              ? 'bg-rose-500'
                              : 'bg-slate-400'
                          }`}
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                    </div>

                    <StatusBadge status={j.status} />

                    {/* View Logs / Job Monitor Action Link */}
                    <Tooltip content="Inspect live logs and job execution details">
                      <Link
                        to={`/jobs?jobId=${j.id}`}
                        className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                        aria-label={`View logs for job ${j.id}`}
                      >
                        <FileText className="w-4 h-4" />
                      </Link>
                    </Tooltip>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Table Footer Link */}
        <div className="px-5 py-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 flex items-center justify-between text-xs">
          <span className="text-slate-500 dark:text-slate-400">
            Showing latest {filteredJobs.length} of {jobs.length} executions
          </span>
          <Link
            to="/jobs"
            className="font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 dark:hover:text-teal-300 flex items-center gap-1.5"
          >
            <span>Open Job Monitor</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
      </div>
    </div>
  );
};

export default OperationsTable;
