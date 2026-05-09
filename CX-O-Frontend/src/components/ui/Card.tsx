import React from 'react';
import { motion } from 'framer-motion';
import { cn } from '../../lib/utils';

export interface CardProps extends Omit<React.HTMLAttributes<HTMLDivElement>, 'onDrag' | 'onDragEnd' | 'onAnimationStart' | 'onDragStart' | 'onDragOver' | 'onDragEnter' | 'onDragLeave' | 'onDrop'> {
  hoverable?: boolean;
  selected?: boolean;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, hoverable, selected, children, ...props }, ref) => {
    return (
      <motion.div
        ref={ref}
        className={cn(
          'bg-[var(--color-bg-primary)] rounded-[var(--radius-lg)]',
          'border border-[var(--color-border)]',
          'shadow-[var(--shadow-sm)]',
          selected && 'border-[var(--color-accent)] ring-2 ring-[var(--color-accent-light)]',
          className
        )}
        {...(hoverable && {
          whileHover: {
            y: -4,
            boxShadow: 'var(--shadow-lg)',
            borderColor: 'var(--color-accent)',
            cursor: 'pointer',
          },
          transition: { duration: 0.2, ease: [0.25, 0.46, 0.45, 0.94] },
        })}
        {...props}
      >
        {children}
      </motion.div>
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
