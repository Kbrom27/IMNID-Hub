import React from 'react';
import { Calendar } from 'lucide-react';

/**
 * DateInput Component
 * Consistent date picker input with calendar icon, bold label support, and validation styling.
 */
const DateInput = React.forwardRef(
  (
    {
      id,
      label,
      required = false,
      hint,
      value,
      onChange,
      error = false,
      disabled = false,
      className = '',
      containerClassName = '',
      ...rest
    },
    ref,
  ) => {
    const generatedId = React.useId();
    const inputId = id || (label ? generatedId : undefined);
    const hasError = Boolean(error);
    const errorMessage = typeof error === 'string' ? error : null;

    const inputElement = (
      <div className={`relative flex items-center w-full ${containerClassName}`}>
        <div className="absolute left-3.5 flex items-center pointer-events-none text-slate-400 dark:text-slate-500">
          <Calendar className="w-4 h-4 text-teal-600 dark:text-teal-400" />
        </div>
        <input
          ref={ref}
          id={inputId}
          type="date"
          value={value}
          onChange={onChange}
          disabled={disabled}
          className={`w-full rounded-lg border text-sm font-medium transition-colors py-2.5 pl-10 pr-3.5 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-50 disabled:bg-slate-50 dark:disabled:bg-slate-800 disabled:cursor-not-allowed ${
            hasError
              ? 'border-rose-400 dark:border-rose-600 focus-visible:ring-rose-500'
              : 'border-slate-300 dark:border-slate-700 hover:border-slate-400 dark:hover:border-slate-600'
          } ${className}`}
          {...rest}
        />
      </div>
    );

    if (label) {
      return (
        <div className="w-full space-y-1.5">
          <label
            htmlFor={inputId}
            className="block text-sm font-bold text-slate-800 dark:text-slate-200 select-none"
          >
            {label}
            {required && <span className="text-rose-500 ml-1" aria-hidden="true">*</span>}
          </label>
          {inputElement}
          {errorMessage && (
            <p className="text-xs font-semibold text-rose-600 dark:text-rose-400 mt-1">{errorMessage}</p>
          )}
        </div>
      );
    }

    return inputElement;
  },
);

DateInput.displayName = 'DateInput';
export default DateInput;
