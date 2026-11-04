import React from 'react';

/**
 * ProgressBar Component
 * Visual progress bar with percentage indicator and smooth animations.
 * Props:
 * @param {number} value - Progress percentage (0 - 100)
 * @param {boolean} indeterminate - Animated indeterminate mode
 * @param {'teal' | 'emerald' | 'amber' | 'rose'} color (default: 'teal')
 * @param {'sm' | 'md' | 'lg'} size (default: 'md')
 * @param {boolean} showLabel - Display percentage label
 * @param {string} className
 */
const ProgressBar = ({
  value = 0,
  indeterminate = false,
  color = 'teal',
  size = 'md',
  showLabel = false,
  className = '',
}) => {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));

  const sizes = {
    sm: 'h-1.5',
    md: 'h-2.5',
    lg: 'h-4',
  };

  const colors = {
    teal: 'bg-teal-600 dark:bg-teal-500',
    emerald: 'bg-emerald-600 dark:bg-emerald-500',
    amber: 'bg-amber-500',
    rose: 'bg-rose-600',
  };

  return (
    <div className={`w-full space-y-1 ${className}`}>
      {showLabel && (
        <div className="flex items-center justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
          <span>Progress</span>
          <span>{indeterminate ? 'Processing...' : `${clamped}%`}</span>
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={indeterminate ? undefined : clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        className={`w-full rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden ${sizes[size] || sizes.md}`}
      >
        {indeterminate ? (
          <div className={`h-full w-1/3 rounded-full animate-indeterminate ${colors[color] || colors.teal}`} />
        ) : (
          <div
            style={{ width: `${clamped}%` }}
            className={`h-full rounded-full transition-all duration-300 ease-out ${colors[color] || colors.teal}`}
          />
        )}
      </div>
    </div>
  );
};

export default ProgressBar;
