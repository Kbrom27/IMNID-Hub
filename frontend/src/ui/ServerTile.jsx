import React, { useState } from 'react';
import {
  Server,
  RefreshCw,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Shield,
  Activity,
} from 'lucide-react';
import StatusBadge from './StatusBadge';
import Tooltip from './Tooltip';

/**
 * ServerTile Component
 * Compact 64-72px operational server card with clean expandable URL details.
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
          ? 'bg-white dark:bg-slate-900 border-slate-200/90 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700'
          : !isConfigured
          ? 'bg-slate-50/70 dark:bg-slate-900/40 border-slate-200 dark:border-slate-800/80 opacity-80'
          : 'bg-rose-50/30 dark:bg-rose-950/20 border-rose-200/80 dark:border-rose-900/60'
      }`}
    >
      {/* Compact Header Row (~64px) */}
      <div
        className="p-3.5 sm:px-4 flex items-center justify-between gap-3 cursor-pointer select-none"
        onClick={() => setExpanded((prev) => !prev)}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div
            className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 border ${
              isConnected
                ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 border-emerald-200/80 dark:border-emerald-900/60'
                : !isConfigured
                ? 'bg-slate-100 dark:bg-slate-800 text-slate-400 border-slate-200 dark:border-slate-700'
                : 'bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border-rose-200/80 dark:border-rose-900/60'
            }`}
          >
            <Server className="w-4 h-4" />
          </div>

          <div className="min-w-0 truncate">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-sm text-slate-900 dark:text-slate-100 truncate">
                {name}
              </span>
              <span className="text-[10px] font-medium px-1.5 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-slate-500">
                {source}
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
              {desc}
            </p>
          </div>
        </div>

        {/* Right side controls: Latency + Status Badge + Test Button + Details Toggle */}
        <div className="flex items-center gap-2.5 flex-shrink-0">
          {latencyMs !== null && latencyMs > 0 && isConnected && (
            <span className="hidden sm:inline font-mono tabular-nums text-xs text-slate-500 dark:text-slate-400 font-medium">
              {latencyMs} ms
            </span>
          )}

          <StatusBadge status={isTesting ? 'testing' : state} />

          <Tooltip content={`Test connection for ${name}`}>
            <button
              type="button"
              onClick={handleTestClick}
              disabled={isTesting}
              className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
              aria-label={`Test ${name} endpoint`}
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isTesting ? 'animate-spin text-teal-600' : ''}`} />
            </button>
          </Tooltip>

          <button
            type="button"
            className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded"
            aria-label={expanded ? 'Collapse server details' : 'Expand server details'}
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Expandable Details Area (Plain Monospace URL + Copy Button + Error message) */}
      {expanded && (
        <div className="px-4 pb-3.5 pt-1 border-t border-slate-100 dark:border-slate-800/80 space-y-2 text-xs animate-in fade-in duration-100">
          <div className="space-y-1">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-[0.04em]">
              Target Endpoint URL
            </span>
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
          </div>

          {error && (
            <div className="p-2 rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/80 text-rose-700 dark:text-rose-300 text-xs font-medium">
              <span className="font-semibold">Error:</span> {error}
            </div>
          )}

          {latencyMs !== null && latencyMs > 0 && (
            <div className="flex items-center justify-between text-[11px] text-slate-500 dark:text-slate-400 pt-1">
              <span>Round-trip latency</span>
              <span className="font-mono tabular-nums font-semibold">{latencyMs} ms</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default ServerTile;
