import React from 'react';
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
} from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardContent } from '../../ui';

const FEATURES = [
  {
    id: 'cleaning',
    title: 'Data Transformation',
    subtitle: 'One Row per TEI',
    desc: 'Standardize columns to snake_case and unfold repeated stage events into analytical format.',
    icon: Sparkles,
    path: '/data-management/cleaning',
  },
  {
    id: 'dictionary',
    title: 'Data Dictionary',
    subtitle: 'Schema Workbook Generator',
    desc: 'Extract stages, sections, TEAs, data elements, and option sets into an Excel workbook.',
    icon: BookOpen,
    path: '/data-management/data-dictionary',
  },
  {
    id: 'export',
    title: 'Data Export for Syncing',
    subtitle: 'Raw Tracker Extract',
    desc: 'Export raw tracker entities with enrollments, events, and option sets for offline sync.',
    icon: Download,
    path: '/data-management/data-export',
  },
  {
    id: 'analysis-export',
    title: 'Analytical Data Export',
    subtitle: 'Wide Longitudinal Format',
    desc: 'De-identified patient export unfolding repeatable stages for statistical packages.',
    icon: FileSpreadsheet,
    path: '/data-management/analysis-export',
  },
  {
    id: 'csv-import',
    title: 'DHIS2 Tracker Data Import',
    subtitle: 'Automated Header Mapping',
    desc: 'Import CSV records with automatic encoding detection and attribute matching.',
    icon: Upload,
    path: '/data-management/csv-import',
  },
  {
    id: 'metadata-import',
    title: 'Metadata Importer',
    subtitle: 'JSON Package Importer',
    desc: 'Import programs, tracked entity types, data elements, and option sets.',
    icon: Package,
    path: '/data-management/metadata-import',
  },
  {
    id: 'dhis2-sync',
    title: 'DHIS2 Direct Sync',
    subtitle: 'Offline ⟷ Online Sync',
    desc: 'Synchronize TEIs, enrollments, events, and relationships between DHIS2 instances.',
    icon: RefreshCw,
    path: '/data-management/dhis2-sync',
  },
  {
    id: 'redcap-import',
    title: 'DHIS to REDCap Sync',
    subtitle: 'DHIS2 to REDCap eCRF',
    desc: 'Transform and synchronize newborn inpatient records into REDCap eCRF schemas.',
    icon: Database,
    path: '/data-management/redcap-import',
  },
  {
    id: 'ncf-nid-sync',
    title: 'NCF to NID Sync',
    subtitle: 'Schema Harmonization',
    desc: 'Harmonize and synchronize inpatient records between distinct DHIS2 tracker schemas.',
    icon: RotateCcw,
    path: '/data-management/ncf-nid-sync',
  },
  {
    id: 'mother-neonate-linker',
    title: 'Mother-Neonate Linker',
    subtitle: 'Relationship Linker',
    desc: 'Automatically match and link MID maternal records with NCF newborn records.',
    icon: LinkIcon,
    path: '/data-management/mother-neonate-linker',
  },
];

const DataManagementIndex = () => {
  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="DHIS2 Data Management & Harmonization"
        breadcrumbs={[
          { label: 'Data Management', href: '/data-management' },
        ]}
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {FEATURES.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              to={item.path}
              className="group block h-full focus:outline-none focus:ring-2 focus:ring-teal-500 rounded-xl"
            >
              <Card className="h-full border-slate-200 dark:border-slate-800 hover:border-teal-500/60 dark:hover:border-teal-500/60 hover:shadow-xs transition-all duration-150 flex flex-col justify-between">
                <CardHeader className="p-4 pb-2">
                  <div className="flex items-center justify-between mb-2">
                    <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
                      <Icon className="w-4 h-4" />
                    </div>
                    <ArrowRight className="w-4 h-4 text-slate-300 dark:text-slate-600 group-hover:text-teal-500 group-hover:translate-x-0.5 transition-all" />
                  </div>
                  <CardTitle className="text-sm font-bold group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors">
                    {item.title}
                  </CardTitle>
                  <span className="text-[11px] text-teal-600 dark:text-teal-400 font-medium">
                    {item.subtitle}
                  </span>
                </CardHeader>

                <CardContent className="p-4 pt-1">
                  <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
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
};

export default DataManagementIndex;
