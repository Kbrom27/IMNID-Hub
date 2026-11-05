import React from 'react';
import { Link } from 'react-router-dom';
import { Activity, ShieldCheck, ExternalLink, HelpCircle } from 'lucide-react';
import { useConnections } from '../context/ConnectionContext';
import pkg from '../../package.json';

export const PageFooter = () => {
  const { summary, secondsAgo } = useConnections();

  return (
    <footer className="mt-auto border-t border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/40 py-3 px-6 lg:px-8 transition-colors">
      <div className="max-w-[1440px] mx-auto w-full flex flex-col sm:flex-row items-center justify-between gap-2.5 text-xs text-slate-500 dark:text-slate-400">
        
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
            <span className="text-slate-600 dark:text-slate-300 font-medium">
              {summary.overallHealth === 'operational'
                ? 'All systems operational'
                : `${summary.connectedCount} of ${summary.totalCount} operational`}
            </span>
          </span>
          <span className="text-slate-300 dark:text-slate-700 hidden md:inline">·</span>
          <span className="text-xs text-slate-500 dark:text-slate-400 font-sans tabular-nums hidden md:inline">
            Status checked {secondsAgo}s ago
          </span>
        </div>

        <div className="flex items-center gap-4 text-xs font-medium">
          <Link
            to="/jobs"
            className="hover:text-teal-600 dark:hover:text-teal-400 transition-colors"
          >
            Job Monitor
          </Link>
          <Link
            to="/settings"
            className="hover:text-teal-600 dark:hover:text-teal-400 transition-colors"
          >
            System Settings
          </Link>
          <a
            href="https://github.com/hisptz/dhis2-core"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 hover:text-slate-800 dark:hover:text-slate-200 transition-colors"
          >
            <span>Docs</span>
            <ExternalLink className="w-3 h-3 text-slate-400" />
          </a>
        </div>

      </div>
    </footer>
  );
};

export default PageFooter;

