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
    <div className="space-y-6 w-full">
      <PageHeader
        title="EMR-DHIS2 Tracker Interoperability"
        subtitle="Automated clinical pipelines bridging OpenMRS 3, Bahmni 2.x, and DHIS2 Tracker"
        breadcrumbs={[
          { label: 'Overview', to: '/' },
          { label: 'Pipelines', to: '/interop' },
        ]}
      />

      {/* Hub Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {INTEROP_MODULES.map((item) => {
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
