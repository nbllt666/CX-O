/**
 * @file modal.tsx — Modal 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\modal.tsx
 * 原组件: src/components/ui/Modal.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（isOpen/onClose/title/size/children/footer/escape/overlay 全部不变）
 *   - 注入 Liquid Glass + data-glass（modal 容器挂载属性）
 *   - motion variants 换用模块6 getComponentMotionVariants 工厂（Dialog gentle spring）
 *   - 关闭按钮换用 ui-v2 Button（ghost variant）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React, { useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui-v2';
import {
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  children: React.ReactNode;
  footer?: React.ReactNode;
  closeOnOverlay?: boolean;
  closeOnEscape?: boolean;
}

const sizeStyles = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
};

// overlay 渐入渐出
const overlayVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
};

// modal 面板入场/退场（基于模块6 getComponentMotionVariants 工厂，gentle spring）
const modalVariants: Variants = getComponentMotionVariants({
  componentName: 'Dialog',
  springKey: 'gentle',
});

/**
 * Modal 业务组件（重组版）。
 *
 * 业务逻辑保留: isOpen / onClose / title / size / children / footer / closeOnOverlay / closeOnEscape
 *   + escape 键监听 + body overflow 锁定 全部原样保留。
 * UI 层重组: modal 容器挂载 data-glass，motion variants 换用模块6 工厂，关闭按钮换用 ui-v2 Button。
 */
export function Modal({
  isOpen,
  onClose,
  title,
  size = 'md',
  children,
  footer,
  closeOnOverlay = true,
  closeOnEscape = true,
}: ModalProps) {
  const handleEscape = useCallback(
    (e: KeyboardEvent) => {
      if (closeOnEscape && e.key === 'Escape') {
        onClose();
      }
    },
    [closeOnEscape, onClose],
  );

  useEffect(() => {
    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [isOpen, handleEscape]);

  const glassAttributes = buildGlassDataAttributes(true, 2);

  return createPortal(
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center"
          variants={overlayVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
        >
          <motion.div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={closeOnOverlay ? onClose : undefined}
            variants={overlayVariants}
            initial="hidden"
            animate="visible"
            exit="exit"
            transition={{ duration: 0.2 }}
          />
          <motion.div
            className={cn(
              'relative w-full mx-4 bg-[var(--color-bg-primary)]',
              'rounded-[var(--radius-xl)] shadow-[var(--shadow-lg)]',
              sizeStyles[size],
            )}
            variants={modalVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            role="dialog"
            aria-modal="true"
            aria-labelledby={title ? 'modal-title' : undefined}
            {...glassAttributes}
          >
            {title && (
              <div className="px-6 py-4 border-b border-[var(--color-border)] flex items-center justify-between">
                <h2 id="modal-title" className="text-lg font-semibold text-[var(--color-text-primary)]">
                  {title}
                </h2>
                <Button
                  variant="ghost"
                  size="sm"
                  className="p-1"
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
            )}
            <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">{children}</div>
            {footer && (
              <div className="px-6 py-4 border-t border-[var(--color-border)] flex justify-end gap-3">
                {footer}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
