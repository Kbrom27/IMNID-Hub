import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeftRight, Database, Table, Activity, ArrowRight, History } from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../ui';

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

      {/* Recent Module Jobs Table */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-teal-600 dark:text-teal-400" />
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
              Recent Interoperability Operations
            </h2>
          </div>
          <Link
            to="/jobs"
            className="text-xs font-semibold text-teal-600 dark:text-teal-400 hover:text-teal-700 flex items-center gap-1"
          >
            All Operations <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>

        <div className="divide-y divide-slate-100 dark:divide-slate-800/80">
          {recentJobs.length === 0 ? (
            <div className="p-6 text-center text-xs text-slate-400">
              {loadingJobs ? 'Loading recent operations...' : 'No recent jobs recorded for this module.'}
            </div>
          ) : (
            recentJobs.map((j) => (
              <div key={j.id} className="p-3 px-5 flex items-center justify-between hover:bg-slate-50/60 dark:hover:bg-slate-800/40 text-xs">
                <div className="flex items-center gap-3">
                  <span className="font-mono font-bold text-slate-700 dark:text-slate-300">{j.id}</span>
                  <div>
                    <span className="font-semibold text-slate-800 dark:text-slate-200">{j.action}</span>
                    <span className="text-slate-400 text-[11px] ml-2">
                      {j.created_at?.slice(0, 19).replace('T', ' ')}
                    </span>
                  </div>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    j.status === 'completed'
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                      : j.status === 'running'
                      ? 'bg-teal-50 text-teal-700 dark:bg-teal-950/40 dark:text-teal-300 border border-teal-200 dark:border-teal-800 animate-pulse'
                      : 'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300 border border-rose-200 dark:border-rose-800'
                  }`}
                >
                  {j.status}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default InteropIndex;
