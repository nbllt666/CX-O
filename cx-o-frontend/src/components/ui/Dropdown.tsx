import React, { useState, useRef, useEffect } from 'react';
import { cn } from '../../lib/utils';

export interface DropdownProps {
  trigger: React.ReactNode;
  children: React.ReactNode;
  align?: 'left' | 'right';
}

export const Dropdown: React.FC<DropdownProps> = ({ trigger, children, align = 'left' }) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div ref={dropdownRef} className="relative inline-block">
      <div onClick={() => setIsOpen(!isOpen)}>{trigger}</div>
      {isOpen && (
        <div
          className={cn(
            'absolute top-full mt-1 min-w-[160px]',
            'bg-[var(--color-bg-primary)] rounded-[var(--radius-lg)]',
            'border border-[var(--color-border)] shadow-[var(--shadow-lg)]',
            'py-1 z-50 animate-scale-in',
            align === 'right' ? 'right-0' : 'left-0'
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
};

export const DropdownItem: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & { icon?: React.ReactNode; danger?: boolean }
> = ({ className, icon, danger, children, ...props }) => (
  <button
    className={cn(
      'w-full px-4 py-2 text-sm text-left flex items-center gap-2',
      'hover:bg-[var(--color-bg-hover)] transition-colors',
      danger && 'text-[var(--color-error)]',
      className
    )}
    {...props}
  >
    {icon}
    {children}
  </button>
);

export const DropdownDivider: React.FC = () => (
  <div className="my-1 border-t border-[var(--color-border)]" />
);
