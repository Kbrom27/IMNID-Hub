import React, { useState, useRef } from 'react';
import { UploadCloud, FileText, CheckCircle2, X, AlertCircle } from 'lucide-react';
import Button from './Button';
import Spinner from './Spinner';

/**
 * FileDropzone Component
 * Prominent drag-and-drop file uploader with validation, file details, and remove action.
 */
const FileDropzone = ({
  id,
  accept = '.csv,.xlsx,.json',
  file = null,
  value = null,
  filePath = '',
  onFileSelect,
  onChange,
  onRemove,
  uploading = false,
  label,
  hint,
  helperText,
  error,
  compact = false,
  disabled = false,
  className = '',
  maxSize,
}) => {
  const [isDragOver, setIsDragOver] = useState(false);
  const inputRef = useRef(null);

  const activeFile = file || value || null;
  const activeHint = hint || helperText || '';

  const notifyFileSelected = (selected) => {
    if (onFileSelect) onFileSelect(selected);
    if (onChange) onChange(selected);
  };

  const notifyFileRemoved = () => {
    if (onRemove) onRemove();
    if (onChange) onChange(null);
    if (onFileSelect) onFileSelect(null);
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    if (!disabled && !uploading) setIsDragOver(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragOver(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragOver(false);
    if (disabled || uploading) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFile = e.dataTransfer.files[0];
      notifyFileSelected(droppedFile);
    }
  };

  const handleChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      const selected = e.target.files[0];
      notifyFileSelected(selected);
    }
  };

  const formatFileSize = (bytes) => {
    if (!bytes && bytes !== 0) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const hasFile = Boolean(activeFile || filePath);
  const displayName = activeFile ? activeFile.name : filePath ? filePath.split('/').pop() : '';
  const displaySize = activeFile ? formatFileSize(activeFile.size) : '';

  if (compact) {
    return (
      <div className={`space-y-1.5 ${className}`}>
        {label && (
          <label htmlFor={id} className="block font-bold text-sm text-slate-800 dark:text-slate-200">
            {label}
          </label>
        )}
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`flex items-center justify-between p-3.5 rounded-xl border text-sm transition-all ${
            isDragOver
              ? 'border-teal-500 bg-teal-50/60 dark:bg-teal-950/40'
              : hasFile
              ? 'border-teal-400 dark:border-teal-700 bg-teal-50/30 dark:bg-teal-950/20'
              : error
              ? 'border-rose-300 dark:border-rose-800 bg-rose-50/30 dark:bg-rose-950/20'
              : 'border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900'
          }`}
        >
          <input
            ref={inputRef}
            id={id}
            type="file"
            accept={accept}
            onChange={handleChange}
            disabled={disabled || uploading}
            className="hidden"
          />

          <div className="flex items-center gap-3 min-w-0 flex-1">
            {uploading ? (
              <Spinner size="sm" color="teal" />
            ) : hasFile ? (
              <FileText className="w-5 h-5 text-teal-600 dark:text-teal-400 flex-shrink-0" />
            ) : (
              <UploadCloud className="w-5 h-5 text-slate-400 flex-shrink-0" />
            )}

            <div className="min-w-0 flex-1">
              {hasFile ? (
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-900 dark:text-slate-100 truncate text-sm">{displayName}</span>
                  {displaySize && <span className="text-xs text-slate-400">({displaySize})</span>}
                </div>
              ) : (
                <span className="text-slate-500 dark:text-slate-400 text-sm">
                  {activeHint || 'Choose a file or drag & drop'}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 ml-2">
            {hasFile ? (
              <button
                type="button"
                onClick={() => {
                  if (inputRef.current) inputRef.current.value = '';
                  notifyFileRemoved();
                }}
                disabled={disabled || uploading}
                aria-label="Remove selected file"
                className="p-1.5 text-slate-400 hover:text-rose-600 rounded-lg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            ) : (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => inputRef.current?.click()}
                disabled={disabled || uploading}
              >
                Browse
              </Button>
            )}
          </div>
        </div>

        {error && (
          <p className="text-xs font-semibold text-rose-600 dark:text-rose-400 flex items-center gap-1 mt-1">
            <AlertCircle className="w-4 h-4" />
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={`space-y-2 ${className}`}>
      {label && (
        <label htmlFor={id} className="block font-semibold text-sm text-slate-800 dark:text-slate-200">
          {label}
        </label>
      )}

      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => !hasFile && !disabled && !uploading && inputRef.current?.click()}
        className={`relative rounded-xl border border-dashed py-7 px-6 min-h-[130px] flex items-center justify-center transition-all ${
          disabled ? 'opacity-50 cursor-not-allowed' : hasFile ? 'cursor-default' : 'cursor-pointer'
        } ${
          isDragOver
            ? 'border-teal-500 bg-teal-50/70 dark:bg-teal-950/40 ring-2 ring-teal-500/20'
            : hasFile
            ? 'border-teal-400/80 dark:border-teal-700 bg-teal-50/30 dark:bg-teal-950/20'
            : error
            ? 'border-rose-400 dark:border-rose-700 bg-rose-50/20 dark:bg-rose-950/20'
            : 'border-slate-300 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-900/60 hover:bg-slate-50 dark:hover:bg-slate-850 hover:border-teal-500/60'
        }`}
      >
        <input
          ref={inputRef}
          id={id}
          type="file"
          accept={accept}
          onChange={handleChange}
          disabled={disabled || uploading}
          className="hidden"
        />

        {uploading ? (
          <div className="flex flex-col items-center justify-center gap-2 py-2">
            <Spinner size="md" color="teal" />
            <span className="text-sm font-semibold text-teal-700 dark:text-teal-400">Uploading file...</span>
          </div>
        ) : hasFile ? (
          <div className="flex items-center justify-between gap-3 w-full text-left">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-10 h-10 rounded-xl bg-teal-100 dark:bg-teal-900/60 text-teal-700 dark:text-teal-300 flex items-center justify-center flex-shrink-0">
                <FileText className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100 truncate">{displayName}</p>
                {displaySize && <span className="text-xs font-sans tabular-nums text-slate-500 dark:text-slate-400">{displaySize}</span>}
              </div>
            </div>

            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                if (inputRef.current) inputRef.current.value = '';
                notifyFileRemoved();
              }}
              aria-label="Remove file"
              className="text-rose-600 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/40 text-xs font-semibold p-1.5 h-8"
            >
              <X className="w-4 h-4 mr-1" />
              Remove
            </Button>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-2 text-center">
            <div className="w-10 h-10 rounded-xl bg-teal-50 dark:bg-teal-950/60 border border-teal-200 dark:border-teal-800/60 flex items-center justify-center text-teal-600 dark:text-teal-400 flex-shrink-0">
              <UploadCloud className="w-5 h-5" />
            </div>
            <div className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Drop file here, or <span className="text-teal-600 dark:text-teal-400 underline decoration-1 underline-offset-2">browse files</span>
            </div>
          </div>
        )}
      </div>

      {error && (
        <p className="text-xs font-semibold text-rose-600 dark:text-rose-400 flex items-center gap-1 mt-1">
          <AlertCircle className="w-3.5 h-3.5" />
          {error}
        </p>
      )}
    </div>
  );
};

export default FileDropzone;
