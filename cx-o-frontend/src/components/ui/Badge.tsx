import React from 'react';
import { cn } from '../../lib/utils';

type BadgeVariant = 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info';
type BadgeSize = 'sm' | 'md';

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
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
      'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]',
      'rounded-[var(--radius-sm)]',
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
