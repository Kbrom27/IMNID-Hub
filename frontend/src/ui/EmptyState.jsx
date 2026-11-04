import React from 'react';
import { Inbox } from 'lucide-react';

/**
 * EmptyState Component
 * Displays empty or uninitialized states across tables, lists, and search queries.
 * Props:
 * @param {React.ReactNode} icon - Optional central icon
 * @param {string} title - Header title
 * @param {string | React.ReactNode} description - Explanatory subtitle
 * @param {React.ReactNode} action - Action button
 * @param {string} className
 */
const EmptyState = ({
  icon,
  title = 'No items found',
  description = 'There is currently no data or activity to display.',
  action,
  className = '',
}) => {
  return (
    <div
      className={`flex flex-col items-center justify-center p-8 sm:p-12 text-center rounded-md border border-dashed border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40 ${className}`}
    >
      <div className="p-3 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 mb-3">
        {icon || <Inbox className="w-8 h-8 stroke-[1.5]" />}
      </div>
      <h4 className="text-sm sm:text-base font-semibold text-slate-800 dark:text-slate-200">
        {title}
      </h4>
      {description && (
        <p className="mt-1 text-xs sm:text-sm text-slate-500 dark:text-slate-400 max-w-sm">
          {description}
        </p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
};

export default EmptyState;
