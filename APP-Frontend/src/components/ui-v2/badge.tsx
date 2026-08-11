/**
 * ui-v2 Badge 适配组件（Liquid Glass 风格，适配 APP-Frontend 视觉体系）。
 *
 * 从 CX-O-Frontend ui-v2/badge.tsx 移植，改用 APP-Frontend 的 --glass-* / --color-* token，
 * 移除 WebGL glass 层与 framer-motion variants 依赖，保持 API 兼容：
 * variant: default/secondary/success/warning/error/anime；size: sm/md。
 */
import React from 'react';
import { cn } from '@/lib/utils';

export type BadgeVariant =
  | 'default'
  | 'secondary'
  | 'success'
  | 'warning'
  | 'error'
  | 'anime';

export type BadgeSize = 'sm' | 'md';

export interface BadgeProps {
  /** variant（default/secondary/success/warning/error/anime，默认 default） */
  readonly variant?: BadgeVariant;
  /** size（sm/md，默认 md） */
  readonly size?: BadgeSize;
  /** 子元素（徽章内容） */
  readonly children?: React.ReactNode;
  /** 自定义 className */
  readonly className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-[rgba(255,255,255,0.08)] text-[var(--text-secondary)]',
  secondary: 'bg-[rgba(255,255,255,0.05)] text-[var(--text-secondary)]',
  success: 'bg-emerald-500/15 text-emerald-500',
  warning: 'bg-amber-500/15 text-amber-500',
  error: 'bg-red-500/15 text-red-500',
  anime: 'bg-[rgba(255,183,225,0.18)] text-[var(--color-primary)]',
};

const sizeStyles: Record<BadgeSize, string> = {
  sm: 'px-2 py-0.5 text-xs rounded-[var(--radius-sm)]',
  md: 'px-2.5 py-1 text-sm rounded-[var(--radius-md)]',
};

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { className, variant = 'default', size = 'md', children, ...props },
  ref,
) {
  return (
    <span
      ref={ref}
      data-badge-variant={variant}
      className={cn(
        'inline-flex items-center justify-center font-medium whitespace-nowrap select-none',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
});

Badge.displayName = 'Badge';