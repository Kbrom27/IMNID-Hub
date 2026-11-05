import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Layers, Server, ArrowRight, History } from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardDescription, CardContent, OperationsTable } from '../../ui';

const CONCEPTS_MODULES = [
  {
    id: 'openmrs-3x',
    title: 'OpenMRS 3.x Tools Suite',
    subtitle: 'OpenMRS 3.x Form & Concept Tooling',
    desc: 'Schema generator, component builder, and concept dictionary tools for OpenMRS 3.x.',
    icon: Server,
    path: '/concepts/3x',
  },
  {
    id: 'legacy-21',
    title: 'Legacy 2.1 Tools',
    subtitle: 'OpenMRS 2.x & HTML Form Flow',
    desc: 'Legacy form schema extractors, concept validators, and HTML form flow utilities.',
    icon: Layers,
    path: '/concepts/legacy21',
  },
];

const ConceptsIndex = () => {
  const [recentJobs, setRecentJobs] = useState([]);
  const [loadingJobs, setLoadingJobs] = useState(true);

  useEffect(() => {
    fetch('/api/jobs')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        const list = Array.isArray(data) ? data : data?.jobs || [];
        const filtered = list.filter((j) => (j.module || '').includes('concept'));
        setRecentJobs(filtered.slice(0, 5));
      })
      .catch((e) => console.error(e))
      .finally(() => setLoadingJobs(false));
  }, []);

  return (
    <div className="space-y-4 w-full">
      <PageHeader
        title="Concepts & Forms"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Concepts & Forms', to: '/concepts' },
        ]}
      />

      {/* Hub Cards Grid (Compact tiles: ~64px tall, icon + title only) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {CONCEPTS_MODULES.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              to={item.path}
              className="group flex items-center gap-3 p-3.5 h-16 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500 dark:hover:border-teal-500/80 shadow-2xs hover:shadow-xs transition-all duration-150"
            >
              <div className="w-9 h-9 rounded-lg bg-teal-50 dark:bg-teal-950/50 text-teal-600 dark:text-teal-400 flex items-center justify-center shrink-0 border border-teal-200/60 dark:border-teal-800/60 group-hover:scale-105 transition-transform">
                <Icon className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-slate-900 dark:text-slate-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors truncate">
                  {item.title}
                </div>
              </div>
              <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors flex-shrink-0" />
            </Link>
          );
        })}
      </div>

      {/* Recent Module Jobs Table */}
      <OperationsTable
        jobs={recentJobs}
        title="Recent Concepts & Forms Operations"
        limit={8}
        showFilters={false}
      />
    </div>
  );
};

export default ConceptsIndex;
