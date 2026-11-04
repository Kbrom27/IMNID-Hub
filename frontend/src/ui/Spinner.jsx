import React from 'react';

/**
 * Spinner Component
 * Props:
 * @param {'xs' | 'sm' | 'md' | 'lg'} size - Spinner dimensions (default: 'md')
 * @param {'teal' | 'white' | 'slate'} color - Spinner stroke color (default: 'teal')
 * @param {string} className - Additional CSS class names
 * @param {string} label - Accessible ARIA label (default: 'Loading...')
 */
const Spinner = ({ size = 'md', color = 'teal', className = '', label = 'Loading...' }) => {
  const sizes = {
    xs: 'w-3 h-3 border-[1.5px]',
    sm: 'w-4 h-4 border-2',
    md: 'w-6 h-6 border-2',
    lg: 'w-8 h-8 border-3',
  };

  const colors = {
    teal: 'border-slate-200 border-t-teal-600 dark:border-slate-700 dark:border-t-teal-400',
    white: 'border-white/30 border-t-white',
    slate: 'border-slate-200 border-t-slate-600 dark:border-slate-700 dark:border-t-slate-300',
  };

  return (
    <div
      role="status"
      aria-label={label}
      className={`inline-block rounded-full animate-spin ${sizes[size] || sizes.md} ${colors[color] || colors.teal} ${className}`}
    >
      <span className="sr-only">{label}</span>
    </div>
  );
};

export default Spinner;
