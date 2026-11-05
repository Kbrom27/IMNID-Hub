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
  X,
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
];

/**
 * Sidebar Component
 * Health-tech operations navigation satisfying Section A criteria:
 * - Starts below the top bar (no duplicate brand block)
 * - Scrolls independently with pinned administration block and pinned footer
 * - Strict accordion behavior: opening one group collapses all others
 * - Auto-opens the group containing the active route
 * - Expanded child items: 13px, readable contrast, 36px row height, indented under thin guide line
 * - Pinned Settings & Connections above footer, always reachable
 * - Retains active left accent bar, count badges, untruncated labels, and tooltips
 */
export const Sidebar = ({ isMobileOpen, setIsMobileOpen, isCollapsed }) => {
  const location = useLocation();
  const { summary } = useConnections();

  // Active open accordion group key (single open group at a time)
  const [openGroup, setOpenGroup] = useState(null);

  // Auto-expand group containing the active route (and collapse others)
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
      // In overview / smartcare / settings, keep other accordions closed
      setOpenGroup(null);
    }
  }, [location.pathname]);

  // Strict accordion toggle: opening one closes all other groups
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
        isCollapsed ? 'w-20' : 'w-[278px]'
      }`}
    >
      {/* Scrollable Navigation Area with edge fades */}
      <div className="relative flex-1 min-h-0 flex flex-col">
        {/* Subtle Top Scroll Edge Fade */}
        <div className="pointer-events-none absolute top-0 left-0 right-0 h-3 bg-gradient-to-b from-slate-900 to-transparent z-10" />

        <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-4">
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="space-y-1">
              {!isCollapsed && (
                <div className="px-3 pb-1 text-xs font-bold uppercase tracking-[0.04em] text-slate-400">
                  {group.title}
                </div>
              )}
              <div className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const hasSubs = item.subItems && item.subItems.length > 0;
                  const isGroupActive =
                    location.pathname === item.to || location.pathname.startsWith(item.to + '/');
                  const isOpen = openGroup === item.to;

                  const linkElement = (
                    <NavLink
                      to={item.to}
                      end={!hasSubs}
                      onClick={handleLinkClick}
                      className={({ isActive }) => {
                        const active = hasSubs ? isGroupActive : isActive;
                        return `relative flex items-center gap-2.5 px-3 h-10 min-h-[40px] rounded-lg text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
                          active
                            ? 'bg-teal-500/15 text-teal-300 font-semibold shadow-xs'
                            : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
                        } ${isCollapsed ? 'justify-center px-0' : ''}`;
                      }}
                    >
                      {({ isActive }) => {
                        const active = hasSubs ? isGroupActive : isActive;
                        return (
                          <>
                            {/* Distinct Left Accent Bar for Active Item */}
                            {active && (
                              <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] bg-teal-400 rounded-r shadow-xs" />
                            )}

                            <Icon className="w-5 h-5 flex-shrink-0 text-slate-400 group-hover:text-slate-200" />
                            {!isCollapsed && (
                              <span className="flex-1 whitespace-nowrap text-left text-sm leading-tight">
                                {item.label}
                              </span>
                            )}

                            {!isCollapsed && hasSubs && (
                              <div className="flex items-center gap-1.5 flex-shrink-0">
                                {item.badgeCount && (
                                  <span className="text-xs font-sans tabular-nums font-semibold px-1.5 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700/80 leading-none">
                                    {item.badgeCount}
                                  </span>
                                )}
                                <span
                                  role="button"
                                  tabIndex={0}
                                  onClick={(e) => toggleGroup(item.to, e)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      toggleGroup(item.to, e);
                                    }
                                  }}
                                  aria-expanded={isOpen}
                                  className="w-5 h-5 flex items-center justify-center hover:bg-slate-700/60 rounded text-slate-400 hover:text-slate-200 cursor-pointer"
                                  aria-label={`Toggle ${item.label} submenu`}
                                >
                                  {isOpen ? (
                                    <ChevronDown className="w-3.5 h-3.5" />
                                  ) : (
                                    <ChevronRight className="w-3.5 h-3.5" />
                                  )}
                                </span>
                              </div>
                            )}
                          </>
                        );
                      }}
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

                      {/* Sub-items for accordion group: 13px, 36px row height, indented under thin guide line */}
                      {!isCollapsed && hasSubs && isOpen && (
                        <div className="ml-5 pl-2.5 border-l border-slate-700/60 space-y-0.5 py-1 animate-in fade-in duration-100">
                          {item.subItems.map((sub) => {
                            const isSubActive =
                              location.pathname === sub.to ||
                              (location.search && sub.to.includes(location.search));

                            return (
                              <NavLink
                                key={sub.to}
                                to={sub.to}
                                onClick={handleLinkClick}
                                className={`flex items-center px-3 h-9 min-h-[36px] rounded-md text-[13px] font-medium transition-colors truncate focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-teal-400 ${
                                  isSubActive
                                    ? 'text-teal-300 bg-teal-500/15 font-semibold'
                                    : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
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

        {/* Subtle Bottom Scroll Edge Fade */}
        <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-3 bg-gradient-to-t from-slate-900 to-transparent z-10" />
      </div>

      {/* Pinned Administration Block: Always reachable above footer */}
      <div className="p-3 border-t border-slate-800 bg-slate-950/40 flex-shrink-0">
        {!isCollapsed && (
          <div className="px-3 pb-1 text-xs font-bold uppercase tracking-[0.04em] text-slate-400">
            Administration
          </div>
        )}
        <NavLink
          to="/settings"
          onClick={handleLinkClick}
          className={({ isActive }) => `relative flex items-center gap-2.5 px-3 h-10 min-h-[40px] rounded-lg text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 ${
            isActive
              ? 'bg-teal-500/15 text-teal-300 font-semibold shadow-xs'
              : 'text-slate-300 hover:text-white hover:bg-slate-800/70'
          } ${isCollapsed ? 'justify-center px-0' : ''}`}
        >
          {({ isActive }) => (
            <>
              {isActive && (
                <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] bg-teal-400 rounded-r shadow-xs" />
              )}
              <Settings className="w-5 h-5 flex-shrink-0 text-slate-400 group-hover:text-slate-200" />
              {!isCollapsed && (
                <span className="flex-1 whitespace-nowrap text-left text-sm leading-tight">
                  Settings & Connections
                </span>
              )}
            </>
          )}
        </NavLink>
      </div>

      {/* Pinned Footer: Version and LOCAL Environment Badge (Status kept solely in PageFooter per Section 5) */}
      <div className="p-3 border-t border-slate-800 bg-slate-950 text-xs text-slate-400 flex flex-col gap-2 flex-shrink-0">
        {!isCollapsed ? (
          <div className="flex items-center justify-between">
            <span className="font-semibold text-slate-300 text-xs">
              IMNID Hub <span className="font-sans tabular-nums text-slate-400 font-normal">v{pkg.version || '1.0.0'}</span>
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-teal-500/15 border border-teal-500/30 text-teal-300">
              LOCAL
            </span>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-1 text-[10px] font-bold text-teal-400">
            LOCAL
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
