import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  LayoutDashboard,
  Zap,
  Database,
  ArrowLeftRight,
  Boxes,
  FileSpreadsheet,
  Settings,
  History,
  ArrowRight,
  X,
  Server,
} from 'lucide-react';

const SEARCH_ITEMS = [
  { label: 'Dashboard', desc: 'System overview & health status', to: '/', icon: LayoutDashboard, category: 'General' },
  { label: 'Job Monitor', desc: 'Execution history, statuses, and live logs', to: '/jobs', icon: History, category: 'General' },
  { label: 'Settings & Credentials', desc: 'Manage DHIS2, OpenMRS, and REDCap connections', to: '/settings', icon: Settings, category: 'General' },

  { label: 'HMIS RMH Report (01.2)', desc: 'Reproductive & Maternal Health hospital aggregate', to: '/hmis/rmh-report', icon: FileSpreadsheet, category: 'Reporting' },
  { label: 'HMIS NCH Report (04.2)', desc: 'Neonatal & Child Health hospital aggregate', to: '/hmis/nch-report', icon: FileSpreadsheet, category: 'Reporting' },
  { label: 'NICU Register', desc: 'Track newborn inpatient register data', to: '/hmis/nicu-register', icon: FileSpreadsheet, category: 'Reporting' },
  { label: 'Delivery Register', desc: 'Track maternal delivery cases and outcomes', to: '/hmis/delivery-register', icon: FileSpreadsheet, category: 'Reporting' },
  { label: 'MOH Aggregate Exporter', desc: 'Facility aggregate export directly to MOH DHIS2', to: '/hmis/moh-aggregate', icon: FileSpreadsheet, category: 'Reporting' },

  { label: 'DHIS2 Direct Sync', desc: 'Bi-directional sync between offline and online instances', to: '/data-management/dhis2-sync', icon: Database, category: 'Data Management' },
  { label: 'DHIS2 Tracker Data Import', desc: 'Bulk CSV tracker importer with dry-run validation', to: '/data-management/csv-import', icon: Database, category: 'Data Management' },
  { label: 'Metadata Importer', desc: 'Import packages into target DHIS2 instances', to: '/data-management/metadata-import', icon: Database, category: 'Data Management' },
  { label: 'Data Transformation', desc: 'Convert events to One-Row-Per-TEI format', to: '/data-management/cleaning', icon: Database, category: 'Data Management' },
  { label: 'Analytical Data Export', desc: 'Wide format analysis export for research and analytics', to: '/data-management/analysis-export', icon: Database, category: 'Data Management' },
  { label: 'Offline Data Export', desc: 'Sync export with OU filtering', to: '/data-management/data-export', icon: Database, category: 'Data Management' },
  { label: 'Data Dictionary Generator', desc: 'Export full schema and option sets to Excel', to: '/data-management/data-dictionary', icon: Database, category: 'Data Management' },
  { label: 'DHIS2 to REDCap Sync', desc: 'Automated extraction and pipeline to REDCap forms', to: '/data-management/redcap-import', icon: Database, category: 'Data Management' },
  { label: 'NCF to NID Sync', desc: 'Cross-program synchronization pipeline', to: '/data-management/ncf-nid-sync', icon: Database, category: 'Data Management' },
  { label: 'Mother-Neonate Linker', desc: 'Probabilistic and rule-based record linker', to: '/data-management/mother-neonate-linker', icon: Database, category: 'Data Management' },

  { label: 'OpenMRS 3 Pipeline', desc: 'FHIR/REST extraction to DHIS2 Tracker', to: '/interop/o3', icon: ArrowLeftRight, category: 'Interoperability' },
  { label: 'Bahmni Pipeline', desc: 'Legacy Bahmni SQL to DHIS2 sync', to: '/interop/bahmni', icon: ArrowLeftRight, category: 'Interoperability' },
  { label: 'Mediator Control', desc: 'FastAPI sync microservice management', to: '/interop/mediator', icon: Server, category: 'Interoperability' },
  { label: 'Value Mappings', desc: 'EMR to DHIS2 concept and code mappings', to: '/interop/mappings', icon: ArrowLeftRight, category: 'Interoperability' },

  { label: 'SmartCare to OpenMRS 3', desc: 'Demographics and clinical migration pipeline', to: '/smartcare', icon: Zap, category: 'Migration' },
  { label: 'OpenMRS 3.x Schema Tools', desc: 'Forms, schemas, and concept set exporters', to: '/concepts/3x', icon: Boxes, category: 'Concepts' },
  { label: 'Legacy 2.1 Tools', desc: 'Backwards-compatible form schema converters', to: '/concepts/legacy21', icon: Boxes, category: 'Concepts' },
];

