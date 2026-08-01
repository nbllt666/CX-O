import React from 'react';
import { cn } from '../../lib/utils';

export type BadgeVariant = 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info';
type BadgeSize = 'sm' | 'md';

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  size?: BadgeSize;
  icon?: React.ReactNode;
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-white/[0.08] text-[var(--color-text-secondary)] border border-transparent',
  primary: 'bg-[var(--color-accent)]/20 text-[var(--color-accent)] border border-[var(--color-accent)]/30',
  secondary:
    'bg-white/[0.06] text-[var(--color-text-secondary)] border border-transparent',
  success: 'bg-[var(--color-success)]/20 text-[var(--color-success)] border border-[var(--color-success)]/30',
  warning: 'bg-[var(--color-warning)]/20 text-[var(--color-warning)] border border-[var(--color-warning)]/30',
  error: 'bg-[var(--color-error)]/20 text-[var(--color-error)] border border-[var(--color-error)]/30',
  info: 'bg-[var(--color-info)]/20 text-[var(--color-info)] border border-[var(--color-info)]/30',
};

const sizeStyles: Record<BadgeSize, string> = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-sm',
};

export const Badge: React.FC<BadgeProps> = ({
  className,
  variant = 'default',
  size = 'sm',
  icon,
  children,
  ...props
}) => (
  <span
    className={cn(
      'inline-flex items-center gap-1 font-medium rounded-[var(--radius-full)]',
      variantStyles[variant],
      sizeStyles[size],
      className
    )}
    {...props}
  >
    {icon}
    {children}
  </span>
);

interface TagProps {
  children: React.ReactNode;
  onRemove?: () => void;
  className?: string;
}

export const Tag: React.FC<TagProps> = ({ children, onRemove, className }) => (
  <span
    className={cn(
      'inline-flex items-center gap-1 px-2 py-0.5 text-xs',
      'bg-white/[0.06] text-[var(--color-text-secondary)]',
      'border border-transparent',
      'rounded-[var(--radius-md)]',
      className
    )}
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
  </span>
);
