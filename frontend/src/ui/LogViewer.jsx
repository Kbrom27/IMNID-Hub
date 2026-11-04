import React, { useEffect, useRef, useState } from 'react';
import { Copy, Download, Check, ArrowDown, Terminal } from 'lucide-react';
import IconButton from './IconButton';

/**
 * LogViewer Component
 * Live streaming log viewer with line coloring, auto-scroll toggle, copy and download.
 * Props:
 * @param {Array<{ timestamp?: string, level?: string, text: string } | string>} logs
 * @param {string} title - Optional title (default: 'Execution Logs')
 * @param {string} maxHeight - Container max height CSS (default: '320px')
 * @param {string} logFileName - Filename for download (default: 'job_logs.log')
 * @param {string} className
 */
const LogViewer = ({
  logs = [],
  title = 'Execution Logs',
  maxHeight = '320px',
  logFileName = 'job_logs.log',
  className = '',
}) => {
  const containerRef = useRef(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const handleCopy = () => {
    const raw = logs
      .map((line) => {
        if (!line) return '';
        if (typeof line === 'string') return line;
        return `[${line.timestamp || ''}] [${line.level || 'INFO'}] ${line.text || line.line || JSON.stringify(line)}`;
      })
      .filter(Boolean)
      .join('\n');
    navigator.clipboard.writeText(raw);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const raw = logs
      .map((line) => {
        if (!line) return '';
        if (typeof line === 'string') return line;
        return `[${line.timestamp || ''}] [${line.level || 'INFO'}] ${line.text || line.line || JSON.stringify(line)}`;
      })
      .filter(Boolean)
      .join('\n');
    const blob = new Blob([raw], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = logFileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const getLineStyle = (line) => {
    if (!line) return 'text-slate-300 dark:text-slate-300';
    const text = typeof line === 'string' ? line : `${line?.level || ''} ${line?.text || line?.line || ''}`;
    const upper = String(text).toUpperCase();

    // Check for explicit zero-failure / zero-error indicators
    const isZeroFailure =
      /\b0\s+(?:\w+\s+)?(?:errors?|failures?|failed|exceptions?)\b/i.test(text) ||
      /(?:errors?|row_errors?|failures?|failed|exceptions?)\s*['"]?\s*[:=]\s*0\b/i.test(text) ||
      /\b(?:failed to sync)\s*:\s*0\b/i.test(text) ||
      upper.includes('100% SUCCESS') ||
      upper.includes('ZERO ERRORS') ||
      upper.includes('0 ERROR') ||
      upper.includes('ERRORS: 0') ||
      upper.includes('ERROR: 0');

    // Lines that explicitly indicate success or completion with zero failures
    if (
      isZeroFailure ||
      (upper.includes('FINISHED') && !/\b[1-9]\d*\s+(?:\w+\s+)?(?:errors?|failures?|failed)\b/i.test(text)) ||
      (upper.includes('COMPLETE') && !/\b[1-9]\d*\s+(?:\w+\s+)?(?:errors?|failures?|failed)\b/i.test(text)) ||
      upper.includes('SUCCESSFULLY') ||
      text.includes('✓')
    ) {
      return 'text-emerald-400 dark:text-emerald-400 font-semibold';
    }

    if (
      upper.includes('ERROR') ||
      upper.includes('FAIL') ||
      upper.includes('EXCEPTION')
    ) {
      return 'text-rose-400 dark:text-rose-400 bg-rose-950/20';
    }
    if (upper.includes('WARN') || upper.includes('NOTICE')) {
      return 'text-amber-300 dark:text-amber-300';
    }
    return 'text-slate-300 dark:text-slate-300';
  };

  return (
    <div
      className={`rounded-md border border-slate-800 bg-slate-950 text-slate-200 overflow-hidden font-mono text-xs shadow-md flex flex-col ${className}`}
    >
      {/* Header bar */}
      <div className="flex items-center justify-between px-3.5 py-2 bg-slate-900 border-b border-slate-800 text-[11px] text-slate-400 select-none">
        <div className="flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-teal-400" />
          <span className="font-semibold text-slate-300">{title}</span>
          <span className="text-[10px] bg-slate-800 px-1.5 py-0.2 rounded text-slate-400">
            {logs.length} lines
          </span>
        </div>

        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 cursor-pointer text-slate-400 hover:text-slate-200 transition-colors">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded bg-slate-800 border-slate-700 text-teal-500 focus:ring-0 w-3 h-3"
            />
            <span>Auto-scroll</span>
          </label>

          <IconButton
            variant="ghost"
            size="xs"
            ariaLabel="Copy logs"
            title="Copy logs"
            onClick={handleCopy}
            className="text-slate-400 hover:text-white hover:bg-slate-800"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </IconButton>

          <IconButton
            variant="ghost"
            size="xs"
            ariaLabel="Download log file"
            title="Download log file"
            onClick={handleDownload}
            className="text-slate-400 hover:text-white hover:bg-slate-800"
          >
            <Download className="w-3.5 h-3.5" />
          </IconButton>
        </div>
      </div>

      {/* Log body */}
      <div
        ref={containerRef}
        style={{ maxHeight }}
        className="p-3 overflow-y-auto space-y-1 font-mono text-[11px] leading-relaxed select-text"
      >
        {logs.length === 0 ? (
          <p className="text-slate-500 italic py-4 text-center">Waiting for job output...</p>
        ) : (
          logs.map((line, idx) => {
            if (!line) return null;
            const isObj = typeof line === 'object' && line !== null;
            const displayText = isObj
              ? (line.text || line.line || JSON.stringify(line))
              : String(line);
            return (
              <div key={idx} className={`px-1 py-0.5 rounded-xs transition-colors ${getLineStyle(line)}`}>
                {isObj ? (
                  <span>
                    {line.timestamp && <span className="opacity-50 mr-2">[{line.timestamp}]</span>}
                    {line.level && (
                      <span className="font-bold opacity-75 mr-2">[{line.level}]</span>
                    )}
                    <span>{displayText}</span>
                  </span>
                ) : (
                  <span>{displayText}</span>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default LogViewer;
