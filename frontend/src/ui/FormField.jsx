import React from 'react';

/**
 * FormField Component
 * Standard wrapper providing label (13px), hint/caption (12px), required indicator, and error messaging.
 * Props:
 * @param {string} label - Input label text
 * @param {string} id - HTML ID for associating label with input
 * @param {boolean} required - Displays red asterisk
 * @param {string | React.ReactNode} hint - Optional hint text below input
 * @param {string | React.ReactNode} error - Validation error text
 * @param {React.ReactNode} cornerAction - Optional link or button on top right of label
 * @param {React.ReactNode} children - Input element
 * @param {string} className
 */
const FormField = ({
  label,
  id,
  required = false,
  hint,
  error,
  cornerAction,
  children,
  className = '',
}) => {
  return (
    <div className={`space-y-1.5 ${className}`}>
      {(label || cornerAction) && (
        <div className="flex items-center justify-between">
          {label && (
            <label
              htmlFor={id}
              className="block font-semibold text-[13px] text-slate-700 dark:text-slate-200 select-none"
            >
              {label}
              {required && <span className="text-rose-500 ml-1" aria-hidden="true">*</span>}
            </label>
          )}
          {cornerAction && <div className="text-xs">{cornerAction}</div>}
        </div>
      )}

      {children}

      {error ? (
        <p className="text-xs font-medium text-rose-600 dark:text-rose-400 flex items-center gap-1 mt-1" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{hint}</p>
      ) : null}
    </div>
  );
};

export default FormField;
