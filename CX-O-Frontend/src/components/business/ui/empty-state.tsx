/**
 * @file empty-state.tsx — EmptyState / EmptyStateIcon 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\empty-state.tsx
 * 原组件: src/components/ui/EmptyState.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（icon/title/description/action/EmptyStateIcon 不变）
 *   - 注入 Liquid Glass + data-glass（容器挂载属性）
 *   - 注入 motion variants（gentle spring 进场动画）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const emptyStateVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'gentle',
});

/**
 * EmptyState 业务组件（重组版）。
 *
 * 业务逻辑保留: icon / title / description / action 全部原样保留。
 * UI 层重组: 容器挂载 data-glass，注入 motion variants。
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <motion.div
      className={cn(
        'flex flex-col items-center justify-center py-12 px-4 text-center',
        className,
      )}
      variants={emptyStateVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      {icon && <div className="mb-4 text-[var(--color-text-tertiary)]">{icon}</div>}
      <h3 className="text-lg font-medium text-[var(--color-text-primary)] mb-2">{title}</h3>
      {description && (
        <p className="text-sm text-[var(--color-text-secondary)] mb-4 max-w-sm">
          {description}
        </p>
      )}
      {action}
    </motion.div>
  );
}

export const EmptyStateIcon: React.FC<{ type: 'search' | 'folder' | 'chat' | 'user' }> = ({
  type,
}) => {
  const icons = {
    search: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
        />
      </svg>
    ),
    folder: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
        />
      </svg>
    ),
    chat: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
        />
      </svg>
    ),
    user: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
        />
      </svg>
    ),
  };
  return icons[type];
};