export const CommandPalette = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  const filtered = useMemo(() => {
    if (!query.trim()) return SEARCH_ITEMS;
    const q = query.toLowerCase().trim();
    return SEARCH_ITEMS.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.desc.toLowerCase().includes(q) ||
        item.category.toLowerCase().includes(q)
    );
  }, [query]);

  const handleSelect = (item) => {
    if (!item) return;
    navigate(item.to);
    onClose();
  };

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev + 1) % Math.max(1, filtered.length));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((prev) => (prev - 1 + filtered.length) % Math.max(1, filtered.length));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (filtered[selectedIndex]) {
        handleSelect(filtered[selectedIndex]);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  };

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-slate-950/70 backdrop-blur-sm animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-2xl overflow-hidden flex flex-col max-h-[75vh]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Bar */}
        <div className="flex items-center px-4 py-3 border-b border-slate-200 dark:border-slate-800 gap-3">
          <Search className="w-5 h-5 text-slate-400 flex-shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Type a module, pipeline, or action to jump..."
            className="w-full bg-transparent text-sm text-slate-800 dark:text-slate-100 placeholder-slate-400 focus:outline-none"
          />
          {query && (
            <button
              onClick={() => setQuery('')}
              className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded"
              aria-label="Clear query"
            >
              <X className="w-4 h-4" />
            </button>
          )}
          <kbd className="hidden sm:inline-block px-2 py-0.5 text-[10px] font-mono font-semibold text-slate-400 dark:text-slate-500 bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded">
            ESC
          </kbd>
        </div>

        {/* Results List */}
        <div className="flex-1 overflow-y-auto p-2 divide-y divide-slate-100 dark:divide-slate-800/60">
          {filtered.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-400">
              No results found for "{query}". Try searching for HMIS, Sync, Export, or OpenMRS.
            </div>
          ) : (
            filtered.map((item, idx) => {
              const Icon = item.icon;
              const isSelected = idx === selectedIndex;
              return (
                <button
                  key={item.to + item.label}
                  type="button"
                  onClick={() => handleSelect(item)}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={`w-full text-left p-3 rounded-lg flex items-center justify-between gap-3 transition-colors ${
                    isSelected
                      ? 'bg-teal-50 dark:bg-teal-950/40 text-teal-900 dark:text-teal-100 border border-teal-200/80 dark:border-teal-800/60'
                      : 'text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/40 border border-transparent'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        isSelected
                          ? 'bg-teal-600 text-white shadow-sm'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 truncate">
                      <div className="text-sm font-semibold truncate flex items-center gap-2">
                        <span>{item.label}</span>
                        <span className="text-[10px] font-normal uppercase tracking-wider text-slate-400 bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 rounded">
                          {item.category}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 dark:text-slate-500 truncate">
                        {item.desc}
                      </div>
                    </div>
                  </div>
                  <ArrowRight className={`w-4 h-4 flex-shrink-0 ${isSelected ? 'text-teal-600 dark:text-teal-400' : 'text-slate-300 dark:text-slate-600'}`} />
                </button>
              );
            })
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="px-4 py-2 bg-slate-50 dark:bg-slate-950/50 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-[11px] text-slate-400">
          <div className="flex items-center gap-3">
            <span>
              <kbd className="px-1.5 py-0.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[10px] font-mono mr-1">↑</kbd>
              <kbd className="px-1.5 py-0.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[10px] font-mono mr-1">↓</kbd>
              Navigate
            </span>
            <span>
              <kbd className="px-1.5 py-0.5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded text-[10px] font-mono mr-1">↵</kbd>
              Select
            </span>
          </div>
          <span>IMNID Hub Quick Navigation</span>
        </div>
      </div>
    </div>
  );
};

export default CommandPalette;

