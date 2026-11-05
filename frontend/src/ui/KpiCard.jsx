import React from 'react';
import Skeleton from './Skeleton';

/**
 * KpiCard Component
 * High-legibility operational KPI metric card.
 *
 * Props:
 * @param {string} title - Card title / label (uppercase tracking-wider)
 * @param {string | number} value - Main metric value (rendered in 32-36px tabular figures)
 * @param {React.ReactNode} subtext - Descriptive context (e.g. "98.2% success rate")
 * @param {React.ReactNode} icon - Leading icon
 * @param {'teal' | 'emerald' | 'blue' | 'rose' | 'amber' | 'slate'} variant - Accent color scheme
 * @param {boolean} loading - Displays skeleton loader when true
 * @param {React.ReactNode} badge - Optional badge / indicator on top-right
 * @param {string} className
 */
export const KpiCard = ({
  title,
  value,
  subtext,
  icon,
  variant = 'teal',
  loading = false,
  badge,
  className = '',
}) => {
  const iconVariants = {
    teal: 'bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 border-teal-200 dark:border-teal-900',
    emerald: 'bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 border-emerald-200 dark:border-emerald-900',
    blue: 'bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 border-blue-200 dark:border-blue-900',
    rose: 'bg-rose-50 dark:bg-rose-950/60 text-rose-600 dark:text-rose-400 border-rose-200 dark:border-rose-900',
    amber: 'bg-amber-50 dark:bg-amber-950/60 text-amber-600 dark:text-amber-400 border-amber-200 dark:border-amber-900',
    slate: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700',
  };

  const textVariants = {
    teal: 'text-teal-700 dark:text-teal-300',
    emerald: 'text-emerald-700 dark:text-emerald-300',
    blue: 'text-blue-700 dark:text-blue-300',
    rose: 'text-rose-700 dark:text-rose-300',
    amber: 'text-amber-700 dark:text-amber-300',
    slate: 'text-slate-900 dark:text-slate-100',
  };

  if (loading) {
    return (
      <div className={`p-5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm space-y-3 ${className}`}>
        <div className="flex items-center justify-between">
          <Skeleton variant="text" width={90} height={14} />
          <Skeleton variant="circle" width={32} height={32} />
        </div>
        <Skeleton variant="text" width={110} height={36} />
        <Skeleton variant="text" width={140} height={12} />
      </div>
    );
  }

  return (
    <div
      className={`p-5 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm hover:shadow-md transition-shadow flex flex-col justify-between ${className}`}
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-[0.04em] text-slate-500 dark:text-slate-400">
          {title}
        </span>
        <div className="flex items-center gap-1.5">
          {badge}
          {icon && (
            <div
              className={`w-9 h-9 rounded-lg flex items-center justify-center border flex-shrink-0 ${
                iconVariants[variant] || iconVariants.slate
              }`}
            >
              {icon}
            </div>
          )}
        </div>
      </div>

      <div className="mt-2">
        <div className={`text-3xl font-bold tabular-nums tracking-tight ${textVariants[variant] || textVariants.slate}`}>
          {value ?? '—'}
        </div>
        {subtext && (
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-1 font-medium leading-relaxed">
            {subtext}
          </div>
        )}
      </div>
    </div>
  );
};

export default KpiCard;

