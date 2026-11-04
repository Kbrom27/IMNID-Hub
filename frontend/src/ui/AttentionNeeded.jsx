import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Server,
  XCircle,
  RefreshCw,
  ArrowRight,
  ShieldAlert,
} from 'lucide-react';
import Button from './Button';

/**
 * AttentionNeeded Component
 * Collapsible operational warning strip rendered ONLY when there are
 * offline configured servers or failed background operations.
 */
export const AttentionNeeded = ({
  offlineServers = [],
  failedJobs = [],
  onTestServer,
  className = '',
}) => {
  const [collapsed, setCollapsed] = useState(false);

  const totalIssues = offlineServers.length + failedJobs.length;
  if (totalIssues === 0) return null;

  return (
    <div
      className={`rounded-xl border border-amber-200 dark:border-amber-800/80 bg-amber-50/70 dark:bg-amber-950/20 shadow-xs overflow-hidden transition-all ${className}`}
    >
      {/* Header bar */}
      <div
        className="px-4 py-3 flex items-center justify-between gap-3 cursor-pointer select-none"
        onClick={() => setCollapsed((prev) => !prev)}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-7 h-7 rounded-lg bg-amber-100 dark:bg-amber-900/50 flex items-center justify-center text-amber-700 dark:text-amber-400 flex-shrink-0">
            <AlertTriangle className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-amber-900 dark:text-amber-200 truncate">
              Attention Needed: {totalIssues} issue{totalIssues > 1 ? 's' : ''} detected
            </h3>
            <p className="text-xs text-amber-700 dark:text-amber-300/80 truncate">
              {offlineServers.length > 0 && `${offlineServers.length} server${offlineServers.length > 1 ? 's' : ''} unreachable`}
              {offlineServers.length > 0 && failedJobs.length > 0 && ' · '}
              {failedJobs.length > 0 && `${failedJobs.length} job execution failure${failedJobs.length > 1 ? 's' : ''}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            type="button"
            className="p-1 text-amber-700 dark:text-amber-300 hover:text-amber-900 rounded"
            aria-label={collapsed ? 'Expand issues' : 'Collapse issues'}
          >
            {collapsed ? <ChevronDown className="w-4 h-4" /> : <ChevronUp className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Expanded items */}
      {!collapsed && (
        <div className="px-4 pb-3.5 pt-1 border-t border-amber-200/60 dark:border-amber-800/60 space-y-2.5 text-xs">
          {/* Offline Servers */}
          {offlineServers.length > 0 && (
            <div className="space-y-1.5">
              <span className="text-[11px] font-semibold text-amber-800 dark:text-amber-300 uppercase tracking-[0.04em]">
                Unreachable Endpoints
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {offlineServers.map((s) => (
                  <div
                    key={s.key}
                    className="p-2.5 rounded-lg bg-white/90 dark:bg-slate-900/90 border border-amber-200/80 dark:border-amber-800/60 flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0 truncate">
                      <div className="font-semibold text-xs text-slate-800 dark:text-slate-100 flex items-center gap-1.5">
                        <XCircle className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />
                        <span className="truncate">{s.name}</span>
                      </div>
                      <div className="font-mono text-[10px] text-slate-400 truncate mt-0.5">
                        {s.effectiveUrl || 'Not configured'}
                      </div>
                    </div>
                    {onTestServer && (
                      <button
                        type="button"
                        onClick={() => onTestServer(s.key)}
                        className="px-2 py-1 text-[11px] font-semibold text-teal-700 dark:text-teal-300 hover:bg-teal-50 dark:hover:bg-teal-950/50 rounded border border-teal-200 dark:border-teal-800 flex items-center gap-1 flex-shrink-0"
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

          {/* Failed Jobs */}
          {failedJobs.length > 0 && (
            <div className="space-y-1.5">
              <span className="text-[11px] font-semibold text-amber-800 dark:text-amber-300 uppercase tracking-[0.04em]">
                Failed Background Operations
              </span>
              <div className="space-y-1.5">
                {failedJobs.slice(0, 3).map((j) => (
                  <div
                    key={j.id}
                    className="p-2.5 rounded-lg bg-white/90 dark:bg-slate-900/90 border border-amber-200/80 dark:border-amber-800/60 flex items-center justify-between gap-2"
                  >
                    <div className="min-w-0 truncate">
                      <div className="font-semibold text-xs text-slate-800 dark:text-slate-100 flex items-center gap-2">
                        <span className="font-mono text-[10px] bg-rose-100 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300 px-1.5 py-0.2 rounded">
                          {String(j.id).slice(0, 8)}
                        </span>
                        <span className="truncate">{j.action || j.pipeline || 'Pipeline failed'}</span>
                      </div>
                      {j.error_message && (
                        <div className="text-[11px] text-rose-600 dark:text-rose-400 truncate mt-0.5">
                          {j.error_message}
                        </div>
                      )}
                    </div>
                    <Link
                      to={`/jobs?jobId=${j.id}`}
                      className="px-2 py-1 text-[11px] font-semibold text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 rounded border border-slate-200 dark:border-slate-700 flex items-center gap-1 flex-shrink-0"
                    >
                      <span>Logs</span>
                      <ArrowRight className="w-3 h-3" />
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Bottom Actions */}
          <div className="pt-2 flex items-center justify-between text-xs text-amber-800 dark:text-amber-300">
            <Link
              to="/settings"
              className="font-semibold hover:underline flex items-center gap-1"
            >
              Verify Endpoint Credentials in Settings →
            </Link>
            <Link to="/jobs" className="font-semibold hover:underline">
              Inspect Failed Operations in Job Monitor →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
};

export default AttentionNeeded;
