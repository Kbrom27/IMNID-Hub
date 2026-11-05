import React, { useState, useEffect, useRef } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { useConnections } from '../context/ConnectionContext';
import {
  Menu,
  RefreshCw,
  LogOut,
  CheckCircle2,
  XCircle,
  AlertCircle,
  MinusCircle,
  KeyRound,
  Sun,
  Moon,
  ChevronRight,
  ChevronDown,
  Server,
  Activity,
  Shield,
  User as UserIcon,
  Search,
  Bell,
  Clock,
  ArrowRight,
  ExternalLink,
} from 'lucide-react';
import { Modal, Button, TextInput, Badge, Alert, Tooltip } from '../ui';
import CommandPalette from './CommandPalette';

const ROUTE_LABELS = {
  '': 'Dashboard',
  smartcare: 'SmartCare to OpenMRS 3',
  'data-management': 'Data Management',
  'dhis2-sync': 'DHIS2 Direct Sync',
  'csv-import': 'DHIS2 Tracker Data Import',
  'metadata-import': 'Metadata Importer',
  cleaning: 'Data Transformation',
  'analysis-export': 'Analytical Export',
  'data-export': 'Offline Data Export',
  'data-dictionary': 'Data Dictionary',
  'redcap-import': 'DHIS to REDCap Sync',
  'ncf-nid-sync': 'NCF to NID Sync',
  'mother-neonate-linker': 'Mother-Neonate Linker',
  interop: 'Interoperability',
  bahmni: 'Bahmni Pipeline',
  o3: 'OpenMRS 3 Pipeline',
  mappings: 'Value Mappings',
  mediator: 'Mediator Control',
  concepts: 'Concepts & Forms',
  '3x': 'OpenMRS 3.x Tools',
  legacy21: 'Legacy 2.1 Tools',
  hmis: 'HMIS Reporting',
  'rmh-report': 'HMIS RMH Report (01.2)',
  'nch-report': 'HMIS NCH Report (04.2)',
  'nicu-register': 'NICU Register',
  'delivery-register': 'Delivery Register',
  'moh-aggregate': 'MOH Aggregate Exporter',
  jobs: 'Job Monitor',
  settings: 'Settings & Credentials',
};

/**
 * AppHeader (Topbar)
 * Professional health-tech operations header conforming to all 10 UX criteria:
 * - 56-64px height with clean bordered bottom edge
 * - Aligned breadcrumbs matching main content left grid boundary
 * - Controls in exact sequence: Search (Ctrl+K) -> Connection Pill -> Notifications -> Theme Toggle -> User Menu
 * - Single source of truth for connection counts (shared with Dashboard)
 * - "Last refreshed: Xs ago" indicator
 */
