import React, { useState, useEffect, useRef } from 'react';
import { useLocation, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
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
} from 'lucide-react';
import { Modal, Button, TextInput, Badge, Alert } from '../ui';

const ROUTE_LABELS = {
  '': 'Dashboard',
  smartcare: 'SmartCare Migration',
  'data-management': 'Data Management',
  'dhis2-sync': 'DHIS2 Direct Sync',
  'csv-import': 'DHIS2 Tracker Data Import',
  'metadata-import': 'Metadata Importer',
  cleaning: 'Data Transformation',
  'analysis-export': 'Analysis Export',
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
  rmh: 'RMH Register (01.2)',
  nh: 'NICU Register (04.2)',
  jobs: 'Job History & Logs',
  settings: 'Settings & Credentials',
};

const SYSTEMS = [
  { key: 'dhis2_online', label: 'DHIS2 Online' },
  { key: 'dhis2_offline', label: 'DHIS2 Offline' },
  { key: 'openmrs', label: 'OpenMRS 3.x' },
  { key: 'bahmni', label: 'Bahmni' },
  { key: 'redcap', label: 'REDCap' },
  { key: 'mediator', label: 'Mediator Service' },
];

/**
 * Modern Responsive Topbar
 * Displays dynamic breadcrumbs, connection status popover, compact mobile topbar (fitting 360px),
 * and 4-state connection semantics.
 */
