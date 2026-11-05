import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  Sparkles,
  BookOpen,
  Download,
  FileSpreadsheet,
  Upload,
  Package,
  RefreshCw,
  Database,
  RotateCcw,
  Link as LinkIcon,
  ArrowRight,
  Search,
  Share2,
  Layers,
  X,
} from 'lucide-react';
import { PageHeader } from '../../ui';

const TOOL_GROUPS = [
  {
    id: 'transform',
    title: 'Transform & Prepare',
    icon: Sparkles,
    tools: [
      {
        id: 'cleaning',
        title: 'Data Transformation',
        icon: Sparkles,
        path: '/data-management/cleaning',
      },
      {
        id: 'dictionary',
        title: 'Data Dictionary Generator',
        icon: BookOpen,
        path: '/data-management/data-dictionary',
      },
    ],
  },
  {
    id: 'export',
    title: 'Export & Analytics',
    icon: Download,
    tools: [
      {
        id: 'analysis-export',
        title: 'Analytical Data Export',
        icon: FileSpreadsheet,
        path: '/data-management/analysis-export',
      },
      {
        id: 'export',
        title: 'Data Export for Syncing',
        icon: Download,
        path: '/data-management/data-export',
      },
    ],
  },
  {
    id: 'import',
    title: 'Import & Ingestion',
    icon: Upload,
    tools: [
      {
        id: 'csv-import',
        title: 'DHIS2 Tracker Data Import',
        icon: Upload,
        path: '/data-management/csv-import',
      },
      {
        id: 'metadata-import',
        title: 'Metadata Importer',
        icon: Package,
        path: '/data-management/metadata-import',
      },
    ],
  },
  {
    id: 'sync',
    title: 'Sync & Linking',
    icon: Share2,
    tools: [
      {
        id: 'dhis2-sync',
        title: 'DHIS2 Direct Sync',
        icon: RefreshCw,
        path: '/data-management/dhis2-sync',
      },
      {
        id: 'redcap-import',
        title: 'DHIS to REDCap Sync',
        icon: Database,
        path: '/data-management/redcap-import',
      },
      {
        id: 'ncf-nid-sync',
        title: 'NCF to NID Sync',
        icon: RotateCcw,
        path: '/data-management/ncf-nid-sync',
      },
      {
        id: 'mother-neonate-linker',
        title: 'Mother-Neonate Linker',
        icon: LinkIcon,
        path: '/data-management/mother-neonate-linker',
      },
    ],
  },
];

const DataManagementIndex = () => {
  const [searchTerm, setSearchTerm] = useState('');

  const filteredGroups = useMemo(() => {
    if (!searchTerm.trim()) return TOOL_GROUPS;
    const term = searchTerm.toLowerCase().trim();
    return TOOL_GROUPS.map((group) => {
      const matchingTools = group.tools.filter((t) =>
        t.title.toLowerCase().includes(term)
      );
      return {
        ...group,
        tools: matchingTools,
      };
    }).filter((group) => group.tools.length > 0);
  }, [searchTerm]);

  return (
    <div className="space-y-6 w-full">
      {/* Standard PageHeader with Breadcrumb, Title, and Search Filter */}
      <PageHeader
        title="Data Management"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Data Management', to: '/data-management' },
        ]}
        actions={
          <div className="relative w-full sm:w-72">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" />
            <input
              type="text"
              placeholder="Search data management tools..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-9 pr-8 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 shadow-xs"
            />
            {searchTerm && (
              <button
                type="button"
                onClick={() => setSearchTerm('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded"
                aria-label="Clear search"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        }
      />

      {/* Tool Groups: Structured by Category in Balanced 2-Column Standard Card Grids */}
      {filteredGroups.length === 0 ? (
        <div className="p-12 text-center bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800">
          <Layers className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2" />
          <p className="text-base font-semibold text-slate-700 dark:text-slate-300">
            No tools match &quot;{searchTerm}&quot;
          </p>
          <p className="text-sm text-slate-400 mt-1">
            Try a different search keyword or clear the search field.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {filteredGroups.map((group) => {
            const GroupIcon = group.icon;
            return (
              <div key={group.id} className="space-y-4">
                {/* Clean Group Section Header */}
                <div className="flex items-center gap-2.5 pb-2 border-b border-slate-200 dark:border-slate-800">
                  <div className="w-7 h-7 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 border border-teal-200/60 dark:border-teal-800/60 flex-shrink-0">
                    <GroupIcon className="w-4 h-4" />
                  </div>
                  <h2 className="text-base font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                    {group.title}
                  </h2>
                </div>

                {/* Balanced 2-Column Standard Card Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-5">
                  {group.tools.map((item) => {
                    const Icon = item.icon;
                    return (
                      <Link
                        key={item.id}
                        to={item.path}
                        className="group block h-full focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 rounded-xl"
                      >
                        <div className="h-full p-5 sm:p-6 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500/80 dark:hover:border-teal-500/80 shadow-xs hover:shadow-md transition-all duration-150 flex items-center justify-between">
                          <div className="flex items-center gap-4 min-w-0">
                            <div className="w-10 h-10 rounded-xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 flex items-center justify-center shrink-0 border border-teal-200/60 dark:border-teal-800/60 group-hover:scale-105 transition-transform">
                              <Icon className="w-5 h-5" />
                            </div>
                            <h3 className="text-base font-bold text-slate-900 dark:text-slate-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors">
                              {item.title}
                            </h3>
                          </div>
                          <div className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 group-hover:text-teal-600 group-hover:bg-teal-50 dark:group-hover:bg-teal-950/40 group-hover:translate-x-1 transition-all shrink-0 ml-3">
                            <ArrowRight className="w-4 h-4" />
                          </div>
                        </div>
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default DataManagementIndex;
