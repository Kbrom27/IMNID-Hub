import React, { useState } from 'react';
import {
  Server,
  RefreshCw,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import StatusBadge from './StatusBadge';
import Tooltip from './Tooltip';

/**
 * ServerTile Component
 * Structured into two clear lines per health-tech cockpit design:
 * Line 1: status icon, full server name (no truncation), status pill, test & details actions
 * Line 2: subtitle, right-aligned latency (normal sans font with tabular-nums), source badge
 *
 * Props:
 * @param {object} server - System configuration and live telemetry
 * @param {function} onTest - Function to trigger connection test
 * @param {boolean} isTesting - Whether this system is actively being tested
 */
export const ServerTile = ({ server, onTest, isTesting = false }) => {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const {
    key,
    name,
    desc,
    isConfigured,
    isConnected,
    latencyMs,
    effectiveUrl,
    source,
    error,
    state,
  } = server;

  const handleCopyUrl = (e) => {
    e.stopPropagation();
    if (!effectiveUrl) return;
    navigator.clipboard.writeText(effectiveUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const handleTestClick = (e) => {
    e.stopPropagation();
    if (onTest && !isTesting) {
      onTest(key);
    }
  };

  return (
    <div
      className={`rounded-xl border transition-all duration-150 ${
        isConnected
          ? 'bg-white dark:bg-slate-900 border-slate-200/90 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 shadow-xs'
          : !isConfigured
          ? 'bg-slate-50/70 dark:bg-slate-900/40 border-slate-200 dark:border-slate-800/80 opacity-80'
          : 'bg-rose-50/40 dark:bg-rose-950/20 border-rose-200/80 dark:border-rose-900/60 shadow-xs'
      }`}
    >
      {/* Clickable Header: Structured into 2 distinct lines */}
      <div
        className="p-3.5 sm:px-4 cursor-pointer select-none"
        onClick={() => setExpanded((prev) => !prev)}
      >
        {/* LINE 1: Status Icon + Full Name (No truncation) + Status Pill + Actions */}
        <div className="flex items-center justify-between gap-3 min-w-0">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <div
              className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 border ${
                isConnected
                  ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
                  : !isConfigured
                  ? 'bg-slate-100 dark:bg-slate-800 text-slate-400 border-slate-200 dark:border-slate-700'
                  : 'bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-800'
              }`}
            >
              <Server className="w-3.5 h-3.5" />
            </div>

            <span className="font-semibold text-sm text-slate-900 dark:text-slate-100 whitespace-normal leading-snug">
              {name}
            </span>
          </div>

          {/* Right: Status Badge + Test Action + Expand Toggle */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <StatusBadge status={isTesting ? 'testing' : state} />

            <Tooltip content={`Test connection for ${name}`}>
              <button
                type="button"
                onClick={handleTestClick}
                disabled={isTesting}
                className="p-1 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 cursor-pointer"
                aria-label={`Test ${name} endpoint`}
              >
                <RefreshCw
                  className={`w-3.5 h-3.5 ${
                    isTesting ? 'animate-spin text-teal-600' : ''
                  }`}
                />
              </button>
            </Tooltip>

            <button
              type="button"
              className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded"
              aria-label={expanded ? 'Collapse server details' : 'Expand server details'}
            >
              {expanded ? (
                <ChevronUp className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>

        {/* LINE 2: Subtitle + Right-aligned Latency (Normal Sans Tabular) + Source Badge */}
        <div className="flex items-center justify-between gap-3 mt-2 pl-9.5 text-xs">
          <span className="text-slate-500 dark:text-slate-400 truncate flex-1">
            {desc}
          </span>

          <div className="flex items-center gap-2.5 flex-shrink-0">
            {latencyMs !== null && latencyMs > 0 && isConnected && (
              <span className="font-sans tabular-nums text-xs text-slate-600 dark:text-slate-400 font-medium">
                {latencyMs} ms
              </span>
            )}

            <span className="text-xs font-medium px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700/70">
              {source}
            </span>
          </div>
        </div>
      </div>

      {/* Expandable Details Area (Plain Monospace URL + Copy Button + Error message) */}
      {expanded && (
        <div className="px-4 pb-3.5 pt-2 border-t border-slate-100 dark:border-slate-800 space-y-2.5 text-xs animate-in fade-in duration-100">
          <div className="space-y-1">
            <span className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
              Target Endpoint URL
            </span>
            <div className="flex items-center justify-between gap-2 p-2.5 rounded-lg bg-slate-50 dark:bg-slate-950/60 border border-slate-200/80 dark:border-slate-800">
              <span className="font-mono text-xs text-slate-700 dark:text-slate-300 break-all select-all">
                {effectiveUrl || 'No URL configured'}
              </span>
              {effectiveUrl && (
                <button
                  type="button"
                  onClick={handleCopyUrl}
                  className="p-1 text-slate-400 hover:text-teal-600 dark:hover:text-teal-400 rounded transition-colors flex-shrink-0"
                  title="Copy URL"
                  aria-label="Copy server URL"
                >
                  {copied ? (
                    <Check className="w-3.5 h-3.5 text-emerald-600" />
                  ) : (
                    <Copy className="w-3.5 h-3.5" />
                  )}
                </button>
              )}
            </div>
          </div>

          {error && (
            <div className="p-2.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/80 text-rose-700 dark:text-rose-300 text-xs font-medium">
              <span className="font-semibold">Error:</span> {error}
            </div>
          )}

          {latencyMs !== null && latencyMs > 0 && (
            <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 pt-1">
              <span>Round-trip latency</span>
              <span className="font-sans tabular-nums font-semibold text-slate-700 dark:text-slate-200">
                {latencyMs} ms
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ServerTile;
