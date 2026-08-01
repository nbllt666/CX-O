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
          'glass-panel overflow-hidden',
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
  <div className={cn('px-4 py-3 border-b border-transparent', className)} {...props}>
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
      'px-4 py-3 border-t border-transparent bg-white/[0.02] rounded-b-[var(--glass-radius)]',
      className
    )}
    {...props}
  >
    {children}
  </div>
);
