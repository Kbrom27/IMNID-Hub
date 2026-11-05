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
  return (
    <div className="space-y-4 w-full">
      <PageHeader
        title="Data Management"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Data Management', to: '/data-management' },
        ]}
      />

      {/* Compact Tool Groups Grid (all 10 tools fit without page scroll per Section B6) */}
      <div className="space-y-4">
        {TOOL_GROUPS.map((group) => {
          return (
            <div key={group.id} className="space-y-2">
              <div className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 pb-1 border-b border-slate-200/80 dark:border-slate-800">
                {group.title}
              </div>

              {/* Compact tiles: ~64px tall, icon + title only */}
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5">
                {group.tools.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Link
                      key={item.id}
                      to={item.path}
                      className="group flex items-center gap-3 p-3 h-16 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 shadow-2xs hover:shadow-xs transition-all duration-150"
                    >
                      <div className="w-8 h-8 rounded-lg bg-teal-50 dark:bg-teal-950/50 text-teal-600 dark:text-teal-400 flex items-center justify-center shrink-0 border border-teal-200/60 dark:border-teal-800/60 group-hover:scale-105 transition-transform">
                        <Icon className="w-4 h-4" />
                      </div>
                      <span className="text-xs sm:text-[13px] font-semibold text-slate-900 dark:text-slate-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors line-clamp-2 leading-snug">
                        {item.title}
                      </span>
                    </Link>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DataManagementIndex;
