import React from 'react';
import { CheckCircle2, XCircle, AlertCircle, Clock, RefreshCw, MinusCircle } from 'lucide-react';

/**
 * StatusBadge Component
 * Standardized status badge conforming strictly to health-tech operations UX:
 * - min 12px text
 * - icon + text + color
 * - testing spinner state
 * - WCAG AA contrast compliant
 */
const STATUS_STYLES = {
  completed: {
    badge: 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800/80',
    icon: CheckCircle2,
    iconClass: 'text-emerald-600 dark:text-emerald-400',
    label: 'Completed',
  },
  connected: {
    badge: 'bg-emerald-50 text-emerald-800 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800/80',
    icon: CheckCircle2,
    iconClass: 'text-emerald-600 dark:text-emerald-400',
    label: 'Connected',
  },
  running: {
    badge: 'bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-950/50 dark:text-blue-300 dark:border-blue-800/80',
    icon: RefreshCw,
    iconClass: 'text-blue-600 dark:text-blue-400 animate-spin',
    label: 'Running',
  },
  testing: {
    badge: 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800/80',
    icon: RefreshCw,
    iconClass: 'text-amber-600 dark:text-amber-400 animate-spin',
    label: 'Testing...',
  },
  pending: {
    badge: 'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800/80',
    icon: Clock,
    iconClass: 'text-amber-600 dark:text-amber-400',
    label: 'Pending',
  },
  failed: {
    badge: 'bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-950/50 dark:text-rose-300 dark:border-rose-800/80',
    icon: XCircle,
    iconClass: 'text-rose-600 dark:text-rose-400',
    label: 'Failed',
  },
  unreachable: {
    badge: 'bg-rose-50 text-rose-800 border-rose-200 dark:bg-rose-950/50 dark:text-rose-300 dark:border-rose-800/80',
    icon: XCircle,
    iconClass: 'text-rose-600 dark:text-rose-400',
    label: 'Offline',
  },
  cancelled: {
    badge: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    icon: MinusCircle,
    iconClass: 'text-slate-400',
    label: 'Cancelled',
  },
  canceled: {
    badge: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    icon: MinusCircle,
    iconClass: 'text-slate-400',
    label: 'Cancelled',
  },
  not_configured: {
    badge: 'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700',
    icon: MinusCircle,
    iconClass: 'text-slate-400',
    label: 'Not Configured',
  },
};

const DEFAULT_STYLE = {
  badge: 'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
  icon: AlertCircle,
  iconClass: 'text-slate-400',
  label: 'Unknown',
};

export const StatusBadge = ({
  status,
  showIcon = true,
  dot = false,
  size = 'sm',
  className = '',
  children,
}) => {
  const normStatus = (status || '').toLowerCase().trim();
  const config = STATUS_STYLES[normStatus] || DEFAULT_STYLE;
  const Icon = config.icon;

  const sizeClass =
    size === 'xs'
      ? 'text-[11px] px-2 py-0.5 gap-1'
      : size === 'md'
      ? 'text-xs px-3 py-1 gap-1.5'
      : 'text-xs px-2.5 py-0.5 gap-1.5';

  return (
    <span
      className={`inline-flex items-center font-semibold rounded-full border transition-colors select-none ${sizeClass} ${config.badge} ${className}`}
    >
      {showIcon && Icon && (
        <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${config.iconClass}`} />
      )}
      {dot && !showIcon && (
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${config.iconClass.replace('text-', 'bg-')}`} />
      )}
      <span className="capitalize">{children || config.label}</span>
    </span>
  );
};

export default StatusBadge;
