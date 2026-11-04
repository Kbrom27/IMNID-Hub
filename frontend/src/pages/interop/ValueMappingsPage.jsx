import React, { useState, useEffect, useMemo } from 'react';
import {
  Save,
  Plus,
  Trash2,
  Search,
  Check,
  AlertTriangle,
  History,
  FileText,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Upload,
  FolderOpen,
} from 'lucide-react';
import {
  PageHeader,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Button,
  Select,
  Alert,
  Modal,
  Badge,
} from '../../ui';
import { useToast } from '../../ui/ToastProvider';
import { useAuth } from '../../context/AuthContext';

/**
 * Value Mappings Editor Page
 * Exact translation dictionary from EMR concept answers to DHIS2 Tracker option codes.
 * Dynamic header parsing, search, pagination, backup/restore, and persistent volume storage.
 */
const ValueMappingsPage = () => {
  const { authHeader, isViewer } = useAuth();
  const { showToast } = useToast();

  const [valSystem, setValSystem] = useState('bahmni');
  const [valProgram, setValProgram] = useState('maternal');
  const [customPath, setCustomPath] = useState('');

  const [meta, setMeta] = useState(null);
  const [originalData, setOriginalData] = useState([]);
  const [mappingData, setMappingData] = useState([]);
  const [fieldnames, setFieldnames] = useState([]);
  const [mappingFilter, setMappingFilter] = useState('');
  const [savingMapping, setSavingMapping] = useState(false);
  const [mappingMessage, setMappingMessage] = useState(null);

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);

  // Modals & Backups
  const [showConfirmSave, setShowConfirmSave] = useState(false);
  const [showBackupsModal, setShowBackupsModal] = useState(false);
  const [backupsList, setBackupsList] = useState([]);
  const [loadingBackups, setLoadingBackups] = useState(false);
  const [restoringBackup, setRestoringBackup] = useState(false);

  // Alternative files for placeholder
  const [availableFiles, setAvailableFiles] = useState([]);

  // Fetch Available Files for switcher
  const fetchAvailableFiles = async () => {
    try {
      const res = await fetch('/api/v1/interop/mappings/values/files', {
        headers: authHeader(),
      });
      if (res.ok) {
        const data = await res.json();
        setAvailableFiles(data.files || []);
      }
    } catch (e) {
      console.error('Failed to list files:', e);
    }
  };

  const fetchMappings = async (targetCustomPath = null) => {
    try {
      let url = `/api/v1/interop/mappings/values?system=${valSystem}&program=${valProgram}`;
      if (targetCustomPath) {
        url += `&custom_path=${encodeURIComponent(targetCustomPath)}`;
      }
      const res = await fetch(url, { headers: authHeader() });
      if (res.ok) {
        const data = await res.json();
        setMeta(data);
        setFieldnames(data.fieldnames || []);
        const rows = data.mappings || [];
        setMappingData(rows);
        setOriginalData(JSON.parse(JSON.stringify(rows)));
        setPage(1);
      }
    } catch (err) {
      console.error('Failed to load mappings:', err);
    }
  };

  useEffect(() => {
    setCustomPath('');
    fetchMappings();
    fetchAvailableFiles();
  }, [valSystem, valProgram]);

  const isDirty = useMemo(() => {
    if (mappingData.length !== originalData.length) return true;
    return JSON.stringify(mappingData) !== JSON.stringify(originalData);
  }, [mappingData, originalData]);

  const handleSelectAlternativeFile = (path) => {
    setCustomPath(path);
    fetchMappings(path);
  };

  const handleSaveConfirm = async () => {
    setShowConfirmSave(false);
    setSavingMapping(true);
    setMappingMessage(null);
    try {
      const res = await fetch('/api/v1/interop/mappings/values', {
        method: 'PUT',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system: valSystem,
          program: valProgram,
          mappings: mappingData,
          custom_filename: meta?.filename || null,
        }),
      });
      if (res.ok) {
        const result = await res.json();
        showToast('Value mappings saved successfully to persistent volume.', 'success');
        setMappingMessage({
          type: 'success',
          text: `Saved ${result.saved_count} row(s) to ${result.file_path}. Backup created at: ${result.backup_path || 'backups'}`,
        });
        setOriginalData(JSON.parse(JSON.stringify(mappingData)));
        fetchMappings(customPath || null);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || 'Failed to update mappings.', 'error');
        setMappingMessage({ type: 'error', text: err.detail || 'Failed to update mappings.' });
      }
    } catch (err) {
      showToast(String(err), 'error');
      setMappingMessage({ type: 'error', text: String(err) });
    } finally {
      setSavingMapping(false);
    }
  };

  const fetchBackups = async () => {
    setLoadingBackups(true);
    try {
      const res = await fetch(
        `/api/v1/interop/mappings/values/backups?system=${valSystem}&program=${valProgram}`,
        { headers: authHeader() }
      );
      if (res.ok) {
        const data = await res.json();
        setBackupsList(data.backups || []);
      }
    } catch (e) {
      console.error('Failed to load backups:', e);
    } finally {
      setLoadingBackups(false);
    }
  };

  const handleOpenBackups = () => {
    fetchBackups();
    setShowBackupsModal(true);
  };

  const handleRestore = async (backupFilename) => {
    if (!window.confirm(`Restore mapping from backup "${backupFilename}"? Current file will be archived.`)) {
      return;
    }
    setRestoringBackup(true);
    try {
      const res = await fetch('/api/v1/interop/mappings/values/restore', {
        method: 'POST',
        headers: { ...authHeader(), 'Content-Type': 'application/json' },
        body: JSON.stringify({
          system: valSystem,
          program: valProgram,
          backup_filename: backupFilename,
        }),
      });
      if (res.ok) {
        showToast('Backup restored successfully!', 'success');
        setShowBackupsModal(false);
        fetchMappings();
      } else {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || 'Failed to restore backup.', 'error');
      }
    } catch (e) {
      showToast(String(e), 'error');
    } finally {
      setRestoringBackup(false);
    }
  };

  const handleAddRow = () => {
    const newRow = {};
    fieldnames.forEach((fn) => {
      newRow[fn] = '';
    });
    setMappingData([newRow, ...mappingData]);
  };

  const filteredData = useMemo(() => {
    if (!mappingFilter) return mappingData;
    const q = mappingFilter.toLowerCase();
    return mappingData.filter((row) =>
      Object.values(row).some((val) => String(val || '').toLowerCase().includes(q))
    );
  }, [mappingData, mappingFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredData.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const paginatedData = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredData.slice(start, start + pageSize);
  }, [filteredData, currentPage, pageSize]);

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="Interoperability Value Mappings"
        description="Translate EMR concept answers to DHIS2 Tracker option codes"
        breadcrumbs={[
          { label: 'Interoperability', href: '/interop' },
          { label: 'Value Mappings' },
        ]}
      />

      <Card>
        <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <CardTitle>Value Mapping Rules</CardTitle>
              {isDirty && (
                <Badge variant="warning" size="sm">
                  Unsaved Changes
                </Badge>
              )}
              {meta?.is_custom_saved && (
                <Badge variant="info" size="sm">
                  Active (Volume Storage)
                </Badge>
              )}
            </div>
            <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              File: <span className="font-mono text-slate-700 dark:text-slate-300 font-semibold">{meta?.filename || 'Loading...'}</span>
              {' • '}
              <span className="font-semibold text-slate-800 dark:text-slate-200">{mappingData.length.toLocaleString()}</span> total rows
            </div>
          </div>

          <div className="flex flex-col sm:flex-row flex-wrap sm:items-center gap-3 w-full sm:w-auto">
            <div className="w-full sm:w-44">
              <Select
                aria-label="Target System"
                value={valSystem}
                onChange={(e) => setValSystem(e.target.value)}
                options={[
                  { value: 'bahmni', label: 'Bahmni (OpenMRS 2.x)' },
                  { value: 'o3', label: 'OpenMRS 3.x' },
                ]}
              />
            </div>
            <div className="w-full sm:w-48">
              <Select
                aria-label="Target Program"
                value={valProgram}
                onChange={(e) => setValProgram(e.target.value)}
                options={[
                  { value: 'maternal', label: 'Maternal Inpatient' },
                  { value: 'neonatal', label: 'Neonatal Care Form' },
                ]}
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<History className="w-3.5 h-3.5" />}
                onClick={handleOpenBackups}
              >
                Restore Previous Version
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={<Plus className="w-3.5 h-3.5" />}
                onClick={handleAddRow}
              >
                Add Row
              </Button>
              <Button
                variant="primary"
                size="sm"
                icon={<Save className="w-3.5 h-3.5" />}
                loading={savingMapping}
                disabled={isViewer || !isDirty}
                onClick={() => setShowConfirmSave(true)}
              >
                Save Changes
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4 pt-4">
          {/* Placeholder Alert & File Switcher */}
          {meta?.is_placeholder && (
            <div className="p-4 rounded-xl border border-amber-200 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 space-y-3">
              <div className="flex items-start gap-3">
                <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                <div className="flex-1">
                  <h4 className="text-sm font-bold text-amber-900 dark:text-amber-200">
                    This file has no mappings (placeholder). Upload or select a mapping file.
                  </h4>
                  <p className="text-xs text-amber-800/90 dark:text-amber-300/90 mt-1">
                    The currently loaded file contains only a schema stub. Select an alternative available mapping file or keep this file and add rows.
                  </p>
                </div>
              </div>

              {availableFiles.length > 0 && (
                <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-amber-200/60 dark:border-amber-800/60">
                  <label htmlFor="select-avail-mapping" className="text-xs font-semibold text-amber-900 dark:text-amber-300">
                    Select Available Mapping:
                  </label>
                  <select
                    id="select-avail-mapping"
                    aria-label="Select Available Mapping"
                    className="text-xs rounded-lg border border-amber-300 dark:border-amber-700 bg-white dark:bg-slate-900 py-1 px-2.5 font-medium"
                    value={customPath}
                    onChange={(e) => handleSelectAlternativeFile(e.target.value)}
                  >
                    <option value="">-- Choose available file --</option>
                    {availableFiles
                      .filter((f) => !f.is_placeholder)
                      .map((f) => (
                        <option key={f.path} value={f.path}>
                          {f.name} ({f.count} rows)
                        </option>
                      ))}
                  </select>
                  {customPath && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setCustomPath('');
                        fetchMappings();
                      }}
                    >
                      Reset to Default
                    </Button>
                  )}
                </div>
              )}
            </div>
          )}

          {mappingMessage && (
            <Alert
              variant={mappingMessage.type === 'success' ? 'success' : 'danger'}
              description={mappingMessage.text}
            />
          )}

          {/* Search Bar & Pagination Controls */}
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="relative flex-1 w-full">
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
              <input
                type="text"
                aria-label="Search across all columns"
                value={mappingFilter}
                onChange={(e) => {
                  setMappingFilter(e.target.value);
                  setPage(1);
                }}
                placeholder="Search across all columns..."
                className="w-full pl-9 pr-4 py-2 border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 rounded-lg text-xs focus:ring-1 focus:ring-teal-500"
              />
            </div>

            <div className="flex items-center gap-2 text-xs text-slate-500 shrink-0">
              <label htmlFor="val-map-page-size">Rows per page:</label>
              <select
                id="val-map-page-size"
                aria-label="Rows per page"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
                className="border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 rounded px-2 py-1 text-xs"
              >
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
                <option value={200}>200</option>
              </select>
              <span className="ml-2 font-medium">
                Page {currentPage} of {totalPages} ({filteredData.length} matches)
              </span>
              <div className="flex items-center gap-1 ml-2">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setPage(1)}
                  className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 cursor-pointer"
                  title="First Page"
                >
                  <ChevronsLeft className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 cursor-pointer"
                  title="Previous Page"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 cursor-pointer"
                  title="Next Page"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() => setPage(totalPages)}
                  className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-40 cursor-pointer"
                  title="Last Page"
                >
                  <ChevronsRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>

          {/* Dynamic Table based on file's own columns */}
          <div className="border border-slate-200 dark:border-slate-800 rounded-lg overflow-x-auto max-h-[550px] shadow-[inset_-10px_0_8px_-8px_rgba(0,0,0,0.1)]">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800/80 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 uppercase text-[10px] tracking-wider sticky top-0 z-10">
                <tr>
                  <th className="p-2.5 w-10 text-center">#</th>
                  {fieldnames.map((col) => (
                    <th key={col} className="p-2.5 min-w-[140px] whitespace-nowrap">
                      {col.replace(/_/g, ' ')}
                    </th>
                  ))}
                  <th className="p-2.5 w-16 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800 font-mono">
                {paginatedData.length === 0 ? (
                  <tr>
                    <td colSpan={fieldnames.length + 2} className="py-8 text-center text-slate-400">
                      No mapping rows found. Click "Add Row" to create mappings.
                    </td>
                  </tr>
                ) : (
                  paginatedData.map((row, pIdx) => {
                    const actualIdx = (currentPage - 1) * pageSize + pIdx;
                    return (
                      <tr key={actualIdx} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/40 transition">
                        <td className="p-2 text-center text-[10px] text-slate-400 font-sans">
                          {actualIdx + 1}
                        </td>
                        {fieldnames.map((col) => (
                          <td key={col} className="p-1.5">
                            <input
                              type="text"
                              aria-label={`Row ${actualIdx + 1} ${col}`}
                              value={row[col] ?? ''}
                              onChange={(e) => {
                                const updated = [...mappingData];
                                updated[actualIdx] = {
                                  ...updated[actualIdx],
                                  [col]: e.target.value,
                                };
                                setMappingData(updated);
                              }}
                              className="w-full border border-transparent hover:border-slate-200 dark:hover:border-slate-700 bg-transparent focus:bg-white dark:focus:bg-slate-800 focus:ring-1 focus:ring-teal-500 rounded p-1 text-xs"
                            />
                          </td>
                        ))}
                        <td className="p-1.5 text-center">
                          <button
                            type="button"
                            onClick={() => {
                              const updated = mappingData.filter((_, i) => i !== actualIdx);
                              setMappingData(updated);
                            }}
                            className="text-slate-400 hover:text-rose-600 transition p-1 cursor-pointer"
                            title="Delete row"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Confirm Save Dialog */}
      <Modal
        open={showConfirmSave}
        onClose={() => setShowConfirmSave(false)}
        title="Confirm Value Mappings Save"
      >
        <div className="space-y-4 text-xs">
          <p className="text-slate-600 dark:text-slate-300">
            You are about to save changes to persistent volume storage. An automatic timestamped backup will be archived before saving.
          </p>

          <div className="p-3 bg-slate-50 dark:bg-slate-800 rounded-lg space-y-2 border border-slate-200 dark:border-slate-700 font-mono">
            <div>
              <span className="text-slate-400 block text-[10px] uppercase font-sans font-bold">Target Storage File:</span>
              <span className="text-teal-700 dark:text-teal-300 font-semibold truncate block">
                /data/mappings/{meta?.filename || 'mapping.csv'}
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px] uppercase font-sans font-bold">Backup Destination:</span>
              <span className="text-slate-600 dark:text-slate-400 text-[11px] truncate block">
                /data/mappings/backups/{meta?.filename?.replace('.csv', '')}.&lt;timestamp&gt;.csv
              </span>
            </div>
            <div>
              <span className="text-slate-400 block text-[10px] uppercase font-sans font-bold">Total Rows to Save:</span>
              <span className="text-slate-800 dark:text-slate-200 font-bold">{mappingData.length.toLocaleString()}</span>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" size="sm" onClick={() => setShowConfirmSave(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Save className="w-3.5 h-3.5" />}
              loading={savingMapping}
              onClick={handleSaveConfirm}
            >
              Confirm & Save
            </Button>
          </div>
        </div>
      </Modal>

      {/* Restore Previous Version Modal */}
      <Modal
        open={showBackupsModal}
        onClose={() => setShowBackupsModal(false)}
        title="Restore Previous Version"
      >
        <div className="space-y-4 text-xs">
          <p className="text-slate-600 dark:text-slate-300">
            Select a previous timestamped backup to restore. Restoring replaces the active file in <code className="font-mono">/data/mappings/</code> after archiving the current version.
          </p>

          {loadingBackups ? (
            <div className="py-8 text-center text-slate-400">Loading backups list...</div>
          ) : backupsList.length === 0 ? (
            <div className="py-8 text-center text-slate-400">
              No backups found for this mapping file yet. Backups are automatically created whenever changes are saved.
            </div>
          ) : (
            <div className="max-h-64 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800 border border-slate-200 dark:border-slate-800 rounded-lg">
              {backupsList.map((b) => (
                <div
                  key={b.filename}
                  className="p-3 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-800/50"
                >
                  <div className="min-w-0 pr-3">
                    <div className="font-mono font-semibold text-slate-800 dark:text-slate-200 truncate">
                      {b.filename}
                    </div>
                    <div className="text-[11px] text-slate-400 mt-0.5">
                      {b.created_at?.slice(0, 19).replace('T', ' ')} • {b.count} rows • {Math.round(b.size / 1024)} KB
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon={<RotateCcw className="w-3 h-3" />}
                    loading={restoringBackup}
                    onClick={() => handleRestore(b.filename)}
                  >
                    Restore
                  </Button>
                </div>
              ))}
            </div>
          )}

          <div className="flex justify-end pt-2">
            <Button variant="ghost" size="sm" onClick={() => setShowBackupsModal(false)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default ValueMappingsPage;
