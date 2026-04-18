import React from 'react';
import { cn } from '../../lib/utils';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  icon?: React.ReactNode;
  suffix?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, icon, suffix, type = 'text', ...props }, ref) => {
    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
            {label}
          </label>
        )}
        <div className="relative">
          {icon && (
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)]">
              {icon}
            </div>
          )}
          <input
            ref={ref}
            type={type}
            className={cn(
              'w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)]',
              'bg-[var(--color-bg-primary)] text-[var(--color-text-primary)]',
              'border border-[var(--color-border)]',
              'placeholder:text-[var(--color-text-tertiary)]',
              'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent',
              'transition-all duration-[var(--transition-fast)]',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              icon && 'pl-10',
              suffix && 'pr-10',
              error && 'border-[var(--color-error)] focus:ring-[var(--color-error)]',
              className
            )}
            {...props}
          />
          {suffix && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)]">
              {suffix}
            </div>
          )}
        </div>
        {error && <p className="mt-1.5 text-sm text-[var(--color-error)]">{error}</p>}
      </div>
    );
  }
);

Input.displayName = 'Input';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, label, error, ...props }, ref) => {
    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          className={cn(
            'w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)]',
            'bg-[var(--color-bg-primary)] text-[var(--color-text-primary)]',
            'border border-[var(--color-border)]',
            'placeholder:text-[var(--color-text-tertiary)]',
            'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent',
            'transition-all duration-[var(--transition-fast)]',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'resize-none min-h-[100px]',
            error && 'border-[var(--color-error)] focus:ring-[var(--color-error)]',
            className
          )}
          {...props}
        />
        {error && <p className="mt-1.5 text-sm text-[var(--color-error)]">{error}</p>}
      </div>
    );
  }
);

Textarea.displayName = 'Textarea';
