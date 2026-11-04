import React from 'react';
import Spinner from './Spinner';

/**
 * IconButton Component
 * Props:
 * @param {string} ariaLabel - Mandatory accessible label
 * @param {'ghost' | 'secondary' | 'primary' | 'danger'} variant - Visual style (default: 'ghost')
 * @param {'xs' | 'sm' | 'md' | 'lg'} size - Button size (default: 'md')
 * @param {boolean} loading - Display loading spinner (default: false)
 * @param {boolean} disabled - Disabled state
 * @param {React.ReactNode} children - Icon node
 * @param {string} className - Additional CSS class names
 * @param {string} title - Optional native hover tooltip
 */
const IconButton = React.forwardRef(
  (
    {
      ariaLabel,
      variant = 'ghost',
      size = 'md',
      loading = false,
      disabled = false,
      children,
      className = '',
      title,
      type = 'button',
      ...rest
    },
    ref,
  ) => {
    const baseStyles =
      'inline-flex items-center justify-center rounded-md transition-all duration-150 select-none cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:opacity-40 disabled:cursor-not-allowed disabled:pointer-events-none active:scale-95';

    const sizes = {
      xs: 'w-6 h-6 p-1 text-xs',
      sm: 'w-8 h-8 p-1.5 text-sm',
      md: 'w-9 h-9 p-2 text-base',
      lg: 'w-11 h-11 p-2.5 text-lg',
    };

    const variants = {
      ghost:
        'text-slate-600 hover:text-slate-900 hover:bg-slate-100 active:bg-slate-200 dark:text-slate-400 dark:hover:text-slate-100 dark:hover:bg-slate-800',
      secondary:
        'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 shadow-xs dark:bg-slate-800 dark:text-slate-200 dark:border-slate-700 dark:hover:bg-slate-700/60',
      primary:
        'bg-teal-600 text-white hover:bg-teal-700 shadow-xs dark:bg-teal-600 dark:hover:bg-teal-500',
      danger:
        'text-rose-600 hover:bg-rose-50 hover:text-rose-700 dark:text-rose-400 dark:hover:bg-rose-950/40',
    };

    return (
      <button
        ref={ref}
        type={type}
        aria-label={ariaLabel || title}
        title={title || ariaLabel}
        disabled={disabled || loading}
        className={`${baseStyles} ${sizes[size] || sizes.md} ${variants[variant] || variants.ghost} ${className}`}
        {...rest}
      >
        {loading ? (
          <Spinner size={size === 'xs' || size === 'sm' ? 'xs' : 'sm'} color="teal" />
        ) : (
          children
        )}
      </button>
    );
  },
);

IconButton.displayName = 'IconButton';
export default IconButton;
