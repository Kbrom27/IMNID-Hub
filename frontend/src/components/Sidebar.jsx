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
} from 'lucide-react';
import { Tooltip } from '../ui';
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
        subItems: [
          { label: 'DHIS2 Direct Sync', to: '/data-management/dhis2-sync' },
          { label: 'DHIS2 Tracker Data Import', to: '/data-management/csv-import' },
          { label: 'Metadata Importer', to: '/data-management/metadata-import' },
          { label: 'Data Transformation', to: '/data-management/cleaning' },
          { label: 'Analysis Export', to: '/data-management/analysis-export' },
          { label: 'Data export for syncing', to: '/data-management/data-export' },
          { label: 'Data Dictionary', to: '/data-management/data-dictionary' },
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
        subItems: [
          { label: 'HMIS RMH Report', to: '/hmis/rmh-report' },
          { label: 'HMIS NCH Report', to: '/hmis/nch-report' },
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
 * Modern Responsive Sidebar
 * Implements single-open accordion behavior, fixed header/footer with scrolling middle,
 * reading version from package.json, and keyboard accessible submenus.
 */
const Sidebar = ({ isMobileOpen, setIsMobileOpen, isCollapsed, setIsCollapsed }) => {
  const location = useLocation();

  // Single open group for accordion behavior (Data Management collapsed by default)
  const [openGroup, setOpenGroup] = useState(null);

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
      className={`bg-slate-900 text-slate-300 flex flex-col h-full border-r border-slate-800 select-none transition-all duration-300 ${
        isCollapsed ? 'w-20' : 'w-72'
      }`}
    >
      {/* Brand Header (Fixed) */}
      <div className="h-16 flex items-center justify-between px-4 bg-slate-950/80 border-b border-slate-800/80 flex-shrink-0">
        <NavLink
          to="/"
          onClick={handleLinkClick}
          className="flex items-center gap-3 overflow-hidden focus:outline-none"
        >
          <div className="w-10 h-10 flex-shrink-0 rounded-xl bg-teal-500/20 border border-teal-500/40 flex items-center justify-center text-teal-400 font-bold shadow-sm">
            <Activity className="w-5 h-5 text-teal-400" />
          </div>
          {!isCollapsed && (
            <div className="truncate">
              <h1 className="text-base font-bold text-white tracking-wide">IMNID Hub</h1>
              <p className="text-xs text-teal-400 font-semibold">Interoperability Platform</p>
            </div>
          )}
        </NavLink>

        {/* Mobile close button or desktop collapse button */}
        <div className="flex items-center">
          {isMobileOpen ? (
            <button
              onClick={() => setIsMobileOpen(false)}
              className="lg:hidden p-1.5 text-slate-400 hover:text-white rounded-lg focus:outline-none"
              aria-label="Close sidebar"
            >
              <X className="w-5 h-5" />
            </button>
          ) : (
            <button
              onClick={() => setIsCollapsed(!isCollapsed)}
              className="hidden lg:flex p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition focus:outline-none"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>
          )}
        </div>
      </div>

      {/* Nav Items List (Scrollable Middle Section) */}
      <nav className="flex-1 overflow-y-auto px-3.5 py-4 space-y-4">
        {NAV_GROUPS.map((group) => (
          <div key={group.title} className="space-y-1">
            {!isCollapsed && (
              <div className="px-3 pb-1.5 text-xs font-bold uppercase tracking-wider text-slate-400">
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
                    className={({ isActive }) =>
                      `flex items-center gap-3.5 px-3.5 py-2.5 rounded-xl text-sm font-semibold transition-all ${
                        (hasSubs ? isGroupActive : isActive)
                          ? 'bg-teal-500/15 text-teal-300 font-bold border border-teal-500/20 shadow-xs'
                          : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
                      } ${isCollapsed ? 'justify-center px-0' : ''}`
                    }
                  >
                    <Icon className="w-5 h-5 flex-shrink-0 text-teal-400" />
                    {!isCollapsed && <span className="flex-1 truncate">{item.label}</span>}
                    {!isCollapsed && hasSubs && (
                      <button
                        type="button"
                        onClick={(e) => toggleGroup(item.to, e)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            toggleGroup(item.to, e);
                          }
                        }}
                        aria-expanded={isOpen}
                        className="p-1 hover:bg-slate-700/50 rounded-lg focus:outline-none focus:ring-1 focus:ring-teal-400"
                        aria-label={`Toggle ${item.label} submenu`}
                      >
                        {isOpen ? <ChevronDown className="w-4 h-4 text-slate-300" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
                      </button>
                    )}
                  </NavLink>
                );

                return (
                  <div key={item.to} className="space-y-1">
                    {isCollapsed ? (
                      <Tooltip content={item.label} position="right" className="w-full">
                        {linkElement}
                      </Tooltip>
                    ) : (
                      linkElement
                    )}

                    {/* Sub-items for expanded accordion item */}
                    {!isCollapsed && hasSubs && isOpen && (
                      <div className="ml-6 pl-3 border-l-2 border-slate-800 space-y-1 py-1">
                        {item.subItems.map((sub) => {
                          const isSubActive =
                            location.pathname === sub.to ||
                            (location.search && sub.to.includes(location.search));

                          return (
                            <NavLink
                              key={sub.to}
                              to={sub.to}
                              onClick={handleLinkClick}
                              className={`block px-3 py-2 rounded-lg text-xs font-semibold transition-all truncate ${
                                isSubActive
                                  ? 'text-teal-300 bg-teal-500/15 font-bold border border-teal-500/20'
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

      {/* Footer Info (Fixed) */}
      <div className="p-3.5 border-t border-slate-800/80 bg-slate-950/50 text-xs text-slate-400 font-medium flex items-center justify-between flex-shrink-0">
        {!isCollapsed && (
          <div className="truncate">
            <span className="font-bold text-slate-300">IMNID Hub</span> v{pkg.version || '1.0.0'}
          </div>
        )}
        <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 inline-block shadow-sm" title="System Online" />
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
