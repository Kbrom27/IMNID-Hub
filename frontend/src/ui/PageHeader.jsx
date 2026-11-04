import React from 'react';

/**
 * PageHeader Component
 * Standard page title banner for all IMNID Hub views.
 * Eyebrow/breadcrumb navigation is rendered in the global Topbar to eliminate redundant in-page crumbs.
 * Props:
 * @param {string} title - Page title
 * @param {string | React.ReactNode} description - Subtitle / overview text
 * @param {React.ReactNode} actions - Action buttons displayed on the right
 * @param {React.ReactNode} icon - Leading page icon
 * @param {string} className - Additional CSS classes
 */
const PageHeader = ({
  title,
  description,
  breadcrumbs = [], // Kept for backwards compatibility
  actions,
  icon,
  className = '',
}) => {
  return (
    <div className={`mb-6 pb-4 border-b border-slate-200 dark:border-slate-800 ${className}`}>
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-start gap-3">
          {icon && (
            <div className="p-2.5 rounded-lg bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 border border-teal-200 dark:border-teal-900 flex-shrink-0 mt-0.5">
              {icon}
            </div>
          )}
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-slate-900 dark:text-slate-100">
              {title}
            </h1>
            {description && (
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400 mt-1">
                {description}
              </p>
            )}
          </div>
        </div>

        {actions && <div className="flex items-center gap-2.5 flex-wrap sm:flex-nowrap">{actions}</div>}
      </div>
    </div>
  );
};

export default PageHeader;
