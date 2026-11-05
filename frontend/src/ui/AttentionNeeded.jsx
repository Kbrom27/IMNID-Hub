import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  XCircle,
  RefreshCw,
  ArrowRight,
  X,
  FileText,
  RotateCw,
} from 'lucide-react';

/**
 * AttentionNeeded Component
 * Refined operational warning bar conforming to health-tech cockpit requirements:
 * - Single-line compact summary by default
 * - Scoped issue counting per type (unreachable servers vs recent job failures)
 * - Review and Dismiss controls
 * - When expanded: max 3 items per section, retry action, short error summaries, and "View all" links
 * - Keeps layout above the fold at 1080p
 */
export const AttentionNeeded = ({
  offlineServers = [],
  failedJobs = [],
  onTestServer,
  onRetryJob,
  className = '',
}) => {
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;
  if (offlineServers.length === 0 && failedJobs.length === 0) return null;

  return (
    <div
      className={`rounded-xl border border-amber-200 dark:border-amber-800/80 bg-amber-50/80 dark:bg-amber-950/25 shadow-xs overflow-hidden transition-all duration-200 ${className}`}
    >
      {/* 1. Single-Line Compact Summary Bar */}
      <div className="px-4 py-2.5 flex items-center justify-between gap-3 text-xs sm:text-sm">
        <div className="flex items-center gap-2.5 min-w-0 flex-1">
          <div className="w-6 h-6 rounded-md bg-amber-100 dark:bg-amber-900/60 flex items-center justify-center text-amber-700 dark:text-amber-400 flex-shrink-0">
            <AlertTriangle className="w-3.5 h-3.5" />
          </div>

          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            <span className="font-bold text-amber-900 dark:text-amber-200 flex-shrink-0">
              Attention Needed:
            </span>

            <div className="flex items-center gap-1.5 flex-wrap text-xs text-amber-800 dark:text-amber-300">
              {offlineServers.length > 0 && (
                <span>
                  <strong className="font-bold text-rose-700 dark:text-rose-400 tabular-nums">
                    {offlineServers.length}
                  </strong>{' '}
                  server{offlineServers.length > 1 ? 's' : ''} unreachable
                </span>
              )}

              {offlineServers.length > 0 && failedJobs.length > 0 && (
                <span className="text-amber-400 dark:text-amber-600 font-bold">·</span>
              )}

              {failedJobs.length > 0 && (
                <span>
                  <strong className="font-bold text-rose-700 dark:text-rose-400 tabular-nums">
                    {failedJobs.length}
                  </strong>{' '}
                  recent job failure{failedJobs.length > 1 ? 's' : ''}{' '}
                  <span className="text-amber-700/80 dark:text-amber-400/80 font-normal">
                    (last 50 jobs)
                  </span>
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Compact Right Controls: Review (Expand) & Dismiss */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            type="button"
            onClick={() => setExpanded((prev) => !prev)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-white dark:bg-slate-900 text-amber-800 dark:text-amber-300 border border-amber-300/80 dark:border-amber-700/80 hover:bg-amber-100/50 dark:hover:bg-slate-800 transition-colors cursor-pointer"
            aria-expanded={expanded}
          >
            <span>{expanded ? 'Collapse' : 'Review'}</span>
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>

          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="p-1 text-amber-600 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-200 rounded hover:bg-amber-100/60 dark:hover:bg-slate-800 transition-colors"
            title="Dismiss warning for this session"
            aria-label="Dismiss warning"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* 2. Expanded Detail Drawer (Max 3 items per section + View all) */}
      {expanded && (
        <div className="px-4 pb-3.5 pt-2 border-t border-amber-200/80 dark:border-amber-800/60 space-y-3 text-xs animate-in fade-in duration-150">
          {/* Section A: Unreachable Servers (max 3) */}
          {offlineServers.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-amber-900 dark:text-amber-200 uppercase tracking-wide">
                  Unreachable Endpoints ({offlineServers.length} target{offlineServers.length > 1 ? 's' : ''} offline)
                </span>
                {offlineServers.length > 3 && (
                  <Link
                    to="/settings"
                    className="font-semibold text-teal-700 dark:text-teal-400 hover:underline"
                  >
                    View all {offlineServers.length} in Settings →
                  </Link>
                )}
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                {offlineServers.slice(0, 3).map((s) => (
                  <div
                    key={s.key}
                    className="p-2.5 rounded-lg bg-white dark:bg-slate-900 border border-amber-200/80 dark:border-amber-800/80 flex items-center justify-between gap-2 shadow-xs"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="font-semibold text-xs text-slate-900 dark:text-slate-100 flex items-center gap-1.5">
                        <XCircle className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />
                        <span className="truncate">{s.name}</span>
                      </div>
                      <div className="font-mono text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                        {s.effectiveUrl || 'Not configured'}
                      </div>
                    </div>
                    {onTestServer && (
                      <button
                        type="button"
                        onClick={() => onTestServer(s.key)}
                        className="px-2 py-1 text-xs font-semibold text-teal-700 dark:text-teal-300 hover:bg-teal-50 dark:hover:bg-teal-950/50 rounded border border-teal-200 dark:border-teal-800 flex items-center gap-1 flex-shrink-0 cursor-pointer"
                        title={`Retry connection to ${s.name}`}
                      >
                        <RefreshCw className="w-3 h-3" />
                        <span>Retry</span>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Section B: Failed Background Operations (max 3) */}
          {failedJobs.length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-amber-900 dark:text-amber-200 uppercase tracking-wide">
                  Recent Failed Operations ({failedJobs.length} failed in last 50 jobs)
                </span>
                {failedJobs.length > 3 && (
                  <Link
                    to="/jobs"
                    className="font-semibold text-teal-700 dark:text-teal-400 hover:underline"
                  >
                    View all {failedJobs.length} in Job Monitor →
                  </Link>
                )}
              </div>

              <div className="space-y-1.5">
                {failedJobs.slice(0, 3).map((j) => {
                  const errorSummary =
                    j.error_message || j.error || j.status_message || 'Pipeline execution interrupted or failed';
                  const actionName =
                    j.action && j.action !== 'general' ? j.action : j.pipeline || `${j.module}_pipeline`;

                  return (
                    <div
                      key={j.id}
                      className="p-2.5 rounded-lg bg-white dark:bg-slate-900 border border-amber-200/80 dark:border-amber-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-2 shadow-xs"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono text-xs font-semibold bg-rose-100 dark:bg-rose-950/70 text-rose-700 dark:text-rose-300 px-1.5 py-0.5 rounded border border-rose-200 dark:border-rose-900">
                            {String(j.id).slice(0, 8)}
                          </span>
                          <span className="font-semibold text-xs text-slate-900 dark:text-slate-100 truncate">
                            {actionName}
                          </span>
                          <span className="text-xs font-medium px-2 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 capitalize">
                            {j.module || 'System'}
                          </span>
                        </div>

                        {/* Short Error Summary */}
                        <p className="text-xs text-rose-600 dark:text-rose-400 font-medium truncate mt-1">
                          {errorSummary}
                        </p>
                      </div>

                      {/* Row Actions: Retry and Logs */}
                      <div className="flex items-center gap-2 flex-shrink-0 self-end sm:self-center">
                        <Link
                          to={`/jobs?jobId=${j.id}`}
                          className="px-2.5 py-1 text-xs font-semibold text-teal-700 dark:text-teal-300 hover:bg-teal-50 dark:hover:bg-teal-950/50 rounded border border-teal-200 dark:border-teal-800 flex items-center gap-1.5 transition-colors"
                          title="Open job in Job Monitor to retry or restart"
                        >
                          <RotateCw className="w-3 h-3 text-teal-600 dark:text-teal-400" />
                          <span>Retry</span>
                        </Link>

                        <Link
                          to={`/jobs?jobId=${j.id}`}
                          className="px-2.5 py-1 text-xs font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded border border-slate-200 dark:border-slate-700 flex items-center gap-1.5 transition-colors"
                        >
                          <FileText className="w-3 h-3 text-slate-400" />
                          <span>Logs</span>
                        </Link>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Bottom Direct Links */}
          <div className="pt-1 flex items-center justify-between text-xs text-amber-900 dark:text-amber-200 font-semibold border-t border-amber-200/60 dark:border-amber-800/60">
            <Link to="/settings" className="hover:underline flex items-center gap-1">
              Verify Endpoint Credentials in Settings →
            </Link>
            <Link to="/jobs" className="hover:underline flex items-center gap-1">
              Inspect Failed Operations in Job Monitor →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
};

export default AttentionNeeded;
