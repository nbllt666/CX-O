/**
 * @file skeleton.tsx — Skeleton / SkeletonText / SkeletonCard 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\skeleton.tsx
 * 原组件: src/components/ui/Skeleton.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（variant/width/height/SkeletonText/SkeletonCard 不变）
 *   - 注入 Liquid Glass + data-glass（skeleton 容器挂载属性）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React from 'react';
import { cn } from '@/lib/utils';
import { buildGlassDataAttributes } from '@/components/ui-v2';

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
}

/**
 * Skeleton 业务组件（重组版）。
 *
 * 业务逻辑保留: variant / width / height / shimmer 动画 全部原样保留。
 * UI 层重组: 容器挂载 data-glass 属性。
 */
export function Skeleton({
  className,
  variant = 'text',
  width,
  height,
}: SkeletonProps) {
  const glassAttributes = buildGlassDataAttributes(true, 4);

  const variantStyles = {
    text: 'rounded-[var(--radius-sm)]',
    circular: 'rounded-full',
    rectangular: 'rounded-[var(--radius-md)]',
  };

  return (
    <div
      className={cn(
        'animate-shimmer relative overflow-hidden bg-[var(--color-bg-tertiary)]',
        'before:absolute before:inset-0 before:bg-[var(--color-bg-tertiary)]',
        variantStyles[variant],
        className,
      )}
      style={{
        width,
        height,
        backgroundImage:
          'linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent)',
        backgroundSize: '200% 100%',
      }}
      {...glassAttributes}
    />
  );
}

export const SkeletonText: React.FC<{ lines?: number; className?: string }> = ({
  lines = 3,
  className,
}) => (
  <div className={cn('space-y-2', className)}>
    {Array.from({ length: lines }).map((_, i) => (
      <Skeleton key={i} variant="text" height={16} width={i === lines - 1 ? '60%' : '100%'} />
    ))}
  </div>
);

export const SkeletonCard: React.FC<{ className?: string }> = ({ className }) => {
  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <div
      className={cn(
        'p-4 bg-[var(--color-bg-primary)] rounded-[var(--radius-lg)] border border-[var(--color-border)]',
        className,
      )}
      {...glassAttributes}
    >
      <div className="flex items-center gap-3 mb-4">
        <Skeleton variant="circular" width={40} height={40} />
        <div className="flex-1">
          <Skeleton variant="text" height={16} width="40%" />
          <Skeleton variant="text" height={12} width="60%" className="mt-1" />
        </div>
      </div>
      <SkeletonText lines={3} />
    </div>
  );
};
