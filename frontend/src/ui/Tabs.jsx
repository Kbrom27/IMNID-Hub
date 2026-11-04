import React from 'react';

/**
 * Tabs Component
 * Accessible tabs with keyboard support and active underline or pill.
 * Props:
 * @param {Array<{ id: string, label: string, icon?: React.ReactNode, count?: number | string, disabled?: boolean }>} items
 * @param {string} activeId - Currently active tab ID
 * @param {(id: string) => void} onChange - Callback on selection change
 * @param {'underline' | 'pills' | 'segmented'} variant (default: 'pills')
 * @param {'sm' | 'md'} size (default: 'md')
 * @param {string} className
 */
const Tabs = ({
  items = [],
  activeId,
  onChange,
  variant = 'pills',
  size = 'md',
  className = '',
}) => {
  const handleKeyDown = (e, index) => {
    let nextIndex = null;
    if (e.key === 'ArrowRight') {
      nextIndex = (index + 1) % items.length;
    } else if (e.key === 'ArrowLeft') {
      nextIndex = (index - 1 + items.length) % items.length;
    }
    if (nextIndex !== null) {
      e.preventDefault();
      const nextItem = items[nextIndex];
      if (nextItem && !nextItem.disabled) {
        onChange(nextItem.id);
      }
    }
  };

  const sizes = {
    sm: 'text-xs py-1.5 px-3 gap-1.5',
    md: 'text-sm py-2 px-3.5 gap-2',
  };

  if (variant === 'segmented') {
    return (
      <div
        role="tablist"
        aria-orientation="horizontal"
        className={`inline-flex p-1 bg-slate-100 dark:bg-slate-800 rounded-md border border-slate-200 dark:border-slate-700 max-w-full overflow-x-auto ${className}`}
      >
        {items.map((item, index) => {
          const isActive = item.id === activeId;
          return (
            <button
              key={item.id}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${item.id}`}
              id={`tab-${item.id}`}
              tabIndex={isActive ? 0 : -1}
              disabled={item.disabled}
              onClick={() => !item.disabled && onChange(item.id)}
              onKeyDown={(e) => handleKeyDown(e, index)}
              className={`inline-flex items-center justify-center font-medium rounded-sm transition-all whitespace-nowrap select-none ${
                sizes[size]
              } ${
                isActive
                  ? 'bg-white dark:bg-slate-900 text-teal-700 dark:text-teal-400 shadow-xs font-semibold'
                  : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-200/50'
              } ${item.disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
            >
              {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
              <span>{item.label}</span>
              {item.count !== undefined && (
                <span
                  className={`ml-1 text-[11px] px-1.5 py-0.2 rounded-full font-semibold ${
                    isActive
                      ? 'bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300'
                      : 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-300'
                  }`}
                >
                  {item.count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div
      role="tablist"
      aria-orientation="horizontal"
      className={`flex items-center gap-1 border-b border-slate-200 dark:border-slate-800 overflow-x-auto no-scrollbar ${className}`}
    >
      {items.map((item, index) => {
        const isActive = item.id === activeId;
        return (
          <button
            key={item.id}
            role="tab"
            aria-selected={isActive}
            aria-controls={`panel-${item.id}`}
            id={`tab-${item.id}`}
            tabIndex={isActive ? 0 : -1}
            disabled={item.disabled}
            onClick={() => !item.disabled && onChange(item.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            className={`inline-flex items-center font-medium border-b-2 transition-all whitespace-nowrap select-none ${
              sizes[size]
            } ${
              isActive
                ? 'border-teal-600 text-teal-700 dark:text-teal-400 dark:border-teal-400 font-semibold'
                : 'border-transparent text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:border-slate-300'
            } ${item.disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
          >
            {item.icon && <span className="flex-shrink-0">{item.icon}</span>}
            <span>{item.label}</span>
            {item.count !== undefined && (
              <span
                className={`ml-1 text-[11px] px-1.5 py-0.2 rounded-full font-semibold ${
                  isActive
                    ? 'bg-teal-100 text-teal-800 dark:bg-teal-950 dark:text-teal-300'
                    : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                }`}
              >
                {item.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
};

export default Tabs;
