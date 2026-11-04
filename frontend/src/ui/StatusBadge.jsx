import React from 'react';

/**
 * StatusBadge Component
 * Standardized status badge conforming strictly to Item 12:
 * - pending: yellow (bg-amber-100 text-amber-800 border-amber-200)
 * - running: blue (bg-blue-100 text-blue-800 border-blue-200)
 * - completed: green (bg-emerald-100 text-emerald-800 border-emerald-200)
 * - failed: red (bg-rose-100 text-rose-800 border-rose-200)
 * - cancelled / not_configured / other: gray (bg-slate-100 text-slate-700 border-slate-200)
 */
const STATUS_STYLES = {
  pending: {
    badge: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800',
    dot: 'bg-amber-500',
    label: 'Pending',
  },
  running: {
    badge: 'bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950/60 dark:text-blue-300 dark:border-blue-800',
    dot: 'bg-blue-500 animate-pulse',
    label: 'Running',
  },
  completed: {
    badge: 'bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800',
    dot: 'bg-emerald-500',
    label: 'Completed',
  },
  failed: {
    badge: 'bg-rose-100 text-rose-800 border-rose-200 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800',
    dot: 'bg-rose-500',
    label: 'Failed',
  },
  cancelled: {
    badge: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    dot: 'bg-slate-400',
    label: 'Cancelled',
  },
  canceled: {
    badge: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    dot: 'bg-slate-400',
    label: 'Cancelled',
  },
  not_configured: {
    badge: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    dot: 'bg-slate-400',
    label: 'Not Configured',
  },
};

const DEFAULT_STYLE = {
  badge: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  dot: 'bg-slate-400',
  label: 'Unknown',
};

export const StatusBadge = ({ status, dot = true, size = 'sm', className = '', children }) => {
  const normStatus = (status || '').toLowerCase().trim();
  const config = STATUS_STYLES[normStatus] || DEFAULT_STYLE;

  const sizeClass =
    size === 'xs'
      ? 'text-[10px] px-1.5 py-0.5'
      : size === 'md'
      ? 'text-xs px-2.5 py-1'
      : 'text-[11px] px-2 py-0.5';

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-semibold uppercase tracking-wider rounded-full border ${sizeClass} ${config.badge} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${config.dot}`} />}
      <span>{children || config.label}</span>
    </span>
  );
};

export default StatusBadge;
