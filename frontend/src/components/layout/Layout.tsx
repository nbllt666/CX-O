import React, { useState } from 'react';
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

  const renderSidebar = () => {
    if (!sidebar) return null;
    if (typeof sidebar === 'function') {
      return sidebar({ collapsed: sidebarCollapsed, setCollapsed: setSidebarCollapsed });
    }
    return sidebar;
  };

  return (
    <div className="min-h-screen bg-[var(--color-bg-secondary)]">
      {header && (
        <header className="fixed top-0 left-0 right-0 h-[var(--header-height)] bg-[var(--color-bg-primary)] border-b border-[var(--color-border)] z-40">
          {header}
        </header>
      )}
      <div className="flex pt-[var(--header-height)]">
        {sidebar && (
          <aside
            className={cn(
              'fixed left-0 top-[var(--header-height)] bottom-0',
              'bg-[var(--color-bg-primary)] border-r border-[var(--color-border)]',
              'transition-all duration-[var(--transition-normal)] z-30',
              sidebarCollapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-[var(--sidebar-width)]'
            )}
          >
            <div className="h-full overflow-y-auto">{renderSidebar()}</div>
          </aside>
        )}
        <main
          className={cn(
            'flex-1 min-h-[calc(100vh-var(--header-height))]',
            'transition-all duration-[var(--transition-normal)]',
            sidebar &&
              (sidebarCollapsed
                ? 'ml-[var(--sidebar-collapsed-width)]'
                : 'ml-[var(--sidebar-width)]')
          )}
        >
          {children}
        </main>
      </div>
    </div>
  );
};
