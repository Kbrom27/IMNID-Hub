import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeftRight, Database, Table, Activity, ArrowRight, History } from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardDescription, CardContent, OperationsTable } from '../../ui';

const INTEROP_MODULES = [
  {
    id: 'o3',
    title: 'OpenMRS 3 Pipeline',
    subtitle: 'OpenMRS 3.x ⟷ DHIS2 Tracker',
    desc: 'Modern 4-part workflow for OpenMRS 3 with REST / FHIR encounters export, automated transformation, and tracker import.',
    icon: ArrowLeftRight,
    path: '/interop/o3',
  },
  {
    id: 'bahmni',
    title: 'Bahmni Pipeline',
    subtitle: 'OpenMRS 2.x ⟷ DHIS2 Tracker',
    desc: 'Standard 4-part workflow: Export encounters, transform clinical observations, validate dry-run, and sync to DHIS2.',
    icon: Database,
    path: '/interop/bahmni',
  },
  {
    id: 'mediator',
    title: 'Mediator & Checkpoints',
    subtitle: 'Microservice Health & Recovery',
    desc: 'Inspect background mediator service health on port 8000, inspect failed records, and resume interrupted batch jobs.',
    icon: Activity,
    path: '/interop/mediator',
  },
  {
    id: 'mappings',
    title: 'Value Mappings Editor',
    subtitle: 'Concept-to-OptionCode Table',
    desc: 'Interactive table editor translating EMR concept answer values to DHIS2 Tracker option codes per system and program.',
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
    <div className="space-y-4 w-full">
      <PageHeader
        title="EMR-DHIS2 Tracker Interoperability"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Pipelines', to: '/interop' },
        ]}
      />

      {/* Hub Cards Grid - compact 64px tiles */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
        {INTEROP_MODULES.map((item) => {
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
