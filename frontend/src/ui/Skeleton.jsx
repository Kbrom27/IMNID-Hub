import React from 'react';

/**
 * Skeleton Component
 * Accessible animated placeholder indicating loading state.
 * Props:
 * @param {'text' | 'circle' | 'card' | 'rect'} variant
 * @param {string | number} width
 * @param {string | number} height
 * @param {string} className
 */
const Skeleton = ({ variant = 'rect', width, height, className = '' }) => {
  const variants = {
    text: 'h-4 w-full rounded',
    circle: 'rounded-full',
    rect: 'rounded-md',
    card: 'h-32 w-full rounded-md',
  };

  const style = {};
  if (width) style.width = typeof width === 'number' ? `${width}px` : width;
  if (height) style.height = typeof height === 'number' ? `${height}px` : height;

  return (
    <div
      aria-hidden="true"
      style={style}
      className={`animate-pulse bg-slate-200/80 dark:bg-slate-800/80 ${variants[variant] || variants.rect} ${className}`}
    />
  );
};

export default Skeleton;
