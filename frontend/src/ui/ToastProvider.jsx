import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X } from 'lucide-react';

const ToastContext = createContext(null);

function formatToastMessage(val) {
  if (val === null || val === undefined) return '';
  if (typeof val === 'string') {
    return val === '[object Object]' ? 'An unexpected error occurred. Please verify your inputs.' : val;
  }
  if (val instanceof Error) {
    const msg = val.message;
    return msg === '[object Object]' ? 'An unexpected error occurred. Please verify your inputs.' : msg;
  }
  if (Array.isArray(val)) {
    return val
      .map((item) => {
        if (typeof item === 'string') return item;
        if (item && item.msg) return item.loc ? `${item.loc.join('.')}: ${item.msg}` : item.msg;
        return JSON.stringify(item);
      })
      .join('; ');
  }
  if (typeof val === 'object') {
    if (val.message !== undefined && val.message !== null) return formatToastMessage(val.message);
    if (val.detail !== undefined && val.detail !== null) return formatToastMessage(val.detail);
    if (val.error !== undefined && val.error !== null) return formatToastMessage(val.error);
    if (val.msg !== undefined && val.msg !== null) return formatToastMessage(val.msg);
    try {
      return JSON.stringify(val);
    } catch {
      return 'An unexpected error occurred.';
    }
  }
  return String(val);
}

/**
 * ToastProvider & useToast
 * Non-blocking accessible toast notifications system replacing browser alert().
 */
export const ToastProvider = ({ children }) => {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((toast) => {
    const id = Math.random().toString(36).substring(2, 9);
    const newToast = {
      id,
      variant: toast.variant || 'info',
      title: toast.title || null,
      message: toast.message || '',
      duration: toast.duration !== undefined ? toast.duration : 4500,
    };

    setToasts((prev) => [...prev, newToast]);

    if (newToast.duration > 0) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, newToast.duration);
    }

    return id;
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = (messageOrObj, variant = 'info', title = null) => {
    if (messageOrObj && typeof messageOrObj === 'object' && !(messageOrObj instanceof Error) && (messageOrObj.variant || messageOrObj.title)) {
      const v = messageOrObj.variant === 'error' ? 'danger' : (messageOrObj.variant || 'info');
      const msg = formatToastMessage(messageOrObj.message ?? messageOrObj.detail ?? messageOrObj.error ?? messageOrObj);
      return addToast({ ...messageOrObj, message: msg, variant: v });
    }
    const v = variant === 'error' ? 'danger' : variant;
    const msg = formatToastMessage(messageOrObj);
    return addToast({ variant: v, message: msg, title });
  };

  const toast = {
    show: addToast,
    showToast,
    success: (message, title) => addToast({ variant: 'success', message, title }),
    error: (message, title) => addToast({ variant: 'danger', message, title, duration: 6000 }),
    warning: (message, title) => addToast({ variant: 'warning', message, title }),
    info: (message, title) => addToast({ variant: 'info', message, title }),
    dismiss: removeToast,
  };

  const icons = {
    success: <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />,
    danger: <AlertCircle className="w-5 h-5 text-rose-600 dark:text-rose-400 flex-shrink-0" />,
    warning: <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 flex-shrink-0" />,
    info: <Info className="w-5 h-5 text-teal-600 dark:text-teal-400 flex-shrink-0" />,
  };

  const borders = {
    success: 'border-emerald-200 dark:border-emerald-800 bg-white dark:bg-slate-900',
    danger: 'border-rose-200 dark:border-rose-800 bg-white dark:bg-slate-900',
    warning: 'border-amber-200 dark:border-amber-800 bg-white dark:bg-slate-900',
    info: 'border-teal-200 dark:border-teal-800 bg-white dark:bg-slate-900',
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {/* Toast viewport */}
      <div
        aria-live="polite"
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2.5 max-w-sm w-full pointer-events-none px-3 sm:px-0"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto flex items-start gap-3 p-3.5 rounded-md border shadow-lg transition-all animate-in slide-in-from-bottom-3 duration-200 ${
              borders[t.variant] || borders.info
            }`}
          >
            {icons[t.variant] || icons.info}
            <div className="flex-1 min-w-0">
              {t.title && (
                <h4 className="text-xs font-bold text-slate-900 dark:text-slate-100 mb-0.5">
                  {t.title}
                </h4>
              )}
              <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed break-words">
                {t.message}
              </p>
            </div>
            <button
              type="button"
              onClick={() => removeToast(t.id)}
              aria-label="Dismiss notification"
              className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
};

export const useToast = () => {
  const context = useContext(ToastContext);
  if (!context) {
    // Fallback if rendered outside provider
    return {
      show: (t) => console.log('Toast:', t),
      showToast: (msg, variant, title) => console.log(`Toast [${variant}]:`, msg, title),
      success: (msg) => console.log('Success:', msg),
      error: (msg) => console.error('Error:', msg),
      warning: (msg) => console.warn('Warning:', msg),
      info: (msg) => console.info('Info:', msg),
      dismiss: () => {},
    };
  }
  return context;
};

export default ToastProvider;
