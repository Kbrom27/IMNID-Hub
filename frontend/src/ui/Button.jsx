import React from 'react';
import Spinner from './Spinner';

/**
 * Button Component
 * Props:
 * @param {'primary' | 'secondary' | 'ghost' | 'danger'} variant - Visual style variant (default: 'primary')
 * @param {'sm' | 'md' | 'lg'} size - Sizing scale (default: 'md')
 * @param {boolean} loading - Displays inline spinner and disables button (default: false)
 * @param {React.ReactNode} icon - Optional icon node placed before text
 * @param {React.ReactNode} children - Button label or contents
 * @param {boolean} disabled - Disabled state
 * @param {string} className - Additional CSS class names
 * @param {React.ButtonHTMLAttributes} ...rest - HTML button attributes
 */
const Button = React.forwardRef(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      icon,
      children,
      disabled,
      className = '',
      type = 'button',
      ...rest
    },
    ref,
  ) => {
    const baseStyles =
      'inline-flex items-center justify-center font-semibold rounded-lg transition-all duration-150 select-none cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none active:scale-[0.98]';

    const sizes = {
      sm: 'px-3 py-1.5 text-xs gap-1.5 min-h-[32px]',
      md: 'px-4 py-2.5 text-sm gap-2 min-h-[40px]',
      lg: 'px-6 py-3 text-base font-bold gap-2.5 min-h-[48px]',
    };

    const variants = {
      primary:
        'bg-teal-600 hover:bg-teal-700 active:bg-teal-800 text-white shadow-sm focus-visible:ring-teal-500 border border-teal-700/20',
      secondary:
        'bg-white hover:bg-slate-50 active:bg-slate-100 text-slate-800 border border-slate-300 shadow-sm focus-visible:ring-slate-400 dark:bg-slate-800 dark:text-slate-100 dark:border-slate-700 dark:hover:bg-slate-700',
      ghost:
        'bg-transparent hover:bg-slate-100 active:bg-slate-200 text-slate-700 focus-visible:ring-slate-400 dark:text-slate-300 dark:hover:bg-slate-800/80',
      danger:
        'bg-rose-600 hover:bg-rose-700 active:bg-rose-800 text-white shadow-sm focus-visible:ring-rose-500 border border-rose-700/20',
    };

    const spinnerColor = variant === 'secondary' || variant === 'ghost' ? 'teal' : 'white';

    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled || loading}
        className={`${baseStyles} ${sizes[size] || sizes.md} ${variants[variant] || variants.primary} ${className}`}
        {...rest}
      >
        {loading ? (
          <Spinner size={size === 'sm' ? 'xs' : 'sm'} color={spinnerColor} className="flex-shrink-0" />
        ) : (
          icon && <span className="flex-shrink-0 flex items-center">{icon}</span>
        )}
        <span className="truncate">{children}</span>
      </button>
    );
  },
);

Button.displayName = 'Button';
export default Button;
