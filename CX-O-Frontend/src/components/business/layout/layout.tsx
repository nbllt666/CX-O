/**
 * @file layout.tsx — Layout 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组布局类（layout 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\layout\layout.tsx
 * 原组件: src/components/layout/Layout.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（sidebar 渲染 / header 插槽 / 路由切换动画不变）
 *   - 注入 Liquid Glass 容器 + data-glass（header / aside / main 挂载 data-glass 属性）
 *   - motion variants 处理路由切换（替换内联 transition 为模块6 variants 工厂）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 仅 import 第三方库 react-router-dom / framer-motion
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React, { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

interface SidebarProps {
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
}

interface LayoutProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode | ((props: SidebarProps) => React.ReactNode);
  header?: React.ReactNode;
}

// 路由切换 motion variants（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const routeVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'gentle',
});

/**
 * Layout 业务组件（重组版）。
 *
 * 业务逻辑保留: sidebar 折叠状态管理 / sidebar 函数式渲染 / header 插槽全部原样保留。
 * UI 层重组: header / aside / main 挂载 data-glass 属性，路由切换动画换用模块6 variants 工厂。
 */
export function Layout({ children, sidebar, header }: LayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const location = useLocation();

  const headerGlass = buildGlassDataAttributes(true, 2);
  const asideGlass = buildGlassDataAttributes(true, 2);
  const mainGlass = buildGlassDataAttributes(true, 3);

  const renderSidebar = () => {
    if (!sidebar) return null;
    if (typeof sidebar === 'function') {
      return sidebar({ collapsed: sidebarCollapsed, setCollapsed: setSidebarCollapsed });
    }
    return sidebar;
  };

  return (
    <div className="h-screen bg-[var(--color-bg-secondary)] overflow-hidden">
      {header && (
        <header
          className={cn(
            'fixed top-0 left-0 right-0 h-[var(--header-height)]',
            'bg-[var(--color-bg-primary)] border-b border-[var(--color-border)] z-40',
          )}
          {...headerGlass}
        >
          {header}
        </header>
      )}
      <div className="flex h-[calc(100vh-var(--header-height))] mt-[var(--header-height)]">
        {sidebar && (
          <aside
            className={cn(
              'fixed left-0 top-[var(--header-height)] bottom-0',
              'bg-[var(--color-bg-primary)] border-r border-[var(--color-border)]',
              'transition-all duration-[var(--transition-normal)] z-30',
              sidebarCollapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-[var(--sidebar-width)]',
            )}
            {...asideGlass}
          >
            <div className="h-full overflow-y-auto">{renderSidebar()}</div>
          </aside>
        )}
        <main
          className={cn(
            'flex-1 h-full',
            'transition-all duration-[var(--transition-normal)]',
            sidebar
              ? sidebarCollapsed
                ? 'ml-[var(--sidebar-collapsed-width)]'
                : 'ml-[var(--sidebar-width)]'
              : false,
          )}
          {...mainGlass}
        >
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              variants={routeVariants}
              initial="initial"
              animate="animate"
              exit="exit"
              className="h-full"
            >
              {children}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
