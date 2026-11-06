import React, { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Menu,
  Activity,
  Search,
  Bell,
  Sun,
  Moon,
  ChevronDown,
  RefreshCw,
  LogOut,
  KeyRound,
  Server,
  X,
  ExternalLink,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import { useConnections } from '../context/ConnectionContext';
import { Tooltip } from '../ui';
import CommandPalette from './CommandPalette';

/**
 * AppHeader (Topbar)
 * Restructured per Section A criteria:
 * - Full-width dark top bar using the same color family as the sidebar (bg-slate-950)
 * - Separated from content area by subtle 1px border (border-slate-800)
 * - Left: Sidebar collapse toggle (min 36px hit area) + Brand Logo & Tagline (white 17px, teal 12px)
 * - Right: Controls in strict requested order:
 *     1. Search / Command Palette (Ctrl+K)
 *     2. Connection status pill (opens dropdown listing each server's status and latency)
 *     3. Notifications bell
 *     4. Theme toggle (with tooltip)
 *     5. User account menu
 * - Restyled for dark surface with WCAG AA contrast, light text, visible focus rings
 */
export const Topbar = ({ onMenuClick, isCollapsed, onToggleCollapse }) => {
  const { user, logout, changePassword } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { summary, loading: connLoading, secondsAgo, testSingle, testAll, testingAll } = useConnections();
  const navigate = useNavigate();

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

  const handleToggleClick = () => {
    if (window.innerWidth < 1024) {
      if (onMenuClick) onMenuClick();
    } else {
      if (onToggleCollapse) onToggleCollapse();
    }
  };

  return (
    <>
      {/* FULL-WIDTH DARK TOP BAR: Centered brand with 3-column grid (56-64px) */}
      <header className="h-16 bg-slate-950 text-slate-200 border-b border-slate-800 shadow-xs z-30 flex-shrink-0 sticky top-0 px-4 sm:px-6 select-none transition-colors">
        <div className="w-full h-full flex md:grid md:grid-cols-[1fr_auto_1fr] items-center justify-between gap-2 sm:gap-4">
          
          {/* Column 1 (Left): Sidebar toggle + LOCAL badge (Desktop) / Left-aligned brand (Mobile <768px) */}
          <div className="flex items-center gap-2.5 sm:gap-3 min-w-0 justify-start">
            <button
              type="button"
              onClick={handleToggleClick}
              className="w-9 h-9 min-w-[36px] min-h-[36px] flex items-center justify-center text-slate-300 hover:text-white rounded-lg hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 transition-colors flex-shrink-0 cursor-pointer"
              aria-label="Toggle navigation sidebar"
              title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              <Menu className="w-5 h-5" />
            </button>

            {/* LOCAL Environment Badge */}
            <span className="hidden sm:inline-flex items-center text-[10px] font-bold px-2 py-0.5 rounded-full bg-teal-500/15 border border-teal-500/30 text-teal-300 uppercase tracking-wider select-none flex-shrink-0">
              LOCAL
            </span>

            {/* Below ~768px: Brand switches to left-aligned next to hamburger */}
            <Link
              to="/"
              className="flex md:hidden items-center gap-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 rounded-lg p-1 group flex-shrink-0 ml-1"
              title="IMNID Hub Dashboard"
            >
              <div className="h-8 px-1.5 flex-shrink-0 rounded-lg bg-white border border-slate-700/60 flex items-center justify-center shadow-xs overflow-hidden">
                <img
                  src="/IMNID_Hub_logo.png"
                  alt="IMNID Hub"
                  className="h-6 w-auto object-contain"
                />
              </div>
              <span className="text-base font-bold text-white tracking-tight leading-none">
                IMNID Hub
              </span>
            </Link>
          </div>

          {/* Column 2 (Center): Brand Logo + Name + Tagline centered on full screen width (>=768px) */}
          <div className="hidden md:flex items-center justify-center min-w-0">
            <Link
              to="/"
              className="flex items-center gap-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 rounded-xl px-3 py-1.5 group transition-colors hover:bg-slate-900/60"
              title="IMNID Hub Dashboard"
            >
              <div className="h-10 px-2.5 flex-shrink-0 rounded-xl bg-white border border-slate-700/60 flex items-center justify-center shadow-xs group-hover:scale-105 transition-all overflow-hidden">
                <img
                  src="/IMNID_Hub_logo.png"
                  alt="IMNID Hub"
                  className="h-7 w-auto object-contain"
                />
              </div>
              <div className="min-w-0 flex flex-col text-left">
                <span className="text-[17px] font-bold text-white tracking-tight leading-none">
                  IMNID Hub
                </span>
                {/* Tagline: visible on >=1100px, hidden below ~1100px */}
                <span className="hidden min-[1100px]:inline-block text-xs text-teal-400 font-medium tracking-wide leading-tight mt-1">
                  Interoperability Platform
                </span>
              </div>
            </Link>
          </div>

          {/* Column 3 (Right): Search, Connection Pill, Bell, Theme, User Menu (Right-Aligned) */}
          <div className="flex items-center justify-end gap-1.5 sm:gap-2.5 min-w-0">

            {/* 1. Global Search: Full bar on >=900px, icon button below ~900px */}
            <button
              type="button"
              onClick={() => setShowPalette(true)}
              className="hidden min-[900px]:flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-800 bg-slate-900 hover:bg-slate-800 text-slate-300 text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 cursor-pointer shadow-xs"
              title="Search and quick jump (Ctrl+K)"
            >
              <Search className="w-3.5 h-3.5 text-slate-400" />
              <span className="font-medium text-slate-300">Search tools...</span>
              <kbd className="hidden lg:inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-slate-400 bg-slate-800 border border-slate-700 rounded ml-1">
                Ctrl+K
              </kbd>
            </button>
            <button
              type="button"
              onClick={() => setShowPalette(true)}
              className="flex min-[900px]:hidden p-2 text-slate-300 hover:text-white rounded-lg hover:bg-slate-800 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 cursor-pointer"
              title="Search tools (Ctrl+K)"
              aria-label="Search tools"
            >
              <Search className="w-4 h-4 text-slate-300" />
            </button>

            {/* 2. Connection Status Pill & Popover (Single Source of Truth) */}
            <div className="relative" ref={popoverRef}>
              <button
                type="button"
                onClick={() => setShowConnPopover(!showConnPopover)}
                className={`flex items-center gap-2 px-2.5 sm:px-3 py-1.5 rounded-full border text-xs font-semibold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 cursor-pointer ${
                  summary.isInitialLoading
                    ? 'bg-slate-800 text-slate-300 border-slate-700'
                    : summary.overallHealth === 'operational'
                    ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                    : summary.overallHealth === 'degraded'
                    ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                    : 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                }`}
                title={`System status: ${summary.connectedCount}/${summary.totalCount} operational`}
                aria-label="Server connections status dropdown"
              >
                {summary.isInitialLoading ? (
                  <>
                    <RefreshCw className="w-3 h-3 animate-spin text-teal-400" />
                    <span className="font-medium text-xs">Checking...</span>
                  </>
                ) : (
                  <>
                    <span
                      className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        summary.overallHealth === 'operational'
                          ? 'bg-emerald-400'
                          : summary.overallHealth === 'degraded'
                          ? 'bg-amber-400 animate-pulse'
                          : 'bg-rose-400 animate-pulse'
                      }`}
                    />
                    <span className="tabular-nums font-semibold text-xs">
                      <span className="sm:hidden">{summary.connectedCount}/{summary.totalCount}</span>
                      <span className="hidden sm:inline">{summary.connectedCount}/{summary.totalCount} Connected</span>
                    </span>
                  </>
                )}
                <ChevronDown className="w-3.5 h-3.5 opacity-70" />
              </button>

              {/* Popover Dropdown listing all 7 canonical servers */}
              {showConnPopover && (
                <div className="absolute right-0 mt-2 w-80 sm:w-96 max-w-[calc(100vw-32px)] bg-slate-900 rounded-xl shadow-2xl border border-slate-800 py-3.5 px-4 z-50 animate-in fade-in slide-in-from-top-1 duration-150 text-slate-200">
                  <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                    <div>
                      <h3 className="font-bold text-white text-sm flex items-center gap-2">
                        <Server className="w-4 h-4 text-teal-400" />
                        Target Systems
                      </h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        <span className="font-semibold text-emerald-400">{summary.connectedCount} connected</span>
                        {summary.offlineCount > 0 && (
                          <span className="text-rose-400 ml-1">· {summary.offlineCount} offline</span>
                        )}
                        <span className="text-slate-400 ml-1.5 font-sans tabular-nums">({secondsAgo}s ago)</span>
                      </p>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={testAll}
                        disabled={testingAll}
                        className="px-2.5 py-1 text-xs font-semibold rounded-lg bg-teal-950/60 hover:bg-teal-900/80 text-teal-300 border border-teal-800 transition flex items-center gap-1 cursor-pointer"
                        title="Test all server endpoints"
                      >
                        <RefreshCw className={`w-3 h-3 ${testingAll ? 'animate-spin' : ''}`} />
                        <span>{testingAll ? 'Testing...' : 'Test All'}</span>
                      </button>
                    </div>
                  </div>

                  <div className="divide-y divide-slate-800 my-2 max-h-72 overflow-y-auto pr-1">
                    {summary.list.map((sys) => {
                      return (
                        <div key={sys.key} className="py-2.5 flex items-center justify-between gap-3 hover:bg-slate-800/40 px-1 rounded-lg transition-colors">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span
                                className={`w-2 h-2 rounded-full flex-shrink-0 ${
                                  sys.isTesting
                                    ? 'bg-amber-400 animate-ping'
                                    : sys.isConnected
                                    ? 'bg-emerald-400'
                                    : sys.isConfigured
                                    ? 'bg-rose-400'
                                    : 'bg-slate-400'
                                }`}
                              />
                              <span className="font-semibold text-xs text-slate-100 truncate">
                                {sys.name}
                              </span>
                              <span className="text-xs px-2 py-0.5 rounded font-medium bg-slate-800 text-slate-300 border border-slate-700/60">
                                {sys.source}
                              </span>
                            </div>
                            <div className="font-mono text-xs text-slate-400 truncate mt-0.5 pl-4">
                              {sys.effectiveUrl || 'Not configured'}
                            </div>
                          </div>

                          <div className="flex items-center gap-2 flex-shrink-0">
                            {sys.latencyMs !== null && sys.latencyMs > 0 && (
                              <span className="text-xs font-sans tabular-nums font-medium text-slate-300">
                                {sys.latencyMs} ms
                              </span>
                            )}
                            <button
                              type="button"
                              onClick={() => testSingle(sys.key)}
                              disabled={sys.isTesting}
                              className="p-1 rounded text-slate-400 hover:text-teal-400 hover:bg-slate-800 transition cursor-pointer"
                              title={`Test connection for ${sys.name}`}
                              aria-label={`Test connection for ${sys.name}`}
                            >
                              <RefreshCw className={`w-3.5 h-3.5 ${sys.isTesting ? 'animate-spin text-teal-400' : ''}`} />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="pt-2.5 border-t border-slate-800 flex justify-between items-center text-xs">
                    <Link
                      to="/settings"
                      onClick={() => setShowConnPopover(false)}
                      className="text-teal-400 hover:underline flex items-center gap-1 font-semibold"
                    >
                      <span>Settings & Credentials</span>
                      <ExternalLink className="w-3 h-3" />
                    </Link>
                    <button
                      onClick={() => setShowConnPopover(false)}
                      className="text-slate-400 hover:text-slate-200"
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
                className="relative p-2 text-slate-300 hover:text-white rounded-lg hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 cursor-pointer"
                title="Operations Activity & Notifications"
                aria-label="Activity Notifications"
              >
                <Bell className="w-4 h-4" />
                {(hasRunningJobs || hasFailedJobs) && (
                  <span
                    className={`absolute top-1.5 right-1.5 w-2 h-2 rounded-full ${
                      hasFailedJobs ? 'bg-rose-500 ring-2 ring-slate-950' : 'bg-teal-400 animate-pulse'
                    }`}
                  />
                )}
              </button>

              {showBellPopover && (
                <div className="absolute right-0 mt-2 w-80 max-w-[calc(100vw-32px)] bg-slate-900 rounded-xl shadow-2xl border border-slate-800 py-3 px-4 z-50 animate-in fade-in slide-in-from-top-1 duration-150 text-slate-200">
                  <div className="flex items-center justify-between pb-2.5 border-b border-slate-800">
                    <h3 className="font-bold text-white text-xs sm:text-sm">
                      Recent Activity
                    </h3>
                    <Link
                      to="/jobs"
                      onClick={() => setShowBellPopover(false)}
                      className="text-xs text-teal-400 hover:underline font-semibold"
                    >
                      View All Jobs →
                    </Link>
                  </div>

                  <div className="divide-y divide-slate-800 my-2 max-h-60 overflow-y-auto">
                    {recentJobs.length === 0 ? (
                      <p className="py-4 text-center text-xs text-slate-400">
                        No recent operations recorded
                      </p>
                    ) : (
                      recentJobs.map((j) => (
                        <div key={j.id} className="py-2.5 flex items-start gap-2.5">
                          <span
                            className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${
                              j.status === 'completed'
                                ? 'bg-emerald-400'
                                : j.status === 'running'
                                ? 'bg-blue-400 animate-pulse'
                                : j.status === 'failed'
                                ? 'bg-rose-400'
                                : 'bg-slate-400'
                            }`}
                          />
                          <div className="min-w-0 flex-1">
                            <div className="text-xs font-semibold text-slate-200 truncate">
                              {j.action || j.pipeline || j.id}
                            </div>
                            <div className="text-xs text-slate-400 mt-0.5 capitalize">
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
                className="p-2 text-slate-300 hover:text-white rounded-lg hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 cursor-pointer"
                aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {theme === 'dark' ? (
                  <Sun className="w-4 h-4 text-amber-400 hover:text-amber-300" />
                ) : (
                  <Moon className="w-4 h-4 text-slate-300 hover:text-white" />
                )}
              </button>
            </Tooltip>

            {/* 5. User Avatar & Profile Dropdown */}
            <div className="relative pl-1 sm:pl-2 border-l border-slate-800 flex-shrink-0" ref={userMenuRef}>
              <button
                type="button"
                onClick={() => setShowUserMenu(!showUserMenu)}
                className="flex items-center gap-2 p-1 rounded-lg hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-400 cursor-pointer flex-shrink-0"
                title={`${user?.username || 'User'} (${user?.role || 'Admin'})`}
                aria-label="User account menu"
              >
                <div className="w-8 h-8 rounded-full bg-teal-600 text-white flex items-center justify-center font-bold text-xs shadow-xs flex-shrink-0">
                  {user?.username ? user.username.slice(0, 2).toUpperCase() : 'AD'}
                </div>
                <div className="hidden md:flex flex-col text-left">
                  <span className="text-xs font-semibold text-slate-200 leading-tight">
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
                <div className="absolute right-0 mt-2 w-56 max-w-[calc(100vw-32px)] bg-slate-900 rounded-xl shadow-2xl border border-slate-800 py-1.5 z-50 animate-in fade-in slide-in-from-top-1 duration-150 text-slate-200">
                  <div className="px-4 py-2.5 border-b border-slate-800">
                    <p className="text-xs font-bold text-white">
                      {user?.username || 'admin'}
                    </p>
                    <p className="text-xs text-slate-400 capitalize">
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
                      className="w-full text-left px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800 hover:text-white flex items-center gap-2"
                    >
                      <KeyRound className="w-4 h-4 text-slate-400" />
                      <span>Change Password</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setShowUserMenu(false);
                        logout();
                        navigate('/login');
                      }}
                      className="w-full text-left px-4 py-2 text-xs font-medium text-rose-400 hover:bg-slate-800 flex items-center gap-2"
                    >
                      <LogOut className="w-4 h-4 text-rose-400" />
                      <span>Sign Out</span>
                    </button>
                  </div>
                </div>
              )}
            </div>

          </div>
        </div>
      </header>

      {/* Global Command Palette */}
      <CommandPalette isOpen={showPalette} onClose={() => setShowPalette(false)} />

      {/* Change Password Modal */}
      {showPasswordModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/70 backdrop-blur-xs">
          <div className="w-full max-w-md bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-2xl p-6 space-y-4 animate-in fade-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-slate-200 dark:border-slate-800">
              <h3 className="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-teal-600 dark:text-teal-400" />
                Change Password
              </h3>
              <button
                type="button"
                onClick={() => setShowPasswordModal(false)}
                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleChangePassword} className="space-y-4 text-sm">
              {pwError && (
                <div className="p-3 rounded-lg bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 text-xs font-medium">
                  {pwError}
                </div>
              )}
              {pwSuccess && (
                <div className="p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-900 text-emerald-700 dark:text-emerald-300 text-xs font-medium">
                  {pwSuccess}
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Current Password
                </label>
                <input
                  type="password"
                  value={currentPw}
                  onChange={(e) => setCurrentPw(e.target.value)}
                  required
                  className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  New Password (min 8 characters)
                </label>
                <input
                  type="password"
                  value={newPw}
                  onChange={(e) => setNewPw(e.target.value)}
                  required
                  className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Confirm New Password
                </label>
                <input
                  type="password"
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  required
                  className="w-full px-3 py-2 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-teal-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowPasswordModal(false)}
                  className="px-3.5 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={pwLoading}
                  className="px-4 py-2 text-xs font-semibold text-white bg-teal-600 hover:bg-teal-700 rounded-lg shadow-xs transition disabled:opacity-50"
                >
                  {pwLoading ? 'Saving...' : 'Update Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
};

export default Topbar;