const Topbar = ({ onMenuClick }) => {
  const { user, logout, changePassword } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { summary, loading: connLoading, secondsAgo, fetchStatus, testSingle, testAll, testingAll } = useConnections();
  const location = useLocation();

  const [showConnPopover, setShowConnPopover] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showBellPopover, setShowBellPopover] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [recentJobs, setRecentJobs] = useState([]);

  // Change password modal state
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwError, setPwError] = useState('');
  const [pwSuccess, setPwSuccess] = useState('');
  const [pwLoading, setPwLoading] = useState(false);

  const popoverRef = useRef(null);
  const userMenuRef = useRef(null);
  const bellMenuRef = useRef(null);

  // Global Ctrl+K shortcut for command palette
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setShowPalette((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // Fetch recent jobs for notifications dropdown
  useEffect(() => {
    let mounted = true;
    const fetchJobs = async () => {
      try {
        const res = await fetch('/api/jobs');
        if (res.ok && mounted) {
          const data = await res.json();
          const list = Array.isArray(data) ? data : data.jobs || [];
          setRecentJobs(list.slice(0, 5));
        }
      } catch {
        // graceful ignore
      }
    };
    fetchJobs();
    const timer = setInterval(fetchJobs, 25000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, []);

  // Close dropdowns on outside click
  useEffect(() => {
    const handleOutsideClick = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target)) {
        setShowConnPopover(false);
      }
      if (userMenuRef.current && !userMenuRef.current.contains(e.target)) {
        setShowUserMenu(false);
      }
      if (bellMenuRef.current && !bellMenuRef.current.contains(e.target)) {
        setShowBellPopover(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  // Breadcrumbs calculation
  const pathSegments = location.pathname.split('/').filter(Boolean);
  const currentSegment = pathSegments[pathSegments.length - 1] || '';
  const currentPageTitle = ROUTE_LABELS[currentSegment] || 'Dashboard';

  const breadcrumbs = [
    { label: 'Overview', path: '/' },
    ...pathSegments.map((segment, idx) => {
      const path = '/' + pathSegments.slice(0, idx + 1).join('/');
      return {
        label: ROUTE_LABELS[segment] || segment,
        path,
      };
    }),
  ];

  const handleChangePassword = async (e) => {
    e.preventDefault();
    setPwError('');
    setPwSuccess('');

    if (newPw.length < 8) {
      setPwError('New password must be at least 8 characters long');
      return;
    }
    if (newPw !== confirmPw) {
      setPwError('New passwords do not match');
      return;
    }

    setPwLoading(true);
    try {
      await changePassword(currentPw, newPw);
      setPwSuccess('Password changed successfully');
      setCurrentPw('');
      setNewPw('');
      setConfirmPw('');
      setTimeout(() => setShowPasswordModal(false), 1500);
    } catch (err) {
      setPwError(err.message || 'Failed to change password');
    } finally {
      setPwLoading(false);
    }
  };

  const hasRunningJobs = recentJobs.some((j) => j.status === 'running');
  const hasFailedJobs = recentJobs.some((j) => j.status === 'failed');

  return (
    <>
      <header className="h-16 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 z-30 transition-colors flex-shrink-0 sticky top-0 px-6 lg:px-8">
        <div className="max-w-[1440px] mx-auto w-full h-full flex items-center justify-between gap-4">
          
          {/* Left: Mobile hamburger & aligned breadcrumb */}
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={onMenuClick}
              className="lg:hidden p-2 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 focus:outline-none flex-shrink-0"
              aria-label="Open sidebar"
            >
              <Menu className="w-5 h-5" />
            </button>

            {/* Mobile current page title (<=640px) */}
            <div className="sm:hidden font-semibold text-sm text-slate-900 dark:text-slate-100 truncate">
              {currentPageTitle}
            </div>

            {/* Desktop dynamic breadcrumbs (14px, aligned with content left edge) */}
            <nav aria-label="Breadcrumbs" className="hidden sm:flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400 truncate">
              {breadcrumbs.map((bc, idx) => {
                const isLast = idx === breadcrumbs.length - 1;
                return (
                  <React.Fragment key={bc.path + idx}>
                    {idx > 0 && <ChevronRight className="w-4 h-4 text-slate-300 dark:text-slate-600 flex-shrink-0" />}
                    {isLast ? (
                      <span className="font-semibold text-slate-900 dark:text-slate-100 truncate">
                        {bc.label}
                      </span>
                    ) : (
                      <Link
                        to={bc.path}
                        className="hover:text-slate-900 dark:hover:text-slate-200 transition-colors truncate"
                      >
                        {bc.label}
                      </Link>
                    )}
                  </React.Fragment>
                );
              })}
            </nav>
          </div>

          {/* Right: Controls in strict requested order:
              1. Search / Command Palette (Ctrl+K)
              2. Connection-status pill (single source of truth with KPI)
              3. Notifications bell
              4. Theme toggle (with tooltip)
              5. User avatar menu
          */}
          <div className="flex items-center gap-2 sm:gap-3 flex-shrink-0">

            {/* 1. Global Search / Command Palette trigger */}
            <button
              type="button"
              onClick={() => setShowPalette(true)}
              className="flex items-center gap-2 px-2.5 sm:px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/60 hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
              title="Search and quick jump (Ctrl+K)"
            >
              <Search className="w-3.5 h-3.5 text-slate-400" />
              <span className="hidden md:inline font-medium">Search...</span>
              <kbd className="hidden lg:inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-slate-400 dark:text-slate-400 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded shadow-xs">
                ⌘K
              </kbd>
            </button>

            {/* 2. Connection Status Pill & Popover (Single Source of Truth) */}
            <div className="relative" ref={popoverRef}>
              <button
                type="button"
                onClick={() => setShowConnPopover(!showConnPopover)}
                className={`flex items-center gap-2 px-2.5 sm:px-3 py-1.5 rounded-full border text-xs font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 cursor-pointer ${
                  summary.isInitialLoading
                    ? 'bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400'
                    : summary.overallHealth === 'operational'
                    ? 'bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/80 text-emerald-800 dark:text-emerald-300'
                    : summary.overallHealth === 'degraded'
                    ? 'bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800/80 text-amber-800 dark:text-amber-300'
                    : 'bg-rose-50 dark:bg-rose-950/40 border-rose-200 dark:border-rose-800/80 text-rose-800 dark:text-rose-300'
                }`}
                title={`System status: ${summary.connectedCount}/${summary.totalCount} operational`}
                aria-label="Server connections status dropdown"
              >
                {summary.isInitialLoading ? (
                  <>
                    <RefreshCw className="w-3 h-3 animate-spin text-teal-600" />
                    <span className="font-medium text-xs">Checking...</span>
                  </>
                ) : (
                  <>
                    <span
                      className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        summary.overallHealth === 'operational'
                          ? 'bg-emerald-500'
                          : summary.overallHealth === 'degraded'
                          ? 'bg-amber-500 animate-pulse'
                          : 'bg-rose-500 animate-pulse'
                      }`}
                    />
                    <span className="tabular-nums font-semibold text-xs">
                      <span className="sm:hidden">{summary.connectedCount}/{summary.totalCount}</span>
                      <span className="hidden sm:inline">
                        {summary.connectedCount}/{summary.totalCount} Connected
                      </span>
                    </span>
                  </>
                )}
                <ChevronDown className="w-3.5 h-3.5 opacity-70" />
              </button>

              {/* Popover Dropdown listing all 7 canonical servers */}
              {showConnPopover && (
                <div className="absolute right-0 mt-2 w-80 sm:w-96 max-w-[calc(100vw-32px)] bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-800 py-3.5 px-4 z-50 animate-in fade-in slide-in-from-top-1 duration-150">
                  <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
                    <div>
                      <h3 className="font-bold text-slate-900 dark:text-slate-100 text-sm flex items-center gap-2">
                        <Server className="w-4 h-4 text-teal-600 dark:text-teal-400" />
                        Target Systems
                      </h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                        <span className="font-semibold text-emerald-600 dark:text-emerald-400">{summary.connectedCount} connected</span>
                        {summary.offlineCount > 0 && (
                          <span className="text-rose-600 dark:text-rose-400 ml-1">· {summary.offlineCount} offline</span>
                        )}
                        <span className="text-slate-400 ml-1.5 font-sans tabular-nums">({secondsAgo}s ago)</span>
                      </p>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={testAll}
                        disabled={testingAll}
                        className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-teal-50 dark:bg-teal-950/50 hover:bg-teal-100 dark:hover:bg-teal-900/60 text-teal-700 dark:text-teal-300 border border-teal-200 dark:border-teal-800 transition flex items-center gap-1 cursor-pointer"
                        title="Test all server endpoints"
                      >
                        <RefreshCw className={`w-3 h-3 ${testingAll ? 'animate-spin' : ''}`} />
                        <span>{testingAll ? 'Testing...' : 'Test All'}</span>
                      </button>
                    </div>
                  </div>

                  <div className="divide-y divide-slate-100 dark:divide-slate-800/80 my-2 max-h-72 overflow-y-auto pr-1">
                    {summary.list.map((sys) => {
                      return (
                        <div key={sys.key} className="py-2.5 flex items-center justify-between gap-3 hover:bg-slate-50/50 dark:hover:bg-slate-800/30 px-1 rounded-lg transition-colors">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span
                                className={`w-2 h-2 rounded-full flex-shrink-0 ${
                                  sys.isTesting
                                    ? 'bg-amber-400 animate-ping'
                                    : sys.isConnected
                                    ? 'bg-emerald-500'
                                    : sys.isConfigured
                                    ? 'bg-rose-500'
                                    : 'bg-slate-400'
                                }`}
                              />
                              <span className="font-semibold text-xs text-slate-800 dark:text-slate-200 truncate">
                                {sys.name}
                              </span>
                              <span className="text-xs px-2 py-0.5 rounded font-medium bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700/60">
                                {sys.source}
                              </span>
                            </div>
                            <div className="font-mono text-xs text-slate-400 truncate mt-0.5 pl-4">
                              {sys.effectiveUrl || 'Not configured'}
                            </div>
                          </div>

                          <div className="flex items-center gap-2 flex-shrink-0">
                            {sys.latencyMs !== null && sys.latencyMs > 0 && (
                              <span className="text-xs font-sans tabular-nums font-medium text-slate-600 dark:text-slate-400">
                                {sys.latencyMs} ms
                              </span>
                            )}
                            <button
                              type="button"
                              onClick={() => testSingle(sys.key)}
                              disabled={sys.isTesting}
                              className="p-1 rounded text-slate-400 hover:text-teal-600 dark:hover:text-teal-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition cursor-pointer"
                              title={`Test connection for ${sys.name}`}
                              aria-label={`Test connection for ${sys.name}`}
                            >
                              <RefreshCw className={`w-3.5 h-3.5 ${sys.isTesting ? 'animate-spin text-teal-600' : ''}`} />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="pt-2.5 border-t border-slate-100 dark:border-slate-800 flex justify-between items-center text-xs">
                    <Link
                      to="/settings"
                      onClick={() => setShowConnPopover(false)}
                      className="text-teal-600 dark:text-teal-400 hover:underline font-semibold flex items-center gap-1"
                    >
                      Manage Server Credentials <ArrowRight className="w-3.5 h-3.5" />
                    </Link>
                    <button
                      onClick={() => setShowConnPopover(false)}
                      className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-300"
                    >
                      Close
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* 3. Notifications Bell */}
            <div className="relative" ref={bellMenuRef}>
              <button
                type="button"
                onClick={() => setShowBellPopover(!showBellPopover)}
                className="relative p-2 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                title="Operations Activity & Notifications"
                aria-label="Activity Notifications"
              >
                <Bell className="w-4 h-4" />
                {(hasRunningJobs || hasFailedJobs) && (
                  <span
                    className={`absolute top-1.5 right-1.5 w-2 h-2 rounded-full ${
                      hasFailedJobs ? 'bg-rose-500 ring-2 ring-white dark:ring-slate-900' : 'bg-teal-500 animate-pulse'
                    }`}
                  />
                )}
              </button>

              {showBellPopover && (
                <div className="absolute right-0 mt-2 w-80 max-w-[calc(100vw-32px)] bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-800 py-3 px-4 z-50 animate-in fade-in slide-in-from-top-1 duration-150">
                  <div className="flex items-center justify-between pb-2.5 border-b border-slate-100 dark:border-slate-800">
                    <h3 className="font-bold text-slate-900 dark:text-slate-100 text-xs sm:text-sm">
                      Recent Activity
                    </h3>
                    <Link
                      to="/jobs"
                      onClick={() => setShowBellPopover(false)}
                      className="text-xs text-teal-600 dark:text-teal-400 hover:underline font-semibold"
                    >
                      View All Jobs →
                    </Link>
                  </div>

                  <div className="divide-y divide-slate-100 dark:divide-slate-800/80 my-2 max-h-60 overflow-y-auto">
                    {recentJobs.length === 0 ? (
                      <div className="py-6 text-center text-xs text-slate-400">
                        No recent operations recorded.
                      </div>
                    ) : (
                      recentJobs.map((j) => (
                        <div key={j.id} className="py-2.5 flex items-start gap-2.5">
                          <span
                            className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                              j.status === 'completed'
                                ? 'bg-emerald-500'
                                : j.status === 'running'
                                ? 'bg-blue-500 animate-pulse'
                                : j.status === 'failed'
                                ? 'bg-rose-500'
                                : 'bg-slate-400'
                            }`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-semibold text-slate-800 dark:text-slate-200 truncate">
                              {j.action || j.pipeline || j.id}
                            </div>
                            <div className="text-[11px] text-slate-400 mt-0.5">
                              {j.module} · {j.status}
                            </div>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* 4. Theme Toggle (with accessible tooltip) */}
            <Tooltip content={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
              <button
                type="button"
                onClick={toggleTheme}
                className="p-2 text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {theme === 'dark' ? (
                  <Sun className="w-4 h-4 text-amber-400 hover:text-amber-300" />
                ) : (
                  <Moon className="w-4 h-4 text-slate-600 hover:text-slate-900" />
                )}
              </button>
            </Tooltip>

            {/* 5. User Avatar & Profile Dropdown */}
            <div className="relative pl-1 sm:pl-2 border-l border-slate-200 dark:border-slate-800 flex-shrink-0" ref={userMenuRef}>
              <button
                type="button"
                onClick={() => setShowUserMenu(!showUserMenu)}
                className="flex items-center gap-2 p-1 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 cursor-pointer flex-shrink-0"
                title={`${user?.username || 'User'} (${user?.role || 'Admin'})`}
                aria-label="User account menu"
              >
                <div className="w-8 h-8 rounded-full bg-teal-600 text-white flex items-center justify-center font-bold text-xs shadow-xs flex-shrink-0">
                  {user?.username ? user.username.slice(0, 2).toUpperCase() : 'AD'}
                </div>
                <div className="hidden md:flex flex-col text-left">
                  <span className="text-xs font-semibold text-slate-800 dark:text-slate-200 leading-tight">
                    {user?.username || 'admin'}
                  </span>
                  <span className="text-xs text-slate-400 capitalize leading-tight">
                    {user?.role || 'administrator'}
                  </span>
                </div>
                <ChevronDown className="w-3.5 h-3.5 text-slate-400 hidden sm:inline" />
              </button>

              {/* User Menu Dropdown */}
              {showUserMenu && (
                <div className="absolute right-0 mt-2 w-56 max-w-[calc(100vw-32px)] bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-800 py-1.5 z-50 animate-in fade-in slide-in-from-top-1 duration-150">
                  <div className="px-4 py-2.5 border-b border-slate-100 dark:border-slate-800">
                    <p className="text-xs font-bold text-slate-900 dark:text-slate-100">
                      {user?.username || 'admin'}
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400 capitalize">
                      Role: {user?.role || 'Administrator'}
                    </p>
                  </div>

                  <div className="py-1">
                    <button
                      type="button"
                      onClick={() => {
                        setShowUserMenu(false);
                        setShowPasswordModal(true);
                      }}
                      className="w-full text-left px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/80 flex items-center gap-2"
                    >
                      <KeyRound className="w-4 h-4 text-slate-400" />
                      <span>Change Password</span>
                    </button>
                    <Link
                      to="/settings"
                      onClick={() => setShowUserMenu(false)}
                      className="w-full text-left px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800/80 flex items-center gap-2"
                    >
                      <Server className="w-4 h-4 text-slate-400" />
                      <span>Settings & Connections</span>
                    </Link>
                  </div>

                  <div className="pt-1 border-t border-slate-100 dark:border-slate-800">
                    <button
                      type="button"
                      onClick={() => {
                        setShowUserMenu(false);
                        logout();
                      }}
                      className="w-full text-left px-4 py-2 text-xs font-semibold text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/40 flex items-center gap-2"
                    >
                      <LogOut className="w-4 h-4" />
                      <span>Sign Out</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

          </div>
        </div>
      </header>

      {/* Command Palette Modal */}
      <CommandPalette isOpen={showPalette} onClose={() => setShowPalette(false)} />

      {/* Change Password Modal */}
      <Modal
        isOpen={showPasswordModal}
        onClose={() => setShowPasswordModal(false)}
        title="Change Password"
        size="sm"
      >
        <form onSubmit={handleChangePassword} className="space-y-4">
          {pwError && <Alert variant="danger">{pwError}</Alert>}
          {pwSuccess && <Alert variant="success">{pwSuccess}</Alert>}

          <TextInput
            label="Current Password"
            type="password"
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
            required
            autoFocus
          />
          <TextInput
            label="New Password"
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            helperText="Minimum 8 characters"
            required
          />
          <TextInput
            label="Confirm New Password"
            type="password"
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
            required
          />

          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="secondary"
              type="button"
              onClick={() => setShowPasswordModal(false)}
            >
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={pwLoading}>
              Update Password
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
};

export default Topbar;
