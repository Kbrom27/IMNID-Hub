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
    <div className="space-y-6 w-full">
      <PageHeader
        title="Concepts & Forms Management"
        subtitle="Comprehensive concept dictionary and form engineering utilities for OpenMRS"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Concepts & Forms', to: '/concepts' },
        ]}
      />

      {/* Hub Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {CONCEPTS_MODULES.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              to={item.path}
              className="group block h-full focus:outline-none focus:ring-2 focus:ring-teal-500 rounded-xl"
            >
              <Card className="h-full border-slate-200 dark:border-slate-800 hover:border-teal-500/60 dark:hover:border-teal-500/60 hover:shadow-md transition-all duration-150 flex flex-col justify-between">
                <CardHeader className="pb-2">
                  <div className="w-10 h-10 rounded-xl bg-teal-50 dark:bg-teal-950/40 text-teal-700 dark:text-teal-300 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform mb-2">
                    <Icon className="w-5 h-5" />
                  </div>
                  <CardTitle className="text-base group-hover:text-teal-600 dark:group-hover:text-teal-400 transition-colors">
                    {item.title}
                  </CardTitle>
                  <CardDescription className="text-xs text-teal-600/90 dark:text-teal-400/90 font-medium mt-0.5">
                    {item.subtitle}
                  </CardDescription>
                </CardHeader>
                <CardContent className="pt-0">
                  <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                    {item.desc}
                  </p>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

      {/* Recent Module Jobs Table (Standardized OperationsTable conforming to Section B criteria) */}
      <OperationsTable
        jobs={recentJobs}
        title="Recent Concepts & Forms Operations"
        limit={5}
        showFilters={false}
      />
    </div>
  );
};

export default ConceptsIndex;
