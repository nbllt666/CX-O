/**
 * @file header.tsx — Header 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组布局类（layout 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\layout\header.tsx
 * 原组件: src/components/layout/Header.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（Logo / title / 页面插槽 / 主题切换 / 记忆Agent入口 / 爱发电 / 桌宠模式 不变）
 *   - UI 层换用模块6 ui-v2 Button（icon 按钮换 ghost variant）
 *   - 注入 Liquid Glass + data-glass（header 容器挂载属性）
 *   - motion variants 处理 header 进场动画
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 仅 import app 级共享基础设施（store / router）
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { useThemeStore } from '@/store/themeStore';
import { Button } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

// Check if running in Electron
const isElectron = !!(window as unknown as { electronAPI?: unknown }).electronAPI;

interface HeaderProps {
  title?: string;
  actions?: React.ReactNode;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const headerVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'gentle',
});

// Logo 组件
const Logo: React.FC = () => (
  <div className="flex items-center">
    <div className="flex flex-col">
      <span className="text-base font-bold text-[var(--color-text-primary)] leading-tight">
        CX-O
      </span>
      <span className="text-[10px] text-[var(--color-text-tertiary)] leading-tight">
        晨曦长记忆Agent系统
      </span>
    </div>
  </div>
);

/**
 * Header 业务组件（重组版）。
 *
 * 业务逻辑保留: Logo / title / 页面插槽 / 主题切换 / 记忆Agent入口 / 爱发电 / 桌宠模式 全部原样保留。
 * UI 层重组: icon 按钮换用 ui-v2 Button（ghost variant），容器挂载 data-glass，注入 motion variants。
 */
export function Header({ title, actions }: HeaderProps) {
  const { theme, toggleTheme } = useThemeStore();
  const navigate = useNavigate();
  const glassAttributes = buildGlassDataAttributes(true, 2);

  return (
    <motion.div
      className="h-full px-4 flex items-center justify-between"
      variants={headerVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      <div className="flex items-center gap-4">
        {!title && <Logo />}
        {title && (
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">{title}</h1>
        )}
      </div>

      {/* 页面级内容插槽 - 由具体页面通过 Portal 注入标题和按钮 */}
      <div id="header-page-slot" className="flex items-center justify-between flex-1 px-4 min-w-0 gap-4" />

      <div className="flex items-center gap-2">
        {actions}

        {/* 记忆管理Agent入口 */}
        <Button
          variant="ghost"
          size="sm"
          className="p-2"
          title="记忆管理Agent"
          onClick={() => navigate('/memory-agent')}
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
            />
          </svg>
        </Button>

        {/* 爱发电支持按钮 */}
        <a
          href="https://afdian.com/a/nbllt666"
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            'p-2 rounded-[var(--radius-md)]',
            'text-red-500 hover:bg-red-50 dark:hover:bg-red-950',
            'transition-colors duration-[var(--transition-fast)]',
          )}
          title="支持开发者"
        >
          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
          </svg>
        </a>

        {/* 桌宠模式按钮 - 仅在 Electron 环境显示 */}
        {isElectron && (
          <Button
            variant="ghost"
            size="sm"
            className="p-2"
            title="桌宠模式"
            onClick={() => {
              const electronAPI = (window as unknown as { electronAPI?: { openPetWindow: () => void } }).electronAPI;
              if (electronAPI?.openPetWindow) {
                electronAPI.openPetWindow();
              }
            }}
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
          </Button>
        )}

        <Button
          variant="ghost"
          size="sm"
          className="p-2"
          title={theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
          onClick={toggleTheme}
        >
          {theme === 'dark' ? (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
              />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
              />
            </svg>
          )}
        </Button>
      </div>
    </motion.div>
  );
}
