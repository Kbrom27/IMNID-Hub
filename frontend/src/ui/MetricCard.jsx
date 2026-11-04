import React from 'react';
import Card from './Card';

/**
 * MetricCard Component
 * Displays key statistical metrics with title, trend/status pill, and leading icon.
 * Props:
 * @param {string} title - Metric label
 * @param {string | number} value - Primary displayed value
 * @param {React.ReactNode} icon - Leading icon
 * @param {string | React.ReactNode} subtitle - Optional secondary note
 * @param {'teal' | 'emerald' | 'amber' | 'rose' | 'slate'} accent (default: 'teal')
 * @param {string} className
 */
const MetricCard = ({
  title,
  value,
  icon,
  subtitle,
  accent = 'teal',
  className = '',
}) => {
  const accents = {
    teal: 'bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 border-teal-200 dark:border-teal-900',
    emerald: 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-900',
    amber: 'bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-900',
    rose: 'bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-900',
    slate: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700',
  };

  return (
    <Card className={`p-4 sm:p-5 flex items-center justify-between gap-4 ${className}`}>
      <div className="min-w-0">
        <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider truncate">
          {title}
        </p>
        <p className="mt-1 text-2xl sm:text-3xl font-extrabold text-slate-900 dark:text-slate-100 tracking-tight">
          {value !== undefined && value !== null ? value : '-'}
        </p>
        {subtitle && (
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 truncate">
            {subtitle}
          </p>
        )}
      </div>

      {icon && (
        <div className={`p-3 rounded-md border flex-shrink-0 ${accents[accent] || accents.teal}`}>
          {icon}
        </div>
      )}
    </Card>
  );
};

export default MetricCard;
