import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Layers, Server, ArrowRight } from 'lucide-react';
import { PageHeader, OperationsTable } from '../../ui';

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
    <div className="space-y-6 w-full">
      <PageHeader
        title="Concepts & Forms"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Concepts & Forms', to: '/concepts' },
        ]}
      />

      {/* Balanced 2-Column Standard Card Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-5">
        {CONCEPTS_MODULES.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              to={item.path}
              className="group block h-full focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 rounded-xl"
            >
              <div className="h-full p-5 sm:p-6 rounded-xl border border-slate-200/90 dark:border-slate-800 bg-white dark:bg-slate-900 hover:border-teal-500/80 dark:hover:border-teal-500/80 shadow-xs hover:shadow-md transition-all duration-150 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="w-10 h-10 rounded-xl bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 flex items-center justify-center shrink-0 border border-teal-200/60 dark:border-teal-800/60 group-hover:scale-105 transition-transform">
                      <Icon className="w-5 h-5" />
                    </div>
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 group-hover:text-teal-600 group-hover:bg-teal-50 dark:group-hover:bg-teal-950/40 group-hover:translate-x-1 transition-all">
                      <ArrowRight className="w-4 h-4" />
                    </div>
                  </div>

                  <h3 className="text-base font-bold text-slate-900 dark:text-slate-100 group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors">
                    {item.title}
                  </h3>
                  <span className="text-xs font-semibold text-teal-600 dark:text-teal-400 uppercase tracking-wide mt-1 block">
                    {item.subtitle}
                  </span>

                  <p className="text-sm text-slate-500 dark:text-slate-400 mt-2 line-clamp-2 leading-relaxed">
                    {item.desc}
                  </p>
                </div>
              </div>
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
