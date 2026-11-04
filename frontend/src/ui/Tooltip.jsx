import React, { useState } from 'react';

/**
 * Tooltip Component
 * Accessible hover/focus tooltip using standard CSS/state without external libraries.
 * Props:
 * @param {string | React.ReactNode} content - Tooltip message
 * @param {'top' | 'bottom' | 'left' | 'right'} position (default: 'top')
 * @param {React.ReactNode} children - Trigger element
 * @param {string} className
 */
const Tooltip = ({ content, position = 'top', children, className = '' }) => {
  const [visible, setVisible] = useState(false);

  if (!content) return children;

  const positions = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
    left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
    right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
  };

  return (
    <div
      className={`relative inline-flex ${className}`}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
      onFocus={() => setVisible(true)}
      onBlur={() => setVisible(false)}
    >
      {children}
      {visible && (
        <div
          role="tooltip"
          className={`absolute z-50 px-2 py-1 text-[11px] font-medium text-white bg-slate-900 dark:bg-slate-800 rounded shadow-md whitespace-nowrap pointer-events-none transition-opacity animate-in fade-in duration-100 ${positions[position] || positions.top}`}
        >
          {content}
        </div>
      )}
    </div>
  );
};

export default Tooltip;
