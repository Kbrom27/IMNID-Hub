import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { FileSpreadsheet, Baby, ArrowRight, Layers, BarChart2, BookOpen } from 'lucide-react';
import { PageHeader, OperationsTable } from '../../ui';

const HMIS_GROUPS = [
  {
    id: 'reports',
    title: 'Monthly Aggregate Reports',
    icon: BarChart2,
    tools: [
      {
        id: 'rmh-report',
        title: 'HMIS RMH Report (01.2)',
        icon: BarChart2,
        path: '/hmis/rmh-report',
      },
      {
        id: 'nch-report',
        title: 'HMIS NCH Report (04.2)',
        icon: Baby,
        path: '/hmis/nch-report',
      },
      {
        id: 'moh-aggregate',
        title: 'MOH Aggregate Report Exporter',
        icon: Layers,
        path: '/hmis/moh-aggregate',
      },
    ],
  },
  {
    id: 'registers',
    title: 'Inpatient Registers & Tallies',
    icon: BookOpen,
    tools: [
      {
        id: 'nicu-register',
        title: 'NICU Register (26-Column)',
        icon: BookOpen,
        path: '/hmis/nicu-register',
      },
      {
        id: 'delivery-register',
        title: 'Delivery Register (34-Column)',
        icon: FileSpreadsheet,
        path: '/hmis/delivery-register',
      },
    ],
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
          { label: 'Overview', to: '/' },
          { label: 'HMIS Reporting', to: '/hmis' },
        ]}
      />

      {/* HMIS Tool Groups */}
      <div className="space-y-8">
        {HMIS_GROUPS.map((group) => {
          const GroupIcon = group.icon;
          return (
            <div key={group.id} className="space-y-4">
              <div className="flex items-center gap-2.5 pb-2 border-b border-slate-200 dark:border-slate-800">
                <div className="w-7 h-7 rounded-lg bg-teal-50 dark:bg-teal-950/60 flex items-center justify-center text-teal-600 dark:text-teal-400 border border-teal-200/60 dark:border-teal-800/60 flex-shrink-0">
                  <GroupIcon className="w-4 h-4" />
                </div>
                <h2 className="text-base font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  {group.title}
                </h2>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-5">
                {group.tools.map((item) => {
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
            </div>
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
