import React from 'react';

/**
 * Radio Component
 * Accessible styled radio button with optional card style and details.
 * Props:
 * @param {string} id - Radio ID
 * @param {string} name - Radio group name
 * @param {string} value - Value
 * @param {string | React.ReactNode} label - Primary label
 * @param {string | React.ReactNode} description - Secondary details
 * @param {boolean} checked - Checked state
 * @param {(e: React.ChangeEvent<HTMLInputElement>) => void} onChange
 * @param {boolean} card - Render as card container
 * @param {boolean} disabled
 * @param {string} className
 */
const Radio = React.forwardRef(
  (
    {
      id,
      name,
      value,
      label,
      description,
      checked,
      onChange,
      card = false,
      disabled = false,
      className = '',
      ...rest
    },
    ref,
  ) => {
    if (card) {
      return (
        <label
          htmlFor={id}
          className={`flex items-start gap-3 p-3.5 rounded-md border transition-all select-none ${
            disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
          } ${
            checked
              ? 'border-teal-500 bg-teal-50/50 dark:bg-teal-950/40 ring-1 ring-teal-500/30'
              : 'border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800/60'
          } ${className}`}
        >
          <input
            ref={ref}
            id={id}
            name={name}
            type="radio"
            value={value}
            checked={checked}
            onChange={onChange}
            disabled={disabled}
            className="mt-0.5 h-4 w-4 border-slate-300 dark:border-slate-700 text-teal-600 focus:ring-teal-500 focus:ring-offset-0"
            {...rest}
          />
          <div className="flex flex-col min-w-0 flex-1">
            {label && (
              <span className="text-xs sm:text-sm font-semibold text-slate-900 dark:text-slate-100">
                {label}
              </span>
            )}
            {description && (
              <span className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                {description}
              </span>
            )}
          </div>
        </label>
      );
    }

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
          name={name}
          type="radio"
          value={value}
          checked={checked}
          onChange={onChange}
          disabled={disabled}
          className="mt-0.5 h-4 w-4 border-slate-300 dark:border-slate-700 text-teal-600 focus:ring-teal-500 focus:ring-offset-0"
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

Radio.displayName = 'Radio';
export default Radio;
