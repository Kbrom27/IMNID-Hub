import React, { useState, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Zap,
  Database,
  ArrowLeftRight,
  Boxes,
  FileSpreadsheet,
  Settings,
  History,
  Activity,
  ChevronRight,
  ChevronDown,
  ChevronLeft,
  X,
  Server,
  ShieldCheck,
} from 'lucide-react';
import { Tooltip } from '../ui';
import { useConnections } from '../context/ConnectionContext';
import pkg from '../../package.json';

const NAV_GROUPS = [
  {
    title: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/jobs', label: 'Job Monitor', icon: History },
    ],
  },
  {
    title: 'Migration',
    items: [
      { to: '/smartcare', label: 'SmartCare to OpenMRS 3', icon: Zap },
    ],
  },
  {
    title: 'Data Management',
    items: [
      {
        to: '/data-management',
        label: 'Data Management',
        icon: Database,
        badgeCount: 10,
        subItems: [
          { label: 'DHIS2 Direct Sync', to: '/data-management/dhis2-sync' },
          { label: 'DHIS2 Tracker Data Import', to: '/data-management/csv-import' },
          { label: 'Metadata Importer', to: '/data-management/metadata-import' },
          { label: 'Data Transformation', to: '/data-management/cleaning' },
          { label: 'Analytical Data Export', to: '/data-management/analysis-export' },
          { label: 'Data Export for Syncing', to: '/data-management/data-export' },
          { label: 'Data Dictionary Generator', to: '/data-management/data-dictionary' },
          { label: 'DHIS to REDCap Sync', to: '/data-management/redcap-import' },
          { label: 'NCF to NID Sync', to: '/data-management/ncf-nid-sync' },
          { label: 'Mother-Neonate Linker', to: '/data-management/mother-neonate-linker' },
        ],
      },
    ],
  },
  {
    title: 'Interoperability',
    items: [
      {
        to: '/interop',
        label: 'EMR-DHIS2 Pipelines',
        icon: ArrowLeftRight,
        badgeCount: 4,
        subItems: [
          { label: 'OpenMRS 3 Pipeline', to: '/interop/o3' },
          { label: 'Bahmni Pipeline', to: '/interop/bahmni' },
          { label: 'Mediator Control', to: '/interop/mediator' },
          { label: 'Value Mappings', to: '/interop/mappings' },
        ],
      },
    ],
  },
  {
    title: 'Concepts & Forms',
    items: [
      {
        to: '/concepts',
        label: 'Concepts & Forms',
        icon: Boxes,
        badgeCount: 2,
        subItems: [
          { label: 'OpenMRS 3.x Tools', to: '/concepts/3x' },
          { label: 'Legacy 2.1 Tools', to: '/concepts/legacy21' },
        ],
      },
    ],
  },
  {
    title: 'Reporting',
    items: [
      {
        to: '/hmis',
        label: 'HMIS Reporting',
        icon: FileSpreadsheet,
        badgeCount: 5,
        subItems: [
          { label: 'HMIS RMH Report (01.2)', to: '/hmis/rmh-report' },
          { label: 'HMIS NCH Report (04.2)', to: '/hmis/nch-report' },
          { label: 'NICU Register', to: '/hmis/nicu-register' },
          { label: 'Delivery Register', to: '/hmis/delivery-register' },
          { label: 'MOH Aggregate Exporter', to: '/hmis/moh-aggregate' },
        ],
      },
    ],
  },
  {
    title: 'Administration',
    items: [
      { to: '/settings', label: 'Settings & Connections', icon: Settings },
    ],
  },
];

/**
 * Sidebar Component
 * Health-tech operations navigation satisfying:
 * - 40px nav rows, 20px icons
 * - 3px left accent bar for active item + filled tinted background
 * - Collapsible with tooltips on icon hover
 * - High-contrast uppercase section labels
 * - Expandable child count badges
 * - Footer with environment tag and labeled system-health status
 */
