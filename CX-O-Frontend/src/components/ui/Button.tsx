import React, { useRef } from 'react';
import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';
import { cn } from '../../lib/utils';

export interface ButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onDrag' | 'onDragEnd' | 'onAnimationStart' | 'onDragStart' | 'onDragOver' | 'onDragEnter' | 'onDragLeave' | 'onDrop'> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: React.ReactNode;
}

const variantStyles = {
  primary:
    'bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] active:bg-[var(--color-accent-active)] shadow-lg shadow-[var(--color-accent)]/25',
  secondary:
    'bg-white/[0.04] text-[var(--color-text-primary)] hover:bg-white/[0.08] border border-white/[0.02]',
  ghost:
    'text-[var(--color-text-secondary)] hover:bg-white/[0.06] hover:text-[var(--color-text-primary)]',
  danger: 'bg-[var(--color-error)] text-white hover:opacity-90',
};

const sizeStyles = {
  sm: 'px-3 py-1.5 text-sm rounded-[var(--radius-md)]',
  md: 'px-4 py-2 text-sm rounded-[var(--radius-lg)]',
  lg: 'px-6 py-3 text-base rounded-[var(--radius-xl)]',
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant = 'primary', size = 'md', loading, icon, children, disabled, ...props },
    ref
  ) => {
    const buttonRef = useRef<HTMLButtonElement>(null);
    const mouseX = useMotionValue(0);
    const mouseY = useMotionValue(0);
    
    const rippleX = useSpring(useTransform(mouseX, (x) => x), { stiffness: 300, damping: 30 });
    const rippleY = useSpring(useTransform(mouseY, (y) => y), { stiffness: 300, damping: 30 });

    const handleMouseMove = (e: React.MouseEvent<HTMLButtonElement>) => {
      if (!buttonRef.current) return;
      const rect = buttonRef.current.getBoundingClientRect();
      mouseX.set(e.clientX - rect.left);
      mouseY.set(e.clientY - rect.top);
    };

    return (
      <motion.button
        ref={ref || buttonRef}
        className={cn(
          'relative inline-flex items-center justify-center gap-2 font-medium overflow-hidden',
          'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2',
          'disabled:opacity-50 disabled:cursor-not-allowed',
          variantStyles[variant],
          sizeStyles[size],
          className
        )}
        disabled={disabled || loading}
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
        onMouseMove={handleMouseMove}
        {...props}
      >
        <motion.div
          className="absolute inset-0 rounded-inherit pointer-events-none"
          style={{
            background: 'radial-gradient(circle at var(--ripple-x) var(--ripple-y), rgba(255,255,255,0.15) 0%, transparent 60%)',
            '--ripple-x': rippleX,
            '--ripple-y': rippleY,
          } as React.CSSProperties}
        />
        {loading ? (
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" style={{ transformOrigin: 'center' }}>
            <defs>
              <linearGradient id="spinner-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="currentColor" stopOpacity="0.3" />
                <stop offset="50%" stopColor="currentColor" stopOpacity="1" />
                <stop offset="100%" stopColor="currentColor" stopOpacity="0.3" />
              </linearGradient>
            </defs>
            <circle
              cx="12"
              cy="12"
              r="10"
              stroke="url(#spinner-gradient)"
              strokeWidth="4"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        ) : icon ? (
          icon
        ) : null}
        {children}
      </motion.button>
    );
  }
);

Button.displayName = 'Button';
