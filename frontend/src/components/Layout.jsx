import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import PageFooter from './PageFooter';

/**
 * Main Application Shell Layout
 * Section A Architecture:
 * - Full-width dark Topbar across the very top (56-64px) with brand, collapse toggle, and global controls
 * - Inner frame below Topbar: Collapsible Sidebar + Scrollable Content Main
 * - Fluid 1440px content container with equal 24-32px padding and unified PageFooter
 */
const Layout = () => {
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(() => {
    return localStorage.getItem('imnid_sidebar_collapsed') === 'true';
  });

  const handleToggleCollapse = (val) => {
    setIsCollapsed(val);
    localStorage.setItem('imnid_sidebar_collapsed', String(val));
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-slate-50 dark:bg-slate-900 text-slate-800 dark:text-slate-100 transition-colors">
      {/* 1. Full-Width Dark Top Bar with Brand (pinned at top) */}
      <Topbar
        onMenuClick={() => setIsMobileOpen(true)}
        isCollapsed={isCollapsed}
        onToggleCollapse={() => handleToggleCollapse(!isCollapsed)}
      />

      {/* 2. Main Frame below Topbar: Sidebar + Content Area */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        <Sidebar
          isMobileOpen={isMobileOpen}
          setIsMobileOpen={setIsMobileOpen}
          isCollapsed={isCollapsed}
          setIsCollapsed={handleToggleCollapse}
        />

        <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
          <main className="flex-1 px-6 lg:px-8 py-6 w-full">
            <div className="w-full max-w-[1440px] mx-auto space-y-6">
              <Outlet />
            </div>
          </main>
          <PageFooter />
        </div>
      </div>
    </div>
  );
};

export default Layout;
