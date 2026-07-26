/**
 * @file drawer.tsx — Drawer 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\drawer.tsx
 * 原组件: src/components/ui/Drawer.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（isOpen/onClose/title/children/position/width 不变）
 *   - 注入 Liquid Glass + data-glass（drawer 面板挂载属性）
 *   - CSS transition 换用 Framer Motion + getComponentMotionVariants（slide + fade）
 *   - 关闭按钮换用 ui-v2 Button（ghost variant）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

export interface DrawerProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  position?: 'left' | 'right';
  width?: string;
}

// drawer 面板入场/退场（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const drawerVariants: Variants = getComponentMotionVariants({
  componentName: 'Dialog',
  springKey: 'gentle',
});

// overlay 渐入渐出
const overlayVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
};

/**
 * Drawer 业务组件（重组版）。
 *
 * 业务逻辑保留: isOpen / onClose / title / children / position / width 全部原样保留。
 * UI 层重组: CSS transition 换用 Framer Motion + motion variants，面板挂载 data-glass，关闭按钮换用 ui-v2 Button。
 */
export function Drawer({
  isOpen,
  onClose,
  title,
  children,
  position = 'right',
  width = '400px',
}: DrawerProps) {
  const glassAttributes = buildGlassDataAttributes(true, 2);

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            className="fixed inset-0 bg-black/50 z-40"
            variants={overlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            onClick={onClose}
          />
          <motion.div
            className={cn(
              'fixed top-0 bottom-0 z-50',
              'bg-[var(--color-bg-primary)] shadow-[var(--shadow-lg)]',
              position === 'right' ? 'right-0' : 'left-0',
            )}
            style={{ width }}
            variants={drawerVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            {...glassAttributes}
          >
            <div className="flex items-center justify-between p-4 border-b border-[var(--color-border)]">
              {title && (
                <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">{title}</h2>
              )}
              <Button
                variant="ghost"
                size="sm"
                className="p-2"
                onClick={onClose}
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </Button>
            </div>
            <div className="p-4 overflow-y-auto h-[calc(100%-60px)]">{children}</div>
          </motion.div>
        </>
      )}
    </AnimatePresence>,
    document.body,
  );
}