const Sidebar = ({ isMobileOpen, setIsMobileOpen, isCollapsed, setIsCollapsed }) => {
  const location = useLocation();
  const { summary } = useConnections();

  // Active expandable group state
  const [openGroup, setOpenGroup] = useState(null);

  // Auto-expand group containing the active route
  useEffect(() => {
    const current = location.pathname;
    if (current.startsWith('/data-management')) {
      setOpenGroup('/data-management');
    } else if (current.startsWith('/interop')) {
      setOpenGroup('/interop');
    } else if (current.startsWith('/concepts')) {
      setOpenGroup('/concepts');
    } else if (current.startsWith('/hmis')) {
      setOpenGroup('/hmis');
    } else {
      setOpenGroup(null);
    }
  }, [location.pathname]);

  const toggleGroup = (key, e) => {
    if (e) {
      e.preventDefault();
      e.stopPropagation();
    }
    setOpenGroup((prev) => (prev === key ? null : key));
  };

  const handleLinkClick = () => {
    if (isMobileOpen && setIsMobileOpen) {
      setIsMobileOpen(false);
    }
  };

  const sidebarContent = (
    <aside
      className={`bg-slate-900 text-slate-300 flex flex-col h-full border-r border-slate-800 select-none transition-all duration-200 ${
        isCollapsed ? 'w-20' : 'w-72'
      }`}
    >
      {/* Brand Header */}
      <div className="h-16 flex items-center justify-between px-4 bg-slate-950/80 border-b border-slate-800/80 flex-shrink-0">
        <NavLink
          to="/"
          onClick={handleLinkClick}
          className="flex items-center gap-3 overflow-hidden focus:outline-none group"
        >
          <div className="w-9 h-9 flex-shrink-0 rounded-xl bg-teal-500/20 border border-teal-500/40 flex items-center justify-center text-teal-400 font-bold shadow-xs group-hover:bg-teal-500/30 transition-colors">
            <Activity className="w-5 h-5 text-teal-400" />
          </div>
          {!isCollapsed && (
            <div className="truncate">
              <h1 className="text-[15px] font-bold text-white tracking-tight flex items-center gap-2">
                IMNID Hub
              </h1>
              <p className="text-[11px] text-teal-400 font-medium tracking-wide">
                Interoperability Platform
              </p>
            </div>
          )}
        </NavLink>

        {/* Collapse toggle (min 32px hit area) */}
        <div className="flex items-center">
          {isMobileOpen ? (
            <button
              onClick={() => setIsMobileOpen(false)}
              className="lg:hidden w-8 h-8 flex items-center justify-center text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 focus:outline-none"
              aria-label="Close sidebar"
            >
              <X className="w-5 h-5" />
            </button>
          ) : (
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="hidden lg:flex w-8 h-8 items-center justify-center text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>

      {/* Nav Items List (Scrollable Middle) */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-5">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="space-y-1">
            {!isCollapsed && (
              <div className="px-3 pb-1 text-[11px] font-bold uppercase tracking-[0.04em] text-slate-400">
                {group.title}
              </div>
            )}
            <div className="space-y-1">
              {group.items.map((item) => {
                const Icon = item.icon;
                const hasSubs = item.subItems && item.subItems.length > 0;
                const isGroupActive = location.pathname === item.to || location.pathname.startsWith(item.to + '/');
                const isOpen = openGroup === item.to;

                const linkElement = (
                  <NavLink
                    to={item.to}
                    end={!hasSubs}
                    onClick={handleLinkClick}
                    className={({ isActive }) => {
                      const active = hasSubs ? isGroupActive : isActive;
                      return `flex items-center gap-3 px-3 h-10 min-h-[40px] rounded-lg text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
                        active
                          ? 'bg-teal-500/15 text-teal-300 font-bold border-l-[3px] border-teal-500 shadow-xs'
                          : 'text-slate-300 hover:text-white hover:bg-slate-800/70 border-l-[3px] border-transparent'
                      } ${isCollapsed ? 'justify-center px-0' : ''}`;
                    }}
                  >
                    <Icon className="w-5 h-5 flex-shrink-0 text-slate-400 group-hover:text-slate-200" />
                    {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
                    
                    {!isCollapsed && hasSubs && (
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        {item.badgeCount && (
                          <span className="text-[10px] font-mono font-semibold px-1.5 py-0.2 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                            {item.badgeCount}
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={(e) => toggleGroup(item.to, e)}
                          aria-expanded={isOpen}
                          className="w-6 h-6 flex items-center justify-center hover:bg-slate-700/60 rounded focus:outline-none text-slate-400 hover:text-slate-200"
                          aria-label={`Toggle ${item.label} submenu`}
                        >
                          {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    )}
                  </NavLink>
                );

                return (
                  <div key={item.to} className="space-y-0.5">
                    {isCollapsed ? (
                      <Tooltip content={item.label} position="right" className="w-full">
                        {linkElement}
                      </Tooltip>
                    ) : (
                      linkElement
                    )}

                    {/* Sub-items for expanded accordion item */}
                    {!isCollapsed && hasSubs && isOpen && (
                      <div className="ml-5 pl-2.5 border-l border-slate-800 space-y-0.5 py-1 animate-in fade-in duration-100">
                        {item.subItems.map((sub) => {
                          const isSubActive =
                            location.pathname === sub.to ||
                            (location.search && sub.to.includes(location.search));

                          return (
                            <NavLink
                              key={sub.to}
                              to={sub.to}
                              onClick={handleLinkClick}
                              className={`block px-3 py-1.5 rounded-md text-xs font-medium transition-colors truncate focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-teal-400 ${
                                isSubActive
                                  ? 'text-teal-300 bg-teal-500/15 font-semibold'
                                  : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800/50'
                              }`}
                            >
                              {sub.label}
                            </NavLink>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer Info: Version, Environment, and Labeled System-Health Indicator */}
      <div className="p-3 border-t border-slate-800 bg-slate-950/70 text-xs text-slate-400 flex flex-col gap-2 flex-shrink-0">
        {!isCollapsed ? (
          <>
            <div className="flex items-center justify-between">
              <span className="font-semibold text-slate-200 text-xs">
                IMNID Hub <span className="font-mono text-slate-400 font-normal">v{pkg.version || '1.0.0'}</span>
              </span>
              <span className="px-1.5 py-0.5 rounded text-[10px] font-mono uppercase font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                Local
              </span>
            </div>

            {/* Labeled System Health Indicator */}
            <div className="flex items-center gap-2 pt-1 border-t border-slate-800/80">
              <span
                className={`w-2 h-2 rounded-full flex-shrink-0 ${
                  summary.overallHealth === 'operational'
                    ? 'bg-emerald-500 shadow-xs'
                    : summary.overallHealth === 'degraded'
                    ? 'bg-amber-400'
                    : 'bg-rose-500'
                }`}
              />
              <span className="text-[11px] font-medium text-slate-300 truncate">
                {summary.overallHealth === 'operational'
                  ? 'All systems operational'
                  : summary.offlineCount > 0
                  ? `${summary.offlineCount} server${summary.offlineCount > 1 ? 's' : ''} offline`
                  : 'System degraded'}
              </span>
            </div>
          </>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                summary.overallHealth === 'operational'
                  ? 'bg-emerald-500'
                  : summary.overallHealth === 'degraded'
                  ? 'bg-amber-400'
                  : 'bg-rose-500'
              }`}
              title={
                summary.overallHealth === 'operational'
                  ? 'All systems operational'
                  : `${summary.offlineCount} servers offline`
              }
            />
          </div>
        )}
      </div>
    </aside>
  );

  return (
    <>
      {/* Desktop static sidebar */}
      <div className="hidden lg:flex flex-shrink-0 h-full">{sidebarContent}</div>

      {/* Mobile Drawer */}
      {isMobileOpen && (
        <div className="lg:hidden fixed inset-0 z-50 flex">
          <div
            className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm transition-opacity"
            onClick={() => setIsMobileOpen(false)}
          />
          <div className="relative z-10 flex-1 flex max-w-xs w-full shadow-2xl">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
};

export default Sidebar;
