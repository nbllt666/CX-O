import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { cn } from '../../lib/utils';

interface SidebarProps {
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
}

interface LayoutProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode | ((props: SidebarProps) => React.ReactNode);
  header?: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({ children, sidebar, header }) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const location = useLocation();

  const renderSidebar = () => {
    if (!sidebar) return null;
    if (typeof sidebar === 'function') {
      return sidebar({ collapsed: sidebarCollapsed, setCollapsed: setSidebarCollapsed });
    }
    return sidebar;
  };

  return (
    <div className="h-screen overflow-hidden">
      {header && (
        <header className="fixed top-0 left-0 right-0 h-[var(--header-height)] z-40">
          <div className="h-full glass-panel border-b-0" style={{ borderRadius: 0 }}>
            {header}
          </div>
        </header>
      )}
      <div className="flex h-[calc(100vh-var(--header-height))] mt-[var(--header-height)]">
        {sidebar && (
          <aside
            className={cn(
              'fixed left-0 top-[var(--header-height)] bottom-0 z-30',
              'transition-all duration-[var(--transition-normal)]',
              sidebarCollapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-[var(--sidebar-width)]'
            )}
          >
            <div className="h-full glass-panel border-r-0 border-t-0 border-b-0" style={{ borderRadius: 0 }}>
              <div className="h-full overflow-y-auto">{renderSidebar()}</div>
            </div>
          </aside>
        )}
        <main
          className={cn(
            'flex-1 h-full',
            'transition-all duration-[var(--transition-normal)]',
            sidebar ? (sidebarCollapsed ? 'ml-[var(--sidebar-collapsed-width)]' : 'ml-[var(--sidebar-width)]') : false
          )}
        >
          <div className="h-full">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
};
