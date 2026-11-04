import React from 'react';
import { Check } from 'lucide-react';

/**
 * Stepper Component
 * Progress indicator for multi-stage pipelines (Export -> Transform -> Import -> Sync).
 * Props:
 * @param {Array<{ id: string | number, label: string, description?: string }>} steps
 * @param {number} currentStep - 0-indexed active step
 * @param {(stepIndex: number) => void} onStepClick - Optional step navigation callback
 * @param {string} className
 */
const Stepper = ({ steps = [], currentStep = 0, onStepClick, className = '' }) => {
  return (
    <nav aria-label="Progress" className={`w-full py-2 ${className}`}>
      <ol className="flex items-center w-full">
        {steps.map((step, idx) => {
          const isCompleted = idx < currentStep;
          const isCurrent = idx === currentStep;
          const isPending = idx > currentStep;
          const isClickable = Boolean(onStepClick);

          return (
            <li
              key={step.id || idx}
              className={`relative flex items-center ${idx < steps.length - 1 ? 'flex-1' : ''}`}
            >
              <button
                type="button"
                disabled={!isClickable}
                onClick={() => isClickable && onStepClick(idx)}
                className={`group flex items-center gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 rounded-md p-1 ${
                  isClickable ? 'cursor-pointer' : 'cursor-default'
                }`}
              >
                <span
                  className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs transition-colors flex-shrink-0 ${
                    isCompleted
                      ? 'bg-teal-600 text-white'
                      : isCurrent
                      ? 'bg-teal-50 dark:bg-teal-950 text-teal-700 dark:text-teal-400 border-2 border-teal-600 ring-4 ring-teal-50 dark:ring-teal-950/60'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-500 border border-slate-300 dark:border-slate-700'
                  }`}
                  aria-current={isCurrent ? 'step' : undefined}
                >
                  {isCompleted ? <Check className="w-4 h-4 stroke-[3]" /> : idx + 1}
                </span>

                <div className="hidden sm:block">
                  <span
                    className={`block text-xs font-semibold ${
                      isCurrent
                        ? 'text-teal-700 dark:text-teal-400'
                        : isCompleted
                        ? 'text-slate-800 dark:text-slate-200'
                        : 'text-slate-500 dark:text-slate-400'
                    }`}
                  >
                    {step.label}
                  </span>
                </div>

                {/* Mobile: active step pill label */}
                {isCurrent && (
                  <span className="sm:hidden text-[11px] font-semibold text-teal-700 dark:text-teal-400 bg-teal-50 dark:bg-teal-950/60 px-2 py-0.5 rounded-full whitespace-nowrap">
                    {step.label}
                  </span>
                )}
              </button>

              {idx < steps.length - 1 && (
                <div
                  className={`flex-1 h-0.5 mx-3 sm:mx-4 transition-colors ${
                    isCompleted ? 'bg-teal-600' : 'bg-slate-200 dark:bg-slate-700'
                  }`}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};

export default Stepper;
