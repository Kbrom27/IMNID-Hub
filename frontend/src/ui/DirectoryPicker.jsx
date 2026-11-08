import React, { useState, useEffect, useRef, useMemo } from 'react';
import {
  FolderOpen,
  HardDrive,
  FolderPlus,
  Check,
  ChevronDown,
  FolderTree,
  X,
  Server,
  FileUp,
  Loader2,
} from 'lucide-react';
import Button from './Button';
import {
  setStoredDirectoryHandle,
  clearStoredDirectoryHandle,
  useStoredDirectoryHandle,
} from '../utils/localFileSystem';

/**
 * DirectoryPicker Component
 *
 * Allows users to select an output directory by:
 * 1. Browsing their local computer folder via native OS Directory Picker dialog.
 * 2. Browsing and selecting from Hub server directories without manual typing.
 * 3. Quick-selecting standard presets via one-click chips.
 * 4. Creating a custom subfolder with one click.
 */
const DirectoryPicker = ({
  value = '/data/exports',
  onChange,
  label = 'Output Directory',
  helperText,
  className = '',
  presetDirs = null,
  allowFileUpload = false,
}) => {
  const [showServerMenu, setShowServerMenu] = useState(false);
  const [serverDirs, setServerDirs] = useState([
    ...(presetDirs && Array.isArray(presetDirs) ? presetDirs.map(p => typeof p === 'string' ? p : p.path) : []),
    '/data/schemas',
    '/data/exports',
    '/data/exports/bahmni',
    '/data/exports/o3',
    '/data/exports/data-export',
    '/data/exports/analysis',
    '/data/exports/archive',
  ]);
  const [newSubfolder, setNewSubfolder] = useState('');
  const [showNewFolderInput, setShowNewFolderInput] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const storedFolder = useStoredDirectoryHandle();
  const [localFolderName, setLocalFolderName] = useState(() => storedFolder?.name || '');

  useEffect(() => {
    if (storedFolder?.name) {
      setLocalFolderName(storedFolder.name);
    }
  }, [storedFolder]);

  const fileInputRef = useRef(null);
  const singleFileInputRef = useRef(null);
  const menuRef = useRef(null);

  // Load available server directories
  useEffect(() => {
    const token =
      localStorage.getItem('imnid_token') ||
      localStorage.getItem('access_token') ||
      '';
    fetch('/api/v1/interop/directories', {
      headers: {
        Authorization: token ? `Bearer ${token}` : '',
      },
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data && Array.isArray(data.directories) && data.directories.length > 0) {
          setServerDirs((prev) => Array.from(new Set([...prev, ...data.directories])));
        }
      })
      .catch(() => {});
  }, []);

  // Close server menu on click outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setShowServerMenu(false);
      }
    };
    if (showServerMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [showServerMenu]);

  const uploadFolderFiles = async (folderName, fileList) => {
    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('folder_name', folderName);
      let count = 0;
      for (const item of fileList) {
        const fileObj = item.file || item;
        const rel = item.relPath || fileObj.webkitRelativePath || fileObj.name;
        formData.append('files', fileObj, rel);
        count++;
      }
      const token =
        localStorage.getItem('imnid_token') ||
        localStorage.getItem('access_token') ||
        localStorage.getItem('token') ||
        '';
      const res = await fetch('/api/concepts/upload-folder', {
        method: 'POST',
        headers: {
          Authorization: token ? `Bearer ${token}` : '',
        },
        body: formData,
      });
      if (res.ok) {
        const data = await res.json();
        const serverPath = data.folder_path || `/data/uploads/${folderName}`;
        setLocalFolderName(`${folderName} (${count} file${count === 1 ? '' : 's'} uploaded)`);
        onChange(serverPath);
        setShowServerMenu(false);
        setIsUploading(false);
        return true;
      } else {
        const errData = await res.json().catch(() => null);
        const errMsg = errData?.detail || `Upload failed with HTTP ${res.status}`;
        console.error('Folder upload failed:', errMsg);
        alert(`Failed to upload folder files to server: ${errMsg}`);
      }
    } catch (err) {
      console.error('Folder upload error:', err);
      alert(`Folder upload error: ${err.message || err}`);
    }
    setIsUploading(false);
    return false;
  };

  const collectFilesFromHandle = async (handle, path = '') => {
    const collected = [];
    for await (const entry of handle.values()) {
      const relPath = path ? `${path}/${entry.name}` : entry.name;
      if (entry.kind === 'file') {
        try {
          const file = await entry.getFile();
          collected.push({ file, relPath });
        } catch (e) {
          console.warn('Cannot read file:', entry.name, e);
        }
      } else if (entry.kind === 'directory') {
        try {
          const subFiles = await collectFilesFromHandle(entry, relPath);
          collected.push(...subFiles);
        } catch (e) {
          console.warn('Cannot read directory:', entry.name, e);
        }
      }
    }
    return collected;
  };

  // Browse local folder on the user's computer using native OS dialog
  const handleBrowseLocal = async () => {
    if (typeof window !== 'undefined' && 'showDirectoryPicker' in window) {
      try {
        if (!allowFileUpload) {
          // Output / Export destination folder mode
          const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
          if (dirHandle && dirHandle.name) {
            if (typeof dirHandle.requestPermission === 'function') {
              try {
                await dirHandle.requestPermission({ mode: 'readwrite' });
              } catch (permErr) {
                console.warn('Could not request readwrite permission:', permErr);
              }
            }
            setStoredDirectoryHandle(dirHandle, dirHandle.name);
            setLocalFolderName(dirHandle.name);
            onChange(`[Local Folder] ${dirHandle.name}`);
            setShowServerMenu(false);
            return;
          }
        } else {
          // Upload / Import source folder mode (e.g. schemas, concept trees)
          const dirHandle = await window.showDirectoryPicker({ mode: 'read' });
          if (dirHandle && dirHandle.name) {
            setStoredDirectoryHandle(dirHandle, dirHandle.name);
            const files = await collectFilesFromHandle(dirHandle);
            if (files.length > 0) {
              const ok = await uploadFolderFiles(dirHandle.name, files);
              if (ok) return;
            } else {
              alert(`No files were found in "${dirHandle.name}". Please pick a folder containing CSV or concept files.`);
              return;
            }
          }
        }
      } catch (err) {
        if (err.name === 'AbortError') {
          return; // User canceled
        }
        if (allowFileUpload) {
          fileInputRef.current?.click();
          return;
        } else {
          console.warn('Directory picker error:', err);
        }
      }
    }
    if (allowFileUpload && fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileInputChange = async (e) => {
    const fileList = e.target.files;
    if (fileList && fileList.length > 0) {
      const relativePath = fileList[0].webkitRelativePath || '';
      const folderName = relativePath.split('/')[0] || 'uploaded_folder';
      const ok = await uploadFolderFiles(folderName, Array.from(fileList));
      if (!ok) {
        const resolved = `/data/uploads/${folderName}`;
        setLocalFolderName(folderName);
        onChange(resolved);
        setShowServerMenu(false);
      }
    }
    e.target.value = '';
  };

  const handleSingleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (file) {
      setIsUploading(true);
      try {
        const formData = new FormData();
        formData.append('file', file);
        const token =
          localStorage.getItem('imnid_token') ||
          localStorage.getItem('access_token') ||
          localStorage.getItem('token') ||
          '';
        const res = await fetch('/api/concepts/upload', {
          method: 'POST',
          headers: {
            Authorization: token ? `Bearer ${token}` : '',
          },
          body: formData,
        });
        if (res.ok) {
          const data = await res.json();
          const serverPath = data.filepath || `/data/uploads/${file.name}`;
          setLocalFolderName(`${file.name} (uploaded)`);
          onChange(serverPath);
          setShowServerMenu(false);
        } else {
          const errData = await res.json().catch(() => null);
          alert(`File upload failed: ${errData?.detail || res.status}`);
        }
      } catch (err) {
        console.error('File upload error:', err);
        alert(`File upload error: ${err.message || err}`);
      }
      setIsUploading(false);
    }
    e.target.value = '';
  };

  const handleSelectPreset = (dirPath) => {
    onChange(dirPath);
    setLocalFolderName('');
    clearStoredDirectoryHandle();
    setShowServerMenu(false);
  };

  const handleCreateSubfolder = (e) => {
    e.preventDefault();
    const cleaned = newSubfolder.trim().replace(/^[\/\\]+/, '');
    if (!cleaned) return;
    const fullPath = `/data/exports/${cleaned}`;
    if (!serverDirs.includes(fullPath)) {
      setServerDirs((prev) => [...prev, fullPath]);
    }
    onChange(fullPath);
    setNewSubfolder('');
    clearStoredDirectoryHandle();
    setShowNewFolderInput(false);
    setShowServerMenu(false);
  };

  const commonPresets = useMemo(() => {
    if (presetDirs && Array.isArray(presetDirs) && presetDirs.length > 0) {
      return presetDirs.map((p) => {
        if (typeof p === 'string') {
          const parts = p.split('/').filter(Boolean);
          const label = parts.length > 1 ? parts.slice(-2).join('/') : (parts[0] || p);
          return { label, path: p };
        }
        return p;
      });
    }
    return [
      { label: 'Default', path: '/data/exports' },
      { label: 'Bahmni', path: '/data/exports/bahmni' },
      { label: 'O3', path: '/data/exports/o3' },
      { label: 'Data Export', path: '/data/exports/data-export' },
      { label: 'Analysis', path: '/data/exports/analysis' },
    ];
  }, [presetDirs]);

  return (
    <div className={`space-y-1.5 ${className}`}>
      {/* Hidden file input for browsers without showDirectoryPicker (folder) */}
      <input
        ref={fileInputRef}
        type="file"
        webkitdirectory="true"
        directory="true"
        multiple
        className="hidden"
        onChange={handleFileInputChange}
      />

      {/* Hidden single file input for .json and .zip files */}
      <input
        ref={singleFileInputRef}
        type="file"
        accept=".json,.zip"
        className="hidden"
        onChange={handleSingleFileChange}
      />

      {/* Label and Source indicator */}
      <div className="flex items-center justify-between">
        <label className="block text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
          <FolderOpen className="w-4 h-4 text-teal-600 dark:text-teal-400" />
          <span>{label}</span>
        </label>
        {isUploading ? (
          <span className="text-xs font-semibold text-teal-600 dark:text-teal-400 flex items-center gap-1.5 bg-teal-50 dark:bg-teal-950/40 px-2.5 py-1 rounded-lg animate-pulse">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Uploading to server...
          </span>
        ) : localFolderName ? (
          <span className="text-xs font-semibold text-emerald-600 dark:text-emerald-400 flex items-center gap-1.5 bg-emerald-50 dark:bg-emerald-950/40 px-2.5 py-1 rounded-lg border border-emerald-500/20">
            <HardDrive className="w-3.5 h-3.5" />
            <span>Local: {localFolderName}</span>
            <button
              type="button"
              onClick={() => {
                setLocalFolderName('');
                clearStoredDirectoryHandle();
                onChange('/data/exports');
              }}
              className="text-slate-400 hover:text-rose-500 transition-colors ml-1"
              title="Clear local folder selection"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </span>
        ) : null}
      </div>

      {/* Main Input + Browse Controls */}
      <div className="relative" ref={menuRef}>
        <div className="flex items-center gap-2">
          {/* Output path display / editable input */}
          <div className="relative flex-1">
            <input
              type="text"
              value={value || ''}
              onChange={(e) => {
                onChange(e.target.value);
                setLocalFolderName('');
              }}
              placeholder="/data/schemas"
              className="w-full h-11 px-3.5 pl-10 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 text-sm font-mono font-medium focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition-colors"
            />
            <FolderOpen className="w-4 h-4 text-slate-400 absolute left-3.5 top-3.5 pointer-events-none" />
          </div>

          {/* Browse Local Folder Button */}
          <Button
            type="button"
            variant="secondary"
            size="md"
            icon={isUploading ? <Loader2 className="w-4 h-4 animate-spin text-teal-600" /> : <HardDrive className="w-4 h-4 text-teal-600 dark:text-teal-400" />}
            onClick={handleBrowseLocal}
            disabled={isUploading}
            title="Browse folder on your local computer to upload"
            className="shrink-0 font-medium text-slate-700 dark:text-slate-200"
          >
            {isUploading ? 'Uploading...' : 'Browse Local...'}
          </Button>

          {/* Browse File Button (only for upload/import contexts) */}
          {allowFileUpload && (
            <Button
              type="button"
              variant="secondary"
              size="md"
              icon={<FileUp className="w-4 h-4 text-teal-600 dark:text-teal-400" />}
              onClick={() => singleFileInputRef.current?.click()}
              disabled={isUploading}
              title="Upload a single schema JSON or ZIP file from computer"
              className="shrink-0 font-medium text-slate-700 dark:text-slate-200"
            >
              Upload File...
            </Button>
          )}

          {/* Browse Server / Preset Folders Menu Button */}
          <Button
            type="button"
            variant="secondary"
            size="md"
            icon={<Server className="w-4 h-4 text-slate-600 dark:text-slate-300" />}
            onClick={() => setShowServerMenu(!showServerMenu)}
            title="Select from server directories and preset folders"
            aria-label="Select from server directories and preset folders"
            className="shrink-0 font-medium text-slate-700 dark:text-slate-200 border border-slate-300 dark:border-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <span>Server Folders</span>
            <ChevronDown className="w-3.5 h-3.5 ml-1 text-slate-400" />
          </Button>
        </div>

        {/* Server & Presets Dropdown Popover */}
        {showServerMenu && (
          <div className="absolute right-0 top-full mt-1.5 w-80 bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-xl z-50 overflow-hidden divide-y divide-slate-100 dark:divide-slate-800 animate-in fade-in zoom-in-95 duration-100">
            {/* Header */}
            <div className="px-3.5 py-2.5 bg-slate-50 dark:bg-slate-850 flex items-center justify-between">
              <span className="text-xs font-bold text-slate-700 dark:text-slate-200 flex items-center gap-1.5">
                <FolderTree className="w-3.5 h-3.5 text-teal-600" />
                Select Output Folder
              </span>
              <button
                type="button"
                onClick={() => setShowServerMenu(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* Quick Actions */}
            <div className="p-2 space-y-1">
              <button
                type="button"
                onClick={handleBrowseLocal}
                className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-xs font-semibold text-slate-800 dark:text-slate-200 hover:bg-teal-50 dark:hover:bg-teal-950/40 hover:text-teal-700 dark:hover:text-teal-300 transition text-left"
              >
                <HardDrive className="w-4 h-4 text-teal-600 shrink-0" />
                <span>Browse Local Computer...</span>
              </button>
            </div>

            {/* Available Directories List */}
            <div className="max-h-52 overflow-y-auto p-1.5 space-y-0.5">
              <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                Server Output Folders
              </div>
              {serverDirs.map((dir) => {
                const isSelected = value === dir;
                return (
                  <button
                    key={dir}
                    type="button"
                    onClick={() => handleSelectPreset(dir)}
                    className={`w-full flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs font-mono transition text-left ${
                      isSelected
                        ? 'bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 font-semibold'
                        : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`}
                  >
                    <span className="truncate">{dir}</span>
                    {isSelected && <Check className="w-3.5 h-3.5 text-teal-600 shrink-0 ml-1.5" />}
                  </button>
                );
              })}
            </div>

            {/* Create Subfolder Option */}
            <div className="p-2.5 bg-slate-50/50 dark:bg-slate-850/50">
              {!showNewFolderInput ? (
                <button
                  type="button"
                  onClick={() => setShowNewFolderInput(true)}
                  className="w-full flex items-center justify-center gap-1.5 py-1 text-xs font-medium text-teal-600 dark:text-teal-400 hover:text-teal-700"
                >
                  <FolderPlus className="w-3.5 h-3.5" />
                  <span>+ Create Subfolder</span>
                </button>
              ) : (
                <form onSubmit={handleCreateSubfolder} className="space-y-1.5">
                  <div className="text-[11px] font-medium text-slate-600 dark:text-slate-400">
                    New subfolder under /data/exports/:
                  </div>
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      value={newSubfolder}
                      onChange={(e) => setNewSubfolder(e.target.value)}
                      placeholder="e.g. batch_export"
                      autoFocus
                      className="flex-1 h-7 px-2 rounded border border-slate-300 dark:border-slate-700 text-xs bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-100 font-mono"
                    />
                    <button
                      type="submit"
                      disabled={!newSubfolder.trim()}
                      className="px-2.5 py-1 bg-teal-600 hover:bg-teal-700 disabled:opacity-50 text-white rounded text-xs font-semibold"
                    >
                      Add
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Preset Chips Bar for 1-Click Selection (min 28px height, 12px text) */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">Presets:</span>
        {commonPresets.map((preset) => {
          const isSelected = value === preset.path;
          return (
            <button
              key={preset.path}
              type="button"
              onClick={() => handleSelectPreset(preset.path)}
              className={`min-h-[28px] px-3 py-1 rounded-lg text-xs font-semibold transition-colors flex items-center shadow-2xs ${
                isSelected
                  ? 'bg-teal-100 dark:bg-teal-900/60 text-teal-800 dark:text-teal-200 border border-teal-300 dark:border-teal-700 font-bold'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 border border-slate-200 dark:border-slate-700/60'
              }`}
            >
              {preset.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default DirectoryPicker;
