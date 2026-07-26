/**
 * @file dropdown.tsx — Dropdown / DropdownItem / DropdownDivider 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\dropdown.tsx
 * 原组件: src/components/ui/Dropdown.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（trigger/children/align/点击外部关闭/DropdownItem/DropdownDivider 不变）
 *   - 注入 Liquid Glass + data-glass（dropdown 面板挂载属性）
 *   - CSS animate-scale-in 换用 Framer Motion + getComponentMotionVariants（snappy spring）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

export interface DropdownProps {
  trigger: React.ReactNode;
  children: React.ReactNode;
  align?: 'left' | 'right';
}

// dropdown 面板入场/退场（基于模块6 getComponentMotionVariants 工厂，snappy spring）
const dropdownVariants: Variants = getComponentMotionVariants({
  componentName: 'Button',
  springKey: 'snappy',
});

/**
 * Dropdown 业务组件（重组版）。
 *
 * 业务逻辑保留: trigger / children / align / 点击外部关闭 全部原样保留。
 * UI 层重组: CSS animate-scale-in 换用 Framer Motion + motion variants，面板挂载 data-glass。
 */
export function Dropdown({ trigger, children, align = 'left' }: DropdownProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const glassAttributes = buildGlassDataAttributes(true, 3);

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
      <AnimatePresence>
        {isOpen && (
          <motion.div
            className={cn(
              'absolute top-full mt-1 min-w-[160px]',
              'bg-[var(--color-bg-primary)] rounded-[var(--radius-lg)]',
              'border border-[var(--color-border)] shadow-[var(--shadow-lg)]',
              'py-1 z-50',
              align === 'right' ? 'right-0' : 'left-0',
            )}
            variants={dropdownVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            {...glassAttributes}
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export const DropdownItem: React.FC<
  React.ButtonHTMLAttributes<HTMLButtonElement> & { icon?: React.ReactNode; danger?: boolean }
> = ({ className, icon, danger, children, ...props }) => (
  <button
    className={cn(
      'w-full px-4 py-2 text-sm text-left flex items-center gap-2',
      'hover:bg-[var(--color-bg-hover)] transition-colors',
      danger && 'text-[var(--color-error)]',
      className,
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
