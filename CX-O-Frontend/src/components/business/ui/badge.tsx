/**
 * @file badge.tsx — Badge / Tag 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\badge.tsx
 * 原组件: src/components/ui/Badge.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留旧 Badge 全部 7 种 variant（default/primary/secondary/success/warning/error/info）
 *   - 保留旧 Tag 组件（可移除标签）
 *   - 注入 Liquid Glass + data-glass（buildGlassDataAttributes）
 *   - 注入 motion variants（getComponentMotionVariants，snappy spring）
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

export type BadgeVariant =
  | 'default'
  | 'primary'
  | 'secondary'
  | 'success'
  | 'warning'
  | 'error'
  | 'info';

type BadgeSize = 'sm' | 'md';

interface BadgeProps
  extends Omit<
    React.HTMLAttributes<HTMLSpanElement>,
    'onDrag' | 'onDragEnd' | 'onAnimationStart' | 'onDragStart' | 'onDragOver' | 'onDragEnter' | 'onDragLeave' | 'onDrop'
  > {
  variant?: BadgeVariant;
  size?: BadgeSize;
  icon?: React.ReactNode;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]',
  primary: 'bg-[var(--color-accent-light)] text-[var(--color-accent)]',
  secondary:
    'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] border border-[var(--color-border)]',
  success: 'bg-[var(--color-success-light)] text-[var(--color-success)]',
  warning: 'bg-[var(--color-warning-light)] text-[var(--color-warning)]',
  error: 'bg-[var(--color-error-light)] text-[var(--color-error)]',
  info: 'bg-[var(--color-info-light)] text-[var(--color-info)]',
};

const sizeStyles: Record<BadgeSize, string> = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-sm',
};

// 入场 motion variants（基于模块6 getComponentMotionVariants 工厂，snappy spring）
const badgeVariants: Variants = getComponentMotionVariants({
  componentName: 'Button',
  springKey: 'snappy',
});

/**
 * Badge 业务组件（重组版）。
 *
 * 业务逻辑保留: 7 种 variant + 2 种 size + icon 全部原样保留。
 * UI 层重组: 挂载 data-glass 属性，注入 motion variants。
 */
export function Badge({
  className,
  variant = 'default',
  size = 'sm',
  icon,
  children,
  ...props
}: BadgeProps) {
  const glassAttributes = buildGlassDataAttributes(true, 4);

  return (
    <motion.span
      className={cn(
        'inline-flex items-center gap-1 font-medium rounded-[var(--radius-full)]',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      variants={badgeVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
      {...props}
    >
      {icon}
      {children}
    </motion.span>
  );
}

interface TagProps {
  children: React.ReactNode;
  onRemove?: () => void;
  className?: string;
}

/**
 * Tag 业务组件（重组版）。
 *
 * 业务逻辑保留: 可移除标签逻辑原样保留。
 * UI 层重组: 挂载 data-glass 属性，注入 motion variants。
 */
export function Tag({ children, onRemove, className }: TagProps) {
  const glassAttributes = buildGlassDataAttributes(true, 4);

  return (
    <motion.span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 text-xs',
        'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]',
        'rounded-[var(--radius-sm)]',
        className,
      )}
      variants={badgeVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
      {children}
      {onRemove && (
        <button
          onClick={onRemove}
          className="ml-1 hover:text-[var(--color-text-primary)] transition-colors"
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      )}
    </motion.span>
  );
}
