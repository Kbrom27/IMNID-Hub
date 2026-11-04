import React, { useRef, useState } from 'react';
import { UploadCloud } from 'lucide-react';
import { useToast } from '../../ui/ToastProvider';

/**
 * FileUploadField Component
 * Allows browsing local files to upload to Hub server or typing a server file path directly.
 */
export const FileUploadField = ({
  label,
  value,
  onChange,
  accept = '.csv',
  placeholder = 'Select or upload file...',
  hint,
}) => {
  const fileInputRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const { showToast } = useToast();

  const handleFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/v1/interop/upload', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('imnid_token')}`,
        },
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        onChange(data.filepath);
        showToast(`Uploaded "${file.name}" to server`, 'success');
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(`Upload error: ${err.detail || 'Server error'}`, 'error');
      }
    } catch (err) {
      showToast(`Upload error: ${String(err)}`, 'error');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between items-center">
        <label className="font-bold text-slate-800 dark:text-slate-200 text-sm">{label}</label>
      </div>
      <div className="flex items-center gap-2.5">
        <input
          type="text"
          aria-label={label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="flex-1 text-sm font-mono font-medium border border-slate-300 dark:border-slate-700 rounded-lg py-2.5 px-3.5 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
        />
        <input
          type="file"
          ref={fileInputRef}
          aria-label={`Upload file for ${label}`}
          accept={accept}
          onChange={handleFile}
          className="hidden"
        />
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="px-4 py-2.5 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 border border-slate-300 dark:border-slate-700 rounded-lg text-sm font-semibold text-slate-800 dark:text-slate-200 flex items-center gap-2 transition shrink-0 cursor-pointer"
        >
          <UploadCloud className={`w-4 h-4 text-teal-600 dark:text-teal-400 ${uploading ? 'animate-bounce' : ''}`} />
          <span>{uploading ? 'Uploading...' : 'Browse / Upload'}</span>
        </button>
      </div>
    </div>
  );
};

export default FileUploadField;
