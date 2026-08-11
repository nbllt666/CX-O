/**
 * ui-v2 Card 适配组件（Liquid Glass 风格，适配 APP-Frontend 视觉体系）。
 *
 * 从 CX-O-Frontend ui-v2/card.tsx 移植，用 glass-panel 类 + APP token，
 * 移除 WebGL glass 层与 framer-motion variants 依赖，保持 API 兼容：
 * Card/CardHeader/CardBody/CardFooter。
 */
import React from 'react';
import { cn } from '@/lib/utils';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 是否启用 hover 交互态 */
  hoverable?: boolean;
  /** 是否选中 */
  selected?: boolean;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, hoverable = false, selected = false, children, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn(
        'glass-panel overflow-hidden',
        'text-[var(--text-primary)]',
        selected && 'border-[var(--color-accent)] ring-2 ring-[var(--color-accent)]',
        hoverable && 'transition-all hover:-translate-y-0.5 hover:shadow-lg',
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
});

Card.displayName = 'Card';

export const CardHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...props
}) => (
  <div className={cn('px-4 py-3 border-b border-[var(--glass-border)]', className)} {...props}>
    {children}
  </div>
);
CardHeader.displayName = 'CardHeader';

export const CardBody: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...props
}) => (
  <div className={cn('px-4 py-4', className)} {...props}>
    {children}
  </div>
);
CardBody.displayName = 'CardBody';

export const CardFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...props
}) => (
  <div className={cn('px-4 py-3 border-t border-[var(--glass-border)]', className)} {...props}>
    {children}
  </div>
);
CardFooter.displayName = 'CardFooter';