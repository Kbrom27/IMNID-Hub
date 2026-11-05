import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Clock,
  ArrowRight,
  FileText,
  AlertCircle,
  RotateCw,
} from 'lucide-react';
import StatusBadge from './StatusBadge';
import Tooltip from './Tooltip';

/**
 * Format timestamp into relative display string
 */
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

/**
 * Format timestamp into exact human-readable date & time
 */
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

/**
 * Calculate operation duration
 */
function formatDuration(startIso, endIso) {
  if (!startIso) return '-';
  try {
    const start = new Date(startIso).getTime();
    const end = endIso ? new Date(endIso).getTime() : Date.now();
    const durationSec = Math.max(0, Math.floor((end - start) / 1000));
    if (durationSec < 60) return `${durationSec}s`;
    const min = Math.floor(durationSec / 60);
    const sec = durationSec % 60;
    return `${min}m ${sec}s`;
  } catch {
    return '-';
  }
}

/**
 * OperationsTable Component
 * High-legibility recent background jobs monitor conforming to Section B criteria:
 * - Fixed-width grid for status badge, progress bar, and actions so rows align perfectly
 * - Repeated "Progress" label removed
 * - Cancelled jobs show neutral gray bar (never full green)
 * - Failed jobs show one-line truncated error plus Retry and Logs buttons
 */
export const OperationsTable = ({
  jobs = [],
  title = 'Recent Operations',
  limit = 8,
  showFilters = true,
  className = '',
}) => {
  const [filter, setFilter] = useState('all');

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
    <div className={`space-y-3 ${className}`}>
      {/* Header with Title and Filter Chips */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100 tracking-tight">
            {title}
          </h2>
          <span className="text-xs font-sans tabular-nums font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700">
            {jobs.length}
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
        )}
      </div>

      {/* Operations List Container (~48px per row, no inline errors, 8 rows) */}
      <div className="rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xs overflow-hidden">
        {filteredJobs.length === 0 ? (
          <div className="p-8 text-center space-y-1">
            <Clock className="w-6 h-6 text-slate-300 dark:text-slate-600 mx-auto" />
            <p className="text-xs font-semibold text-slate-700 dark:text-slate-300">
              No operations found
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800/80">
            {filteredJobs.map((j) => {
              const concreteAction =
                j.action && j.action !== 'general' ? j.action : j.pipeline || `${j.module}_pipeline`;
              const isFailed = (j.status || '').toLowerCase() === 'failed';
              const isRunning = (j.status || '').toLowerCase() === 'running';
              const isCompleted = (j.status || '').toLowerCase() === 'completed';
              const isCancelled = (j.status || '').toLowerCase() === 'cancelled' || (j.status || '').toLowerCase() === 'canceled';

              const progressPct =
                typeof j.progress === 'number'
                  ? j.progress
                  : isCompleted
                  ? 100
                  : isCancelled
                  ? 100
                  : 0;

              const relTime = formatRelativeTime(j.created_at || j.started_at);
              const duration = formatDuration(j.created_at || j.started_at, j.completed_at);

              return (
                <div
                  key={j.id}
                  className="px-3.5 py-2 min-h-[48px] hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors flex items-center justify-between gap-3 text-xs"
                >
                  {/* Left: ID chip + Module chip + Action name */}
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <Tooltip content={`Job ID: ${j.id}`}>
                      <span className="font-mono text-xs font-semibold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 flex-shrink-0 select-all">
                        {String(j.id).slice(0, 8)}
                      </span>
                    </Tooltip>

                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 capitalize flex-shrink-0 hidden sm:inline">
                      {j.module || 'System'}
                    </span>

                    <span className="font-medium text-sm text-slate-900 dark:text-slate-100 truncate">
                      {concreteAction}
                    </span>
                  </div>

                  {/* Right: Time + Duration + Progress bar + Status Badge + Actions */}
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className="font-sans tabular-nums text-xs text-slate-500 dark:text-slate-400 hidden md:inline">
                      {relTime}
                    </span>

                    <span className="font-sans tabular-nums text-xs font-medium text-slate-700 dark:text-slate-300 w-16 text-right hidden sm:inline">
                      {duration}
                    </span>

                    {/* Progress Bar (compact 80-100px) */}
                    <div className="w-20 sm:w-24 hidden lg:block">
                      <div className="h-1.5 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all duration-300 ${
                            isCompleted
                              ? 'bg-emerald-500'
                              : isRunning
                              ? 'bg-teal-500 animate-pulse'
                              : isFailed
                              ? 'bg-rose-500'
                              : 'bg-slate-400 dark:bg-slate-500'
                          }`}
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                    </div>

                    {/* Status Badge */}
                    <div className="w-[85px] flex justify-center">
                      <StatusBadge status={j.status} />
                    </div>

                    {/* Actions: Retry + Logs */}
                    <div className="flex items-center gap-1">
                      {isFailed && (
                        <Tooltip content="Retry this failed operation in Job Monitor">
                          <Link
                            to={`/jobs?jobId=${j.id}&action=retry`}
                            className="p-1 rounded-md border border-teal-200 dark:border-teal-800 text-teal-700 dark:text-teal-300 hover:bg-teal-50 dark:hover:bg-teal-950/60 transition-colors cursor-pointer"
                            aria-label={`Retry job ${j.id}`}
                          >
                            <RotateCw className="w-3.5 h-3.5" />
                          </Link>
                        </Tooltip>
                      )}

                      <Tooltip content="Inspect live logs in Job Monitor">
                        <Link
                          to={`/jobs?jobId=${j.id}`}
                          className="p-1 rounded-md border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
                          aria-label={`View logs for job ${j.id}`}
                        >
                          <FileText className="w-3.5 h-3.5" />
                        </Link>
                      </Tooltip>
                    </div>

                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Table Footer Link */}
        <div className="px-4 py-2 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 flex items-center justify-between text-xs">
          <span className="text-slate-500 dark:text-slate-400 font-sans tabular-nums font-medium">
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
