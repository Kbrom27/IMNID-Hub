import React from 'react';
import { ChevronDown } from 'lucide-react';

/**
 * Select Component
 * Styled native select element with custom arrow and consistent focus styling.
 */
const Select = React.forwardRef(
  (
    {
      id,
      label,
      required = false,
      hint,
      options,
      error = false,
      disabled = false,
      children,
      className = '',
      containerClassName = '',
      ...rest
    },
    ref,
  ) => {
    const generatedId = React.useId();
    const selectId = id || (label ? generatedId : undefined);
    const hasError = Boolean(error);
    const errorMessage = typeof error === 'string' ? error : null;

    const selectElement = (
      <div className={`relative flex items-center w-full ${containerClassName}`}>
        <select
          ref={ref}
          id={selectId}
          disabled={disabled}
          className={`w-full appearance-none rounded-lg border text-sm font-medium transition-colors py-2.5 pl-3.5 pr-10 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-50 disabled:bg-slate-50 dark:disabled:bg-slate-800 disabled:cursor-not-allowed ${
            hasError
              ? 'border-rose-400 dark:border-rose-600 focus-visible:ring-rose-500'
              : 'border-slate-300 dark:border-slate-700 hover:border-slate-400 dark:hover:border-slate-600'
          } ${className}`}
          {...rest}
        >
          {Array.isArray(options)
            ? options.map((opt) => (
                <option key={opt.value} value={opt.value} disabled={opt.disabled}>
                  {opt.label}
                </option>
              ))
            : children}
        </select>
        <div className="absolute right-3 pointer-events-none text-slate-400 dark:text-slate-500">
          <ChevronDown className="w-4 h-4" />
        </div>
      </div>
    );

    if (label) {
      return (
        <div className="w-full space-y-1.5">
          <label
            htmlFor={selectId}
            className="block text-sm font-bold text-slate-800 dark:text-slate-200 select-none"
          >
            {label}
            {required && <span className="text-rose-500 ml-1" aria-hidden="true">*</span>}
          </label>
          {selectElement}
          {errorMessage && (
            <p className="text-xs font-semibold text-rose-600 dark:text-rose-400 mt-1">{errorMessage}</p>
          )}
        </div>
      );
    }

    return selectElement;
  },
);

Select.displayName = 'Select';
export default Select;
