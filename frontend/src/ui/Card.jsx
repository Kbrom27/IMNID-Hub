import React from 'react';

/**
 * Card Component
 * Structured container with unified rounded-xl corners and subtle shadow.
 */
export const Card = ({ children, className = '', ...rest }) => (
  <div
    className={`bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm transition-shadow ${className}`}
    {...rest}
  >
    {children}
  </div>
);

export const CardHeader = ({ children, className = '', ...rest }) => (
  <div
    className={`p-5 sm:p-6 border-b border-slate-100 dark:border-slate-800/80 flex flex-col gap-1 ${className}`}
    {...rest}
  >
    {children}
  </div>
);

export const CardTitle = ({ children, className = '', ...rest }) => (
  <h3
    className={`text-base sm:text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2 ${className}`}
    {...rest}
  >
    {children}
  </h3>
);

export const CardDescription = ({ children, className = '', ...rest }) => (
  <p className={`text-xs sm:text-sm font-medium text-slate-500 dark:text-slate-400 ${className}`} {...rest}>
    {children}
  </p>
);

export const CardContent = ({ children, className = '', ...rest }) => (
  <div className={`p-5 sm:p-6 ${className}`} {...rest}>
    {children}
  </div>
);

export const CardFooter = ({ children, className = '', ...rest }) => (
  <div
    className={`p-5 sm:p-6 bg-slate-50/70 dark:bg-slate-800/30 border-t border-slate-100 dark:border-slate-800/80 rounded-b-xl flex items-center justify-between gap-3 ${className}`}
    {...rest}
  >
    {children}
  </div>
);

export default Card;
