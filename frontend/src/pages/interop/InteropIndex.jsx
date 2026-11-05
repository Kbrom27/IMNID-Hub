import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeftRight, Database, Table, Activity, ArrowRight } from 'lucide-react';
import { PageHeader, OperationsTable } from '../../ui';

const INTEROP_MODULES = [
  {
    id: 'o3',
    title: 'OpenMRS 3 Pipeline',
    icon: ArrowLeftRight,
    path: '/interop/o3',
  },
  {
    id: 'bahmni',
    title: 'Bahmni Pipeline',
    icon: Database,
    path: '/interop/bahmni',
  },
  {
    id: 'mediator',
    title: 'Mediator & Checkpoints',
    icon: Activity,
    path: '/interop/mediator',
  },
  {
    id: 'mappings',
    title: 'Value Mappings Editor',
    icon: Table,
    path: '/interop/mappings',
  },
];

const InteropIndex = () => {
  const [recentJobs, setRecentJobs] = useState([]);
  const [loadingJobs, setLoadingJobs] = useState(true);

  useEffect(() => {
    fetch('/api/jobs')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const list = Array.isArray(data) ? data : data?.jobs || [];
        const filtered = list.filter((j) => (j.module || '').includes('interop'));
        setRecentJobs(filtered.slice(0, 5));
      })
      .catch((e) => console.error(e))
      .finally(() => setLoadingJobs(false));
  }, []);

  return (
    <div className="space-y-6 w-full">
      <PageHeader
        title="EMR-DHIS2 Tracker Interoperability"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Pipelines', to: '/interop' },
        ]}
      />

      {/* Hub Cards Grid - Balanced 2-Column Standard Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-5">
        {INTEROP_MODULES.map((item) => {
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

      {/* Recent Module Jobs Table (Standardized OperationsTable) */}
      <OperationsTable
        jobs={recentJobs}
        title="Recent Interoperability Operations"
        limit={5}
        showFilters={false}
      />
    </div>
  );
};

export default InteropIndex;
