import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { FileSpreadsheet, Baby, ArrowRight, History, Layers, BarChart2, BookOpen } from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardContent, OperationsTable } from '../../ui';

const HMIS_MODULES = [
  {
    id: 'rmh-report',
    title: 'HMIS RMH Report Generator',
    subtitle: 'MoH 01.2 Monthly Aggregate Report',
    desc: 'Compute maternal health indicators from DHIS2 Tracker or OpenMRS 3.',
    icon: BarChart2,
    path: '/hmis/rmh-report',
    sources: ['DHIS2 Tracker', 'OpenMRS 3'],
  },
  {
    id: 'nch-report',
    title: 'HMIS NCH Report Generator',
    subtitle: 'MoH 04.2 Monthly Aggregate Report',
    desc: 'Compute neonatal indicators and admission tallies from DHIS2 Tracker or OpenMRS 3.',
    icon: Baby,
    path: '/hmis/nch-report',
    sources: ['DHIS2 Tracker', 'OpenMRS 3'],
  },
  {
    id: 'nicu-register',
    title: 'NICU Register Generator',
    subtitle: 'MoH 26-Column Register',
    desc: 'Generate 26-column admission registers with monthly tally sheets.',
    icon: BookOpen,
    path: '/hmis/nicu-register',
    sources: ['DHIS2 Tracker', 'OpenMRS 3', 'CSV Extract'],
  },
  {
    id: 'delivery-register',
    title: 'Delivery Register Generator',
    subtitle: 'MoH 34-Column Register',
    desc: 'Generate 34-column delivery registers with multi-facility support.',
    icon: FileSpreadsheet,
    path: '/hmis/delivery-register',
    sources: ['DHIS2 Tracker', 'OpenMRS 3', 'CSV Extract'],
  },
  {
    id: 'moh-aggregate',
    title: 'MOH Aggregate Report Exporter',
    subtitle: 'Facility Analytics Exporter (MERGED)',
    desc: 'Query MOH DHIS2 analytics across historical periods and export multi-sheet Excel & CSV.',
    icon: Layers,
    path: '/hmis/moh-aggregate',
    sources: ['DHIS2 Analytics', 'Facility Mapping'],
  },
];

const HmisIndex = () => {
  const [recentJobs, setRecentJobs] = useState([]);
  const [loadingJobs, setLoadingJobs] = useState(true);

  useEffect(() => {
    fetch('/api/jobs')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const list = Array.isArray(data) ? data : data?.jobs || [];
        const filtered = list.filter((j) => (j.module || '').includes('hmis') || (j.action || '').includes('hmis'));
        setRecentJobs(filtered.slice(0, 5));
      })
      .catch((e) => console.error(e))
      .finally(() => setLoadingJobs(false));
  }, []);

  return (
    <div className="space-y-4 w-full">
      <PageHeader
        title="HMIS Reporting & Analytics"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'HMIS Reporting', to: '/hmis' },
        ]}
      />

      {/* Hub Cards Grid - compact 64px tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
        {HMIS_MODULES.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              to={item.path}
              className="group flex items-center gap-3 p-3 h-16 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 shadow-2xs hover:shadow-xs transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-teal-500"
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

      {/* Recent Operations */}
      <OperationsTable
        jobs={recentJobs}
        title="Recent HMIS Reporting Operations"
        limit={5}
        showFilters={false}
      />
    </div>
  );
};

export default HmisIndex;
