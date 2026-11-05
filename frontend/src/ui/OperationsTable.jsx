import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Clock,
  ArrowRight,
  FileText,
  AlertCircle,
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
 * High-legibility recent background jobs monitor conforming to health-tech operations UX:
 * - Monospace used strictly for Job IDs
 * - Normal font with tabular-nums for progress, percentages, durations, timestamps
 * - 160-200px wide progress bar
 * - Percentage hidden on Completed/Failed; visible only on Running
 * - Job ID, module chip, and name clearly separated
 */
export const OperationsTable = ({
  jobs = [],
  title = 'Recent Operations',
  limit = 7,
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
    <div className={`space-y-3.5 ${className}`}>
      {/* Header with Title and Filter Chips */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-base sm:text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
            {title}
          </h2>
          <span className="text-xs font-sans tabular-nums text-slate-500 dark:text-slate-400 font-medium">
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
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 cursor-pointer ${
                    active
                      ? 'bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 shadow-xs'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700'
                  }`}
                >
                  <span>{tab.label}</span>
                  <span
                    className={`font-sans tabular-nums text-xs font-medium px-1.5 py-0.2 rounded-full ${
                      active
                        ? 'bg-white/20 dark:bg-black/20 text-white dark:text-slate-900'
                        : 'bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
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
      <div className="rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs overflow-hidden">
        {filteredJobs.length === 0 ? (
          <div className="p-10 text-center space-y-2">
            <Clock className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto" />
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              No operations found
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
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
              const isRunning = j.status === 'running';
              const errorText = j.error_message || j.error || j.status_message;

              return (
                <div
                  key={j.id}
                  className="p-4 px-5 hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                >
                  {/* Left: Clearly Separated Job ID + Module Chip + Name + Timestamps */}
                  <div className="flex items-start gap-3 min-w-0 flex-1">
                    {/* Job ID: Monospace pill */}
                    <Tooltip content={`Job ID: ${j.id}`}>
                      <span className="font-mono text-xs font-semibold px-2 py-1 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 flex-shrink-0 mt-0.5 select-all">
                        {String(j.id).slice(0, 8)}
                      </span>
                    </Tooltip>

                    <div className="min-w-0 flex-1">
                      {/* Module Chip and Action Name clearly separated */}
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 capitalize flex-shrink-0">
                          {j.module || 'System'}
                        </span>
                        <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                          {concreteAction}
                        </span>
                      </div>

                      {/* Timestamps in normal font with tabular-nums */}
                      <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400 mt-1 font-medium font-sans">
                        <Tooltip content={`Started at ${fullTime}`}>
                          <span className="cursor-help flex items-center gap-1">
                            <Clock className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                            <span className="tabular-nums">{relTime}</span>
                          </span>
                        </Tooltip>
                        <span className="text-slate-300 dark:text-slate-600">·</span>
                        <span className="tabular-nums">Duration: {duration}</span>
                      </div>

                      {/* Error Summary on Failure */}
                      {isFailed && errorText && (
                        <div className="mt-2 p-2 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-2 font-medium">
                          <AlertCircle className="w-3.5 h-3.5 text-rose-500 flex-shrink-0 mt-0.5" />
                          <span className="truncate">{errorText}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Right: Progress Bar (176px wide) + Status Badge + Action */}
                  <div className="flex items-center gap-4 flex-shrink-0 sm:self-center">
                    {/* Widen progress bar to 176-192px (w-44 / w-48) */}
                    <div className="w-44 lg:w-48 hidden md:block">
                      <div className="flex items-center justify-between text-xs font-sans text-slate-600 dark:text-slate-400 mb-1">
                        <span className="font-medium">Progress</span>
                        {/* Hide percentage on Completed/Failed; show ONLY for Running */}
                        {isRunning && (
                          <span className="tabular-nums font-semibold text-teal-600 dark:text-teal-400">
                            {progressPct}%
                          </span>
                        )}
                      </div>
                      <div className="h-2 w-full bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all duration-300 ${
                            j.status === 'completed'
                              ? 'bg-emerald-500'
                              : isRunning
                              ? 'bg-teal-500 animate-pulse'
                              : isFailed
                              ? 'bg-rose-500'
                              : 'bg-slate-400'
                          }`}
                          style={{ width: `${progressPct}%` }}
                        />
                      </div>
                    </div>

                    <StatusBadge status={j.status} />

                    {/* View Logs Action Link */}
                    <Tooltip content="Inspect live logs and job execution details">
                      <Link
                        to={`/jobs?jobId=${j.id}`}
                        className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
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
