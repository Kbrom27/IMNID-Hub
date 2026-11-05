import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import PageFooter from './PageFooter';

/**
 * Main Application Shell Layout
 * Integrates responsive collapsible sidebar, dynamic topbar, fluid 1440px content container,
 * and unified page footer.
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
    <div className="flex h-screen overflow-hidden bg-slate-50 dark:bg-slate-950 text-slate-800 dark:text-slate-100 transition-colors">
      <Sidebar
        isMobileOpen={isMobileOpen}
        setIsMobileOpen={setIsMobileOpen}
        isCollapsed={isCollapsed}
        setIsCollapsed={handleToggleCollapse}
      />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Topbar onMenuClick={() => setIsMobileOpen(true)} />
        <div className="flex-1 overflow-y-auto flex flex-col">
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
