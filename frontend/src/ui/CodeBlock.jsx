import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';
import IconButton from './IconButton';

/**
 * CodeBlock Component
 * Monospace code container with syntax copy button and optional max-height scroll.
 * Props:
 * @param {string} code - Raw code string
 * @param {string} language - Language badge (e.g. 'json', 'sql', 'bash')
 * @param {string} maxHeight - Max height CSS
 * @param {string} className
 */
const CodeBlock = ({ code = '', language = 'json', maxHeight = '360px', className = '' }) => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className={`relative rounded-md border border-slate-800 bg-slate-950 text-slate-200 overflow-hidden font-mono text-xs shadow-xs ${className}`}
    >
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900 border-b border-slate-800 text-[11px] text-slate-400">
        <span className="uppercase font-semibold tracking-wider text-slate-400">{language}</span>
        <IconButton
          variant="ghost"
          size="xs"
          ariaLabel="Copy code"
          onClick={handleCopy}
          className="text-slate-400 hover:text-white"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
        </IconButton>
      </div>

      <pre
        style={{ maxHeight }}
        className="p-3.5 overflow-x-auto overflow-y-auto leading-relaxed select-text"
      >
        <code>{code}</code>
      </pre>
    </div>
  );
};

export default CodeBlock;
