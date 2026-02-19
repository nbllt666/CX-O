import React from 'react';
import { cn } from '../../lib/utils';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  hoverable?: boolean;
  selected?: boolean;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, hoverable, selected, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          'bg-[var(--color-bg-primary)] rounded-[var(--radius-lg)]',
          'border border-[var(--color-border)]',
          'shadow-[var(--shadow-sm)]',
          'transition-all duration-[var(--transition-fast)]',
          hoverable &&
            'hover:shadow-[var(--shadow-md)] hover:border-[var(--color-border-hover)] cursor-pointer',
          selected && 'border-[var(--color-accent)] ring-2 ring-[var(--color-accent-light)]',
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);

Card.displayName = 'Card';

export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...props
}) => (
  <div className={cn('px-4 py-3 border-b border-[var(--color-border)]', className)} {...props}>
    {children}
  </div>
);

export const CardBody: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...props
}) => (
  <div className={cn('px-4 py-4', className)} {...props}>
    {children}
  </div>
);

export const CardFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...props
}) => (
  <div
    className={cn(
      'px-4 py-3 border-t border-[var(--color-border)] bg-[var(--color-bg-secondary)] rounded-b-[var(--radius-lg)]',
      className
    )}
    {...props}
  >
    {children}
  </div>
);
