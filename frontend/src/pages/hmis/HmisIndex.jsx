import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { FileSpreadsheet, Baby, ArrowRight, History, Layers, BarChart2, BookOpen } from 'lucide-react';
import { PageHeader, Card, CardHeader, CardTitle, CardContent } from '../../ui';

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
    <div className="space-y-6 w-full">
      <PageHeader
        title="HMIS Reporting & Analytics"
        breadcrumbs={[
          { label: 'Reporting', href: '/hmis' },
        ]}
      />

      {/* Hub Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {HMIS_MODULES.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              to={item.path}
              className="group block h-full focus:outline-none focus:ring-2 focus:ring-teal-500 rounded-xl"
            >
              <Card className="h-full border-slate-200 dark:border-slate-800 hover:border-teal-500/60 dark:hover:border-teal-500/60 hover:shadow-sm transition-all duration-150 flex flex-col justify-between">
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

                <CardContent className="p-4 pt-1 space-y-3">
                  <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                    {item.desc}
                  </p>
                  <div className="flex flex-wrap gap-1 pt-2 border-t border-slate-100 dark:border-slate-800">
                    {item.sources.map((src) => (
                      <span
                        key={src}
                        className="px-2 py-0.5 text-[10px] font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded"
                      >
                        {src}
                      </span>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

      {/* Recent Operations */}
      <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <History className="w-4 h-4 text-teal-600 dark:text-teal-400" />
            <h2 className="text-xs font-bold text-slate-800 dark:text-slate-100 uppercase tracking-wider">
              Recent HMIS Operations
            </h2>
          </div>
          <Link
            to="/jobs"
            className="text-xs font-medium text-teal-600 dark:text-teal-400 hover:underline flex items-center gap-1"
          >
            All Operations <ArrowRight className="w-3 h-3" />
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
                    <span className="font-semibold text-slate-800 dark:text-slate-200">{j.action || j.description}</span>
                    <span className="text-slate-400 text-[11px] ml-2">
                      {j.created_at?.slice(0, 19).replace('T', ' ')}
                    </span>
                  </div>
                </div>
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    j.status === 'completed'
                      ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800'
                      : j.status === 'running'
                      ? 'bg-teal-50 text-teal-700 border border-teal-200 dark:bg-teal-950/40 dark:text-teal-300 dark:border-teal-800 animate-pulse'
                      : 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800'
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

export default HmisIndex;
