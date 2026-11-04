import React from 'react';

/**
 * Switch Component
 * Accessible toggle switch with label and description.
 * Props:
 * @param {string} id - Switch ID
 * @param {string | React.ReactNode} label - Primary label
 * @param {string | React.ReactNode} description - Optional detail text
 * @param {boolean} checked - Checked state
 * @param {(checked: boolean) => void} onChange
 * @param {boolean} disabled
 * @param {string} className
 */
const Switch = React.forwardRef(
  ({ id, label, description, checked, onChange, disabled = false, className = '', ...rest }, ref) => {
    return (
      <label
        htmlFor={id}
        className={`inline-flex items-start justify-between gap-3 select-none ${
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
        } ${className}`}
      >
        {(label || description) && (
          <div className="flex flex-col">
            {label && (
              <span className="text-xs sm:text-sm font-medium text-slate-800 dark:text-slate-200">
                {label}
              </span>
            )}
            {description && (
              <span className="text-[11px] sm:text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {description}
              </span>
            )}
          </div>
        )}

        <button
          ref={ref}
          id={id}
          type="button"
          role="switch"
          aria-checked={checked}
          disabled={disabled}
          onClick={() => !disabled && onChange && onChange(!checked)}
          className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 ${
            checked ? 'bg-teal-600' : 'bg-slate-300 dark:bg-slate-700'
          }`}
          {...rest}
        >
          <span
            aria-hidden="true"
            className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow-xs ring-0 transition duration-200 ease-in-out ${
              checked ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </label>
    );
  },
);

Switch.displayName = 'Switch';
export default Switch;
