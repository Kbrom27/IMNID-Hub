import React from 'react';

/**
 * KeyValueList Component
 * Displays metadata pairs cleanly in stacked or horizontal alignment.
 * Props:
 * @param {Array<{ label: string, value: React.ReactNode, copyable?: boolean, mono?: boolean }>} items
 * @param {'horizontal' | 'stacked'} layout (default: 'horizontal')
 * @param {string} className
 */
const KeyValueList = ({ items = [], layout = 'horizontal', className = '' }) => {
  return (
    <dl
      className={`divide-y divide-slate-100 dark:divide-slate-800 text-xs sm:text-sm ${className}`}
    >
      {items.map((item, idx) => (
        <div
          key={idx}
          className={`py-2.5 flex ${
            layout === 'stacked'
              ? 'flex-col gap-0.5'
              : 'flex-row items-center justify-between gap-4'
          }`}
        >
          <dt className="text-slate-500 dark:text-slate-400 font-medium">{item.label}</dt>
          <dd
            className={`font-semibold text-slate-800 dark:text-slate-200 text-right ${
              item.mono ? 'font-mono text-xs' : ''
            }`}
          >
            {item.value !== undefined && item.value !== null && item.value !== '' ? (
              item.value
            ) : (
              <span className="text-slate-400 italic">Not set</span>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
};

export default KeyValueList;