const Topbar = ({ onMenuClick }) => {
  const { user, logout, changePassword } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const location = useLocation();

  const [statuses, setStatuses] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showConnPopover, setShowConnPopover] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  // Change password modal state
  const [currentPw, setCurrentPw] = useState('');
  const [newPw, setNewPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [pwError, setPwError] = useState('');
  const [pwSuccess, setPwSuccess] = useState('');
  const [pwLoading, setPwLoading] = useState(false);

  const popoverRef = useRef(null);
  const userMenuRef = useRef(null);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/connections/status');
      if (res.ok) {
        const data = await res.json();
        setStatuses(data);
      }
    } catch (e) {
      console.error('Failed to fetch status:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
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
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  // Breadcrumbs calculation
  const pathSegments = location.pathname.split('/').filter(Boolean);
  const currentSegment = pathSegments[pathSegments.length - 1] || '';
  const currentPageTitle = ROUTE_LABELS[currentSegment] || 'Dashboard';

  const breadcrumbs = [
    { label: 'Home', path: '/' },
    ...pathSegments.map((segment, idx) => {
      const path = '/' + pathSegments.slice(0, idx + 1).join('/');
      return {
        label: ROUTE_LABELS[segment] || segment,
        path,
      };
    }),
  ];

  // Configured vs unconfigured systems count
  const configuredSystems = statuses
    ? SYSTEMS.filter((s) => {
        const item = statuses[s.key];
        return item && item.configured === true && item.status !== 'not_configured';
      })
    : [];
  const configuredTotal = configuredSystems.length;
  const connectedCount = statuses
    ? configuredSystems.filter(
        (s) => statuses[s.key]?.status === 'connected' || statuses[s.key]?.result?.ok === true
      ).length
    : 0;

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

  return (
    <header className="h-16 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-3 sm:px-6 flex items-center justify-between z-20 transition-colors flex-shrink-0">
      {/* Left: Mobile hamburger & breadcrumbs */}
      <div className="flex items-center gap-2 sm:gap-3 min-w-0">
        <button
          onClick={onMenuClick}
          className="lg:hidden p-1.5 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 focus:outline-none flex-shrink-0"
          aria-label="Open sidebar"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Mobile current page title (<=640px) */}
        <div className="sm:hidden font-semibold text-xs text-slate-800 dark:text-slate-200 truncate max-w-[130px]">
          {currentPageTitle}
        </div>

        {/* Desktop dynamic breadcrumbs (>640px) */}
        <nav aria-label="Breadcrumbs" className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 truncate">
          {breadcrumbs.map((bc, idx) => {
            const isLast = idx === breadcrumbs.length - 1;
            return (
              <React.Fragment key={bc.path + idx}>
                {idx > 0 && <ChevronRight className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />}
                {isLast ? (
                  <span className="font-semibold text-slate-800 dark:text-slate-200 truncate">
                    {bc.label}
                  </span>
                ) : (
                  <Link
                    to={bc.path}
                    className="hover:text-slate-800 dark:hover:text-slate-200 transition-colors truncate"
                  >
                    {bc.label}
                  </Link>
                )}
              </React.Fragment>
            );
          })}
        </nav>
      </div>

      {/* Right: Compact Status Pill, Theme Toggle, User Avatar */}
      <div className="flex items-center gap-1.5 sm:gap-3 flex-shrink-0">
        {/* Connection Status Pill & Popover */}
        <div className="relative" ref={popoverRef}>
          <button
            onClick={() => setShowConnPopover(!showConnPopover)}
            className="flex items-center gap-1.5 sm:gap-2 px-2 sm:px-3 py-1.5 rounded-full border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/80 hover:bg-slate-100 dark:hover:bg-slate-800 text-xs transition-colors focus:outline-none cursor-pointer"
            title="System Connection Status"
          >
            <span
              className={`w-2 h-2 rounded-full flex-shrink-0 ${
                connectedCount === configuredTotal && configuredTotal > 0
                  ? 'bg-emerald-500'
                  : connectedCount > 0
                  ? 'bg-amber-500'
                  : 'bg-rose-500'
              }`}
            />
            {/* Compact label on mobile */}
            <span className="font-semibold text-slate-700 dark:text-slate-300 text-[11px] sm:text-xs">
              <span className="sm:hidden">{connectedCount}/{configuredTotal}</span>
              <span className="hidden sm:inline">{connectedCount}/{configuredTotal} Connected</span>
            </span>
            <ChevronDown className="w-3.5 h-3.5 text-slate-400 hidden sm:inline" />
          </button>

          {/* Popover Dropdown */}
          {showConnPopover && (
            <div className="absolute right-0 mt-2 w-80 sm:w-96 bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-800 py-3 px-4 z-50 text-xs animate-in fade-in slide-in-from-top-1 duration-150">
              <div className="flex items-center justify-between pb-2.5 border-b border-slate-100 dark:border-slate-800">
                <div>
                  <h3 className="font-bold text-slate-800 dark:text-slate-100 text-xs sm:text-sm">
                    Target System Connections
                  </h3>
                  <p className="text-[11px] text-slate-500">
                    {connectedCount} of {configuredTotal} configured servers connected
                  </p>
                </div>
                <button
                  onClick={fetchStatus}
                  disabled={loading}
                  className="p-1.5 text-slate-400 hover:text-teal-600 dark:hover:text-teal-400 rounded-md hover:bg-slate-50 dark:hover:bg-slate-800 transition"
                  title="Refresh status"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-teal-600' : ''}`} />
                </button>
              </div>

              <div className="divide-y divide-slate-100 dark:divide-slate-800/80 my-2 max-h-72 overflow-y-auto">
                {SYSTEMS.map((sys) => {
                  const s = statuses?.[sys.key];
                  const isConf = s && s.configured === true && s.status !== 'not_configured';
                  const isConnected = s?.status === 'connected' || s?.result?.ok === true;
                  const isChecking = loading;

                  return (
                    <div key={sys.key} className="py-2 flex items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold text-slate-800 dark:text-slate-200 truncate">
                            {sys.label}
                          </span>
                          {s?.source && (
                            <span className="text-[9px] px-1.5 py-0.2 rounded font-medium bg-slate-100 dark:bg-slate-800 text-slate-500">
                              {s.source === 'vault' ? 'Vault' : 'Env'}
                            </span>
                          )}
                        </div>
                        <div className="font-mono text-[10px] text-slate-400 truncate mt-0.5">
                          {s?.effective_url || s?.configured_url || 'Not configured'}
                        </div>
                      </div>

                      <div className="flex-shrink-0">
                        {isChecking ? (
                          <div className="w-3.5 h-3.5 border-2 border-teal-500 border-t-transparent rounded-full animate-spin" />
                        ) : !isConf ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                            <MinusCircle className="w-3 h-3 text-slate-400" />
                            Not configured
                          </span>
                        ) : isConnected ? (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-200 dark:border-emerald-800">
                            <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                            Connected
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-[10px] font-medium text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-950/40 px-2 py-0.5 rounded border border-rose-200 dark:border-rose-800">
                            <XCircle className="w-3 h-3 text-rose-500" />
                            Unreachable
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="pt-2 border-t border-slate-100 dark:border-slate-800 flex justify-between items-center text-[11px]">
                <Link
                  to="/settings"
                  onClick={() => setShowConnPopover(false)}
                  className="text-teal-600 dark:text-teal-400 hover:underline font-semibold"
                >
                  Manage Vault Credentials →
                </Link>
                <button
                  onClick={() => setShowConnPopover(false)}
                  className="text-slate-400 hover:text-slate-600"
                >
                  Close
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Theme Toggle Button */}
        <button
          onClick={toggleTheme}
          className="p-1.5 sm:p-2 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition focus:outline-none"
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          aria-label="Toggle color theme"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4" />}
        </button>

        {/* User Profile Menu */}
        <div className="relative" ref={userMenuRef}>
          <button
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-2 p-1 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 transition focus:outline-none cursor-pointer"
            aria-label="Open user menu"
          >
            <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-teal-600 text-white flex items-center justify-center font-bold text-xs uppercase shadow-sm">
              {user?.username ? user.username.charAt(0) : 'U'}
            </div>
          </button>

          {showUserMenu && (
            <div className="absolute right-0 mt-2 w-52 bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-800 py-1.5 z-50 text-xs animate-in fade-in slide-in-from-top-1 duration-150">
              <div className="px-3 py-2 border-b border-slate-100 dark:border-slate-800">
                <div className="font-semibold text-slate-800 dark:text-slate-200 truncate">
                  {user?.full_name || user?.username || 'User'}
                </div>
                <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                  Role: {user?.role || 'Operator'}
                </div>
              </div>

              <button
                onClick={() => {
                  setShowUserMenu(false);
                  setShowPasswordModal(true);
                }}
                className="w-full text-left px-3 py-2 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center gap-2"
              >
                <KeyRound className="w-3.5 h-3.5 text-slate-400" />
                Change Password
              </button>

              <button
                onClick={() => {
                  setShowUserMenu(false);
                  logout();
                }}
                className="w-full text-left px-3 py-2 text-rose-600 dark:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/30 flex items-center gap-2 border-t border-slate-100 dark:border-slate-800 mt-1"
              >
                <LogOut className="w-3.5 h-3.5" />
                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Change Password Modal */}
      <Modal
        isOpen={showPasswordModal}
        onClose={() => setShowPasswordModal(false)}
        title="Change Password"
        size="sm"
      >
        <form onSubmit={handleChangePassword} className="space-y-4">
          {pwError && <Alert variant="error" description={pwError} />}
          {pwSuccess && <Alert variant="success" description={pwSuccess} />}

          <TextInput
            label="Current Password"
            type="password"
            required
            value={currentPw}
            onChange={(e) => setCurrentPw(e.target.value)}
          />

          <TextInput
            label="New Password"
            type="password"
            required
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            helperText="Minimum 8 characters"
          />

          <TextInput
            label="Confirm New Password"
            type="password"
            required
            value={confirmPw}
            onChange={(e) => setConfirmPw(e.target.value)}
          />

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setShowPasswordModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={pwLoading}>
              Update Password
            </Button>
          </div>
        </form>
      </Modal>
    </header>
  );
};

export default Topbar;
