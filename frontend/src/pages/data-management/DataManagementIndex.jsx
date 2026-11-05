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
  Layers,
  Share2,
} from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardContent } from '../../ui';

const TOOL_GROUPS = [
  {
    id: 'transform',
    title: 'Transform & Prepare',
    desc: 'Schema transformation, standardization, and workbook dictionary utilities',
    icon: Sparkles,
    tools: [
      {
        id: 'cleaning',
        title: 'Data Transformation',
        subtitle: 'One Row per TEI',
        desc: 'Standardize columns to snake_case and unfold repeated stage events into analytical longitudinal format.',
        icon: Sparkles,
        path: '/data-management/cleaning',
      },
      {
        id: 'dictionary',
        title: 'Data Dictionary Generator',
        subtitle: 'Schema Workbook Generator',
        desc: 'Extract stages, sections, TEAs, data elements, and option sets into a comprehensive Excel schema workbook.',
        icon: BookOpen,
        path: '/data-management/data-dictionary',
      },
    ],
  },
  {
    id: 'export',
    title: 'Export & Analytics',
    desc: 'De-identified longitudinal exports and offline synchronization extracts',
    icon: Download,
    tools: [
      {
        id: 'analysis-export',
        title: 'Analytical Data Export',
        subtitle: 'Wide Longitudinal Format',
        desc: 'De-identified patient export unfolding repeatable stages for statistical and ML analysis pipelines.',
        icon: FileSpreadsheet,
        path: '/data-management/analysis-export',
      },
      {
        id: 'export',
        title: 'Data Export for Syncing',
        subtitle: 'Raw Tracker Extract',
        desc: 'Export raw tracker entities with enrollments, events, and option sets for offline instance synchronization.',
        icon: Download,
        path: '/data-management/data-export',
      },
    ],
  },
  {
    id: 'import',
    title: 'Import & Ingestion',
    desc: 'Automated CSV tracker ingester and full metadata JSON package loader',
    icon: Upload,
    tools: [
      {
        id: 'csv-import',
        title: 'DHIS2 Tracker Data Import',
        subtitle: 'Automated Header Mapping',
        desc: 'Import CSV records with automatic encoding detection, validation, and attribute matching.',
        icon: Upload,
        path: '/data-management/csv-import',
      },
      {
        id: 'metadata-import',
        title: 'Metadata Importer',
        subtitle: 'JSON Package Importer',
        desc: 'Import programs, tracked entity types, data elements, and option sets from standardized bundles.',
        icon: Package,
        path: '/data-management/metadata-import',
      },
    ],
  },
  {
    id: 'sync',
    title: 'Sync & Linking',
    desc: 'Cross-instance synchronization, external REDCap pipeline, and record linkage',
    icon: Share2,
    tools: [
      {
        id: 'dhis2-sync',
        title: 'DHIS2 Direct Sync',
        subtitle: 'Offline ⟷ Online Sync',
        desc: 'Synchronize TEIs, enrollments, events, and relationships between DHIS2 offline and central instances.',
        icon: RefreshCw,
        path: '/data-management/dhis2-sync',
      },
      {
        id: 'redcap-import',
        title: 'DHIS to REDCap Sync',
        subtitle: 'DHIS2 to REDCap eCRF',
        desc: 'Transform and synchronize newborn inpatient records into REDCap eCRF schemas with audit trails.',
        icon: Database,
        path: '/data-management/redcap-import',
      },
      {
        id: 'ncf-nid-sync',
        title: 'NCF to NID Sync',
        subtitle: 'Schema Harmonization',
        desc: 'Harmonize and synchronize inpatient records between distinct DHIS2 tracker schemas seamlessly.',
        icon: RotateCcw,
        path: '/data-management/ncf-nid-sync',
      },
      {
        id: 'mother-neonate-linker',
        title: 'Mother-Neonate Linker',
        subtitle: 'Relationship Linker',
        desc: 'Automatically match and link MID maternal records with NCF newborn records using clinical identifiers.',
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
      const matchingTools = group.tools.filter(
        (t) =>
          t.title.toLowerCase().includes(term) ||
          t.subtitle.toLowerCase().includes(term) ||
          t.desc.toLowerCase().includes(term)
      );
      return {
        ...group,
        tools: matchingTools,
      };
    }).filter((group) => group.tools.length > 0);
  }, [searchTerm]);

  return (
    <div className="space-y-6 w-full">
      {/* Shared PageHeader with Breadcrumb, Title, Subtitle, and Search Box */}
      <PageHeader
        title="Data Management"
        subtitle="Manage, transform, export, and harmonize healthcare data across DHIS2 and external systems"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Data Management', to: '/data-management' },
        ]}
        actions={
          <div className="relative w-full sm:w-72">
            <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search data management tools..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 shadow-xs"
            />
          </div>
        }
      />

      {/* Tool Groups Grid */}
      {filteredGroups.length === 0 ? (
        <div className="p-12 text-center bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800">
          <Layers className="w-8 h-8 text-slate-300 dark:text-slate-600 mx-auto mb-2" />
          <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">
            No tools match &quot;{searchTerm}&quot;
          </p>
          <p className="text-xs text-slate-400 mt-1">
            Try a different search keyword or clear the search field.
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {filteredGroups.map((group) => {
            const GroupIcon = group.icon;
            return (
              <div key={group.id} className="space-y-3">
                {/* Group Heading */}
                <div className="flex items-center gap-2 pb-1 border-b border-slate-200/80 dark:border-slate-800">
                  <div className="w-7 h-7 rounded-lg bg-teal-50 dark:bg-teal-950/50 flex items-center justify-center text-teal-600 dark:text-teal-400 border border-teal-200/80 dark:border-teal-800/60 flex-shrink-0">
                    <GroupIcon className="w-3.5 h-3.5" />
                  </div>
                  <div>
                    <h2 className="text-sm font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                      {group.title}
                    </h2>
                    <p className="text-xs text-slate-500 dark:text-slate-400">
                      {group.desc}
                    </p>
                  </div>
                </div>

                {/* Balanced Grid: 2 columns so no orphaned card */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {group.tools.map((item) => {
                    const Icon = item.icon;
                    return (
                      <Link
                        key={item.id}
                        to={item.path}
                        className="group block h-full focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 rounded-xl"
                      >
                        <Card className="h-full border-slate-200/90 dark:border-slate-800 hover:border-teal-500/60 dark:hover:border-teal-500/60 shadow-xs hover:shadow-sm transition-all duration-150 flex flex-col justify-between bg-white dark:bg-slate-900">
                          <CardHeader className="p-4 pb-2">
                            <div className="flex items-center justify-between mb-2">
                              <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/50 text-teal-600 dark:text-teal-400 flex items-center justify-center shrink-0 border border-teal-200/60 dark:border-teal-800/60 group-hover:scale-105 transition-transform">
                                <Icon className="w-4 h-4" />
                              </div>
                              <div className="w-7 h-7 rounded-lg flex items-center justify-center group-hover:bg-teal-50 dark:group-hover:bg-teal-950/40 transition-colors">
                                <ArrowRight className="w-4 h-4 text-slate-400 dark:text-slate-500 group-hover:text-teal-600 dark:group-hover:text-teal-400 group-hover:translate-x-0.5 transition-all" />
                              </div>
                            </div>
                            <CardTitle className="text-sm font-bold text-slate-900 dark:text-slate-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors">
                              {item.title}
                            </CardTitle>
                            <span className="text-xs text-teal-600 dark:text-teal-400 font-semibold mt-0.5">
                              {item.subtitle}
                            </span>
                          </CardHeader>

                          <CardContent className="p-4 pt-1">
                            <p className="text-xs text-slate-500 dark:text-slate-400 min-h-[36px] line-clamp-2 leading-relaxed">
                              {item.desc}
                            </p>
                          </CardContent>
                        </Card>
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
