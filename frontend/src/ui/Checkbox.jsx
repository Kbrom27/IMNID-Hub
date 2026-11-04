import React from 'react';

/**
 * Checkbox Component
 * Accessible styled checkbox with optional title and description text.
 * Props:
 * @param {string} id - Input ID
 * @param {string | React.ReactNode} label - Primary label
 * @param {string | React.ReactNode} description - Optional secondary detail text
 * @param {boolean} checked - Checked state
 * @param {(e: React.ChangeEvent<HTMLInputElement>) => void} onChange
 * @param {boolean} disabled
 * @param {string} className
 */
const Checkbox = React.forwardRef(
  ({ id, label, description, checked, onChange, disabled = false, className = '', ...rest }, ref) => {
    return (
      <label
        htmlFor={id}
        className={`inline-flex items-start gap-2.5 select-none ${
          disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
        } ${className}`}
      >
        <input
          ref={ref}
          id={id}
          type="checkbox"
          checked={checked}
          onChange={onChange}
          disabled={disabled}
          className="mt-0.5 h-4 w-4 rounded border-slate-300 dark:border-slate-700 text-teal-600 focus:ring-teal-500 focus:ring-offset-0 transition-colors"
          {...rest}
        />
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
      </label>
    );
  },
);

Checkbox.displayName = 'Checkbox';
export default Checkbox;
