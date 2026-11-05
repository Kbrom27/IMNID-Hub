import React from 'react';
import { useConnections } from '../context/ConnectionContext';
import pkg from '../../package.json';

/**
 * PageFooter Component
 * Slim single line conforming to Section D criteria:
 * - Version and "X of 7 operational · checked Xs ago" only
 * - Removed duplicate sidebar links (Job Monitor, System Settings, Docs)
 */
export const PageFooter = () => {
  const { summary, secondsAgo } = useConnections();

  return (
    <footer className="mt-auto border-t border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/40 py-2 px-4 sm:px-6 transition-colors">
      <div className="max-w-[1440px] mx-auto w-full flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <div className="flex items-center gap-3">
          <span className="font-semibold text-slate-700 dark:text-slate-300">
            IMNID Hub <span className="font-sans tabular-nums text-slate-400 font-normal">v{pkg.version || '1.0.0'}</span>
          </span>
          <span className="text-slate-300 dark:text-slate-700">·</span>
          <span className="inline-flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                summary.overallHealth === 'operational'
                  ? 'bg-emerald-500'
                  : summary.overallHealth === 'degraded'
                  ? 'bg-amber-500'
                  : 'bg-rose-500'
              }`}
            />
            <span className="text-slate-600 dark:text-slate-300 font-medium font-sans tabular-nums">
              {summary.connectedCount}/{summary.totalCount} operational
            </span>
          </span>
          <span className="text-slate-300 dark:text-slate-700 hidden sm:inline">·</span>
          <span className="text-xs text-slate-500 dark:text-slate-400 font-sans tabular-nums hidden sm:inline">
            checked {secondsAgo}s ago
          </span>
        </div>
      </div>
    </footer>
  );
};

export default PageFooter;

