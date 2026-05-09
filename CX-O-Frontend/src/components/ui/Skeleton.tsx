import React from 'react';
import { cn } from '../../lib/utils';

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  className,
  variant = 'text',
  width,
  height,
}) => {
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
        className
      )}
      style={{
        width,
        height,
        backgroundImage: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent)',
        backgroundSize: '200% 100%',
      }}
    />
  );
};

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

export const SkeletonCard: React.FC<{ className?: string }> = ({ className }) => (
  <div
    className={cn(
      'p-4 bg-[var(--color-bg-primary)] rounded-[var(--radius-lg)] border border-[var(--color-border)]',
      className
    )}
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
