/**
 * ui-v2 Input 适配组件（Liquid Glass 风格，适配 APP-Frontend 视觉体系）。
 *
 * 从 CX-O-Frontend ui-v2/input.tsx 移植，用 APP token（--glass-border / --color-accent），
 * 移除 WebGL glass 层与 framer-motion variants 依赖，保持 API 兼容：
 * Input（label/error/icon/suffix）+ Textarea。
 */
import React from 'react';
import { cn } from '@/lib/utils';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** 标签文本（可选，渲染在 input 上方） */
  label?: string;
  /** 错误信息（可选） */
  error?: string;
  /** 前置图标（可选） */
  icon?: React.ReactNode;
  /** 后置图标/后缀（可选） */
  suffix?: React.ReactNode;
}

const inputBase =
  'w-full px-3 py-2 text-sm rounded-[var(--radius-lg)] bg-[rgba(255,255,255,0.06)] text-[var(--text-primary)] border border-[var(--glass-border)] placeholder:text-[var(--text-secondary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed';

export const Input = React.forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, label, error, icon, suffix, type = 'text', ...props },
  ref,
) {
  return (
    <div className="w-full">
      {label && (
        <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">
          {label}
        </label>
      )}
      <div className="relative">
        {icon && (
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] pointer-events-none">
            {icon}
          </div>
        )}
        <input
          ref={ref}
          type={type}
          className={cn(inputBase, Boolean(icon) && 'pl-10', Boolean(suffix) && 'pr-10', className)}
          {...props}
        />
        {suffix && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)] pointer-events-none">
            {suffix}
          </div>
        )}
      </div>
      {error && <p className="mt-1.5 text-sm text-red-500">{error}</p>}
    </div>
  );
});
Input.displayName = 'Input';

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  /** 标签文本（可选） */
  label?: string;
  /** 错误信息（可选） */
  error?: string;
}

export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, label, error, ...props },
  ref,
) {
  return (
    <div className="w-full">
      {label && (
        <label className="block text-sm font-medium text-[var(--text-secondary)] mb-1.5">
          {label}
        </label>
      )}
      <textarea
        ref={ref}
        className={cn(inputBase, 'resize-none min-h-[100px]', className)}
        {...props}
      />
      {error && <p className="mt-1.5 text-sm text-red-500">{error}</p>}
    </div>
  );
});
Textarea.displayName = 'Textarea';