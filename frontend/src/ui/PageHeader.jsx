import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';

const ROUTE_LABELS = {
  '': 'Dashboard',
  'smartcare': 'SmartCare to OpenMRS 3',
  'data-management': 'Data Management',
  'dhis2-sync': 'DHIS2 Direct Sync',
  'csv-import': 'DHIS2 Tracker Data Import',
  'metadata-import': 'Metadata Importer',
  'cleaning': 'Data Transformation',
  'analysis-export': 'Analytical Data Export',
  'data-export': 'Data Export for Syncing',
  'data-dictionary': 'Data Dictionary Generator',
  'redcap-import': 'DHIS to REDCap Sync',
  'ncf-nid-sync': 'NCF to NID Sync',
  'mother-neonate-linker': 'Mother-Neonate Linker',
  'interop': 'EMR-DHIS2 Pipelines',
  'o3': 'OpenMRS 3 Pipeline',
  'bahmni': 'Bahmni Pipeline',
  'mediator': 'Mediator Control',
  'mappings': 'Value Mappings',
  'concepts': 'Concepts & Forms',
  '3x': 'OpenMRS 3.x Tools',
  'legacy21': 'Legacy 2.1 Tools',
  'hmis': 'HMIS Reporting',
  'rmh-report': 'HMIS RMH Report (01.2)',
  'nch-report': 'HMIS NCH Report (04.2)',
  'nicu-register': 'NICU Register',
  'delivery-register': 'Delivery Register',
  'moh-aggregate': 'MOH Aggregate Exporter',
  'jobs': 'Job Monitor',
  'settings': 'Settings & Connections',
};

/**
 * PageHeader Component
 * Unified shared header for all IMNID Hub views conforming to Section C:
 * - Breadcrumb navigation displayed cleanly above the title
 * - Prominent 24-28px title
 * - Contextual 14px subtitle
 * - Right-aligned actions slot
 */
export const PageHeader = ({
  title,
  subtitle,
  description, // alias for subtitle
  breadcrumbs,
  actions,
  icon,
  className = '',
}) => {
  const location = useLocation();

  // If breadcrumbs prop is not provided, generate from URL path
  const autoCrumbs = React.useMemo(() => {
    if (breadcrumbs) return breadcrumbs;
    const pathSegments = location.pathname.split('/').filter(Boolean);
    if (pathSegments.length === 0) {
      return [{ label: 'Overview', to: '/' }];
    }
    const list = [{ label: 'Overview', to: '/' }];
    let accPath = '';
    pathSegments.forEach((seg) => {
      accPath += `/${seg}`;
      list.push({
        label: ROUTE_LABELS[seg] || seg,
        to: accPath,
      });
    });
    return list;
  }, [breadcrumbs, location.pathname]);

  const sub = subtitle || description;

  return (
    <div className={`pb-4 border-b border-slate-200 dark:border-slate-800 ${className}`}>
      {/* 1. Breadcrumbs rendered above the page title */}
      {autoCrumbs && autoCrumbs.length > 0 && (
        <nav aria-label="Page Breadcrumbs" className="mb-2 flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 font-medium">
          {autoCrumbs.map((bc, idx) => {
            const isLast = idx === autoCrumbs.length - 1;
            return (
              <React.Fragment key={(bc.to || bc.href || bc.label) + idx}>
                {idx > 0 && (
                  <ChevronRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-600 flex-shrink-0" />
                )}
                {isLast ? (
                  <span className="font-semibold text-slate-700 dark:text-slate-200 truncate">
                    {bc.label}
                  </span>
                ) : (
                  <Link
                    to={bc.to || bc.href || '/'}
                    className="hover:text-slate-900 dark:hover:text-slate-100 transition-colors truncate"
                  >
                    {bc.label}
                  </Link>
                )}
              </React.Fragment>
            );
          })}
        </nav>
      )}

      {/* 2. Title & Subtitle + Right Actions */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          {icon && (
            <div className="p-2 rounded-lg bg-teal-50 dark:bg-teal-950/60 text-teal-600 dark:text-teal-400 border border-teal-200 dark:border-teal-900 flex-shrink-0 mt-0.5">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <h1 className="text-2xl sm:text-[28px] font-bold text-slate-900 dark:text-slate-100 tracking-tight">
              {title}
            </h1>
            {sub && (
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400 mt-1">
                {sub}
              </p>
            )}
          </div>
        </div>

        {actions && (
          <div className="flex items-center gap-2.5 flex-wrap sm:flex-nowrap flex-shrink-0">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
};

export default PageHeader;
