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
 * Single-row (~44px) operational system tile conforming to Section B & C criteria:
 * - Row: Status icon, full name (no truncation), right-aligned latency (integer ms), status pill, test button, expand chevron
 * - Subtitle line and source badge removed from closed state (kept in expandable chevron)
 * - Round-trip latency: 13-14px/500 in primary text color with light-weight unit
 */
export const ServerTile = ({ server, onTest, isTesting = false }) => {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const {
    key,
    name,
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

  const roundedLatency = latencyMs !== null && latencyMs > 0 ? Math.round(latencyMs) : null;

  return (
    <div
      className={`rounded-xl border transition-all duration-150 ${
        isConnected
          ? 'bg-white dark:bg-slate-900 border-slate-200/90 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 shadow-2xs'
          : !isConfigured
          ? 'bg-slate-50/70 dark:bg-slate-900/40 border-slate-200 dark:border-slate-800/80 opacity-80'
          : 'bg-rose-50/40 dark:bg-rose-950/20 border-rose-200/80 dark:border-rose-900/60 shadow-2xs'
      }`}
    >
      {/* Clickable Single-Row Header */}
      <div
        className="px-4 py-3 min-h-[50px] flex items-center justify-between gap-3 cursor-pointer select-none"
        onClick={() => setExpanded((prev) => !prev)}
      >
        {/* Left: Status Icon + Full Name */}
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div
            className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 border ${
              isConnected
                ? 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
                : !isConfigured
                ? 'bg-slate-100 dark:bg-slate-800 text-slate-400 border-slate-200 dark:border-slate-700'
                : 'bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-800'
            }`}
          >
            <Server className="w-4 h-4" />
          </div>

          <span className="font-semibold text-sm text-slate-900 dark:text-slate-100 truncate">
            {name}
          </span>
        </div>

        {/* Right: Latency (Right-aligned, tabular-nums) + Status Badge + Actions */}
        <div className="flex items-center gap-2.5 flex-shrink-0">
          {roundedLatency !== null && isConnected && (
            <span className="font-sans tabular-nums text-sm font-medium text-slate-900 dark:text-slate-100">
              {roundedLatency} <span className="text-xs font-normal text-slate-500 dark:text-slate-400">ms</span>
            </span>
          )}

          <StatusBadge status={isTesting ? 'testing' : state} />

          <Tooltip content={`Test connection for ${name}`}>
            <button
              type="button"
              onClick={handleTestClick}
              disabled={isTesting}
              className="p-1 rounded-md border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-teal-500 cursor-pointer"
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
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Expandable Details Area (Plain Monospace URL + Copy Button + Source + Error message) */}
      {expanded && (
        <div className="px-3.5 pb-3 pt-2 border-t border-slate-100 dark:border-slate-800 space-y-2 text-xs animate-in fade-in duration-100">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wide">
              Target Endpoint URL
            </span>
            {source && (
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700/70">
                Source: {source}
              </span>
            )}
          </div>

          <div className="flex items-center justify-between gap-2 p-2 rounded-lg bg-slate-50 dark:bg-slate-950/60 border border-slate-200/80 dark:border-slate-800">
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

          {error && (
            <div className="p-2 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/80 text-rose-700 dark:text-rose-300 text-xs font-medium">
              <span className="font-semibold">Error:</span> {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ServerTile;
