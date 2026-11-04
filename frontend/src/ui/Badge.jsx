import React from 'react';

/**
 * Badge / StatusPill Component
 * Props:
 * @param {'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'primary'} variant (default: 'neutral')
 * @param {'sm' | 'md' | 'lg'} size (default: 'md')
 * @param {boolean} dot - Render a pulse/status dot before text (default: false)
 * @param {React.ReactNode} children - Badge content
 * @param {string} className - Additional CSS classes
 */
const Badge = ({ variant = 'neutral', size = 'md', dot = false, children, className = '' }) => {
  const sizes = {
    sm: 'text-[11px] px-2 py-0.5 gap-1',
    md: 'text-xs px-2.5 py-0.5 gap-1.5',
    lg: 'text-sm px-3 py-1 gap-2',
  };

  const variants = {
    neutral:
      'bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    primary:
      'bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/60 dark:text-teal-300 dark:border-teal-800',
    success:
      'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800',
    warning:
      'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800',
    danger:
      'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800',
    info: 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-800',
  };

  const dotColors = {
    neutral: 'bg-slate-500',
    primary: 'bg-teal-500',
    success: 'bg-emerald-500',
    warning: 'bg-amber-500',
    danger: 'bg-rose-500',
    info: 'bg-sky-500',
  };

  return (
    <span
      className={`inline-flex items-center font-medium rounded-full border ${sizes[size] || sizes.md} ${variants[variant] || variants.neutral} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotColors[variant] || dotColors.neutral}`} />}
      <span className="truncate">{children}</span>
    </span>
  );
};

export default Badge;
