/**
 * ui-v2 Button 适配组件（Liquid Glass 风格，适配 APP-Frontend 视觉体系）。
 *
 * 从 CX-O-Frontend ui-v2/button.tsx 移植，改用 APP-Frontend 的 --glass-* / --color-* token，
 * 移除 WebGL glass 层与 framer-motion variants 依赖，保持 API 兼容：
 * variant: primary/secondary/ghost/danger；size: sm/md/lg；loading/icon。
 */
import React from 'react';
import { cn } from '@/lib/utils';

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** variant（primary/secondary/ghost/danger，默认 primary） */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  /** size（sm/md/lg，默认 md） */
  size?: 'sm' | 'md' | 'lg';
  /** 加载状态（显示 spinner，禁用按钮） */
  loading?: boolean;
  /** 前置图标 */
  icon?: React.ReactNode;
}

const variantStyles: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary: 'bg-[var(--color-primary)] text-[var(--color-primary-foreground)] hover:opacity-90',
  secondary:
    'bg-[rgba(255,255,255,0.06)] text-[var(--text-primary)] border border-[var(--glass-border)] hover:bg-[rgba(255,255,255,0.1)]',
  ghost:
    'text-[var(--text-secondary)] hover:bg-[rgba(255,255,255,0.08)] hover:text-[var(--text-primary)]',
  danger: 'bg-red-500/85 text-white hover:opacity-90',
};

const sizeStyles: Record<NonNullable<ButtonProps['size']>, string> = {
  sm: 'px-3 py-1.5 text-sm rounded-[var(--radius-sm)]',
  md: 'px-4 py-2 text-sm rounded-[var(--radius-lg)]',
  lg: 'px-6 py-3 text-base rounded-[var(--radius-lg)]',
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = 'primary', size = 'md', loading = false, icon, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'relative inline-flex items-center justify-center gap-2 font-medium overflow-hidden',
        'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-1',
        'disabled:opacity-50 disabled:cursor-not-allowed transition-all',
        variantStyles[variant],
        sizeStyles[size],
        className,
      )}
      {...props}
    >
      {loading ? (
        <svg
          className="animate-spin h-4 w-4"
          viewBox="0 0 24 24"
          style={{ transformOrigin: 'center' }}
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeDasharray="60 20" />
        </svg>
      ) : icon ? (
        icon
      ) : null}
      {children}
    </button>
  );
});

Button.displayName = 'Button';