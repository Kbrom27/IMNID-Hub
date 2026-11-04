import React from 'react';
import { Info, CheckCircle2, AlertTriangle, AlertCircle, X } from 'lucide-react';

/**
 * Alert Component
 * Inline banners for notifications, system warnings, errors, and validation summaries.
 * Props:
 * @param {'info' | 'success' | 'warning' | 'danger'} variant (default: 'info')
 * @param {string} title - Optional title line
 * @param {React.ReactNode} children - Alert body content
 * @param {() => void} onClose - Optional callback for dismiss button
 * @param {string} className
 */
const Alert = ({
  variant = 'info',
  title,
  children,
  onClose,
  className = '',
}) => {
  const variants = {
    info: {
      bg: 'bg-sky-50 dark:bg-sky-950/50 border-sky-200 dark:border-sky-800 text-sky-900 dark:text-sky-200',
      icon: <Info className="w-4 h-4 text-sky-600 dark:text-sky-400 mt-0.5 flex-shrink-0" />,
    },
    success: {
      bg: 'bg-emerald-50 dark:bg-emerald-950/50 border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-200',
      icon: <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 mt-0.5 flex-shrink-0" />,
    },
    warning: {
      bg: 'bg-amber-50 dark:bg-amber-950/50 border-amber-200 dark:border-amber-800 text-amber-900 dark:text-amber-200',
      icon: <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />,
    },
    danger: {
      bg: 'bg-rose-50 dark:bg-rose-950/50 border-rose-200 dark:border-rose-800 text-rose-900 dark:text-rose-200',
      icon: <AlertCircle className="w-4 h-4 text-rose-600 dark:text-rose-400 mt-0.5 flex-shrink-0" />,
    },
  };

  const current = variants[variant] || variants.info;

  return (
    <div
      role="alert"
      className={`flex items-start gap-3 p-3.5 rounded-md border text-xs sm:text-sm ${current.bg} ${className}`}
    >
      {current.icon}
      <div className="flex-1 min-w-0">
        {title && <h4 className="font-semibold text-xs mb-0.5">{title}</h4>}
        <div className="leading-relaxed break-words">{children}</div>
      </div>
      {onClose && (
        <button
          type="button"
          onClick={onClose}
          aria-label="Dismiss alert"
          className="p-1 rounded-sm opacity-70 hover:opacity-100 hover:bg-black/5 dark:hover:bg-white/10 transition-opacity flex-shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
};

export default Alert;
