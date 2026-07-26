/**
 * @file toast.tsx — ToastProvider / useToast 业务组件重组（模块7 ui 子目录）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组（ui 子目录）
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\ui\toast.tsx
 * 原组件: src/components/ui/Toast.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（ToastProvider/useToast/ToastContext/ToastItem/toastIcons 不变）
 *   - 注入 Liquid Glass + data-glass（toast item 容器挂载属性）
 *   - 保留 toast 专属 motion variants（从右上角滑入 + spring 弹性，行为动画不变）
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块3 motion / 模块4 glass / 模块6 ui-v2 公开产出
 *   - 禁止 import 模块8/9 内部实现
 * ============================================================================
 */

import React, { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { cn } from '@/lib/utils';
import { buildGlassDataAttributes } from '@/components/ui-v2';

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number;
}

interface ToastContextValue {
  toasts: Toast[];
  addToast: (type: ToastType, message: string, duration?: number) => void;
  removeToast: (id: string) => void;
}

const ToastContext = React.createContext<ToastContextValue | null>(null);

export const useToast = () => {
  const context = React.useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a ToastProvider');
  }
  return context;
};

const toastIcons = {
  success: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
    </svg>
  ),
  error: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  ),
  warning: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
      />
    </svg>
  ),
  info: (
    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  ),
};

const toastStyles = {
  success:
    'bg-[var(--color-success-light)] text-[var(--color-success)] border-[var(--color-success)]',
  error: 'bg-[var(--color-error-light)] text-[var(--color-error)] border-[var(--color-error)]',
  warning:
    'bg-[var(--color-warning-light)] text-[var(--color-warning)] border-[var(--color-warning)]',
  info: 'bg-[var(--color-info-light)] text-[var(--color-info)] border-[var(--color-info)]',
};

// toast 专属 motion variants（从右上角滑入 + spring 弹性）
const toastVariants = {
  initial: {
    opacity: 0,
    y: -100,
    scale: 0.95,
    x: 50,
  },
  animate: {
    opacity: 1,
    y: 0,
    scale: 1,
    x: 0,
    transition: {
      type: 'spring',
      damping: 25,
      stiffness: 300,
      mass: 0.8,
    },
  },
  exit: {
    opacity: 0,
    y: -20,
    scale: 0.95,
    x: 30,
    transition: {
      duration: 0.2,
      ease: [0.4, 0, 0.2, 1],
    },
  },
};

const ToastItem: React.FC<{ toast: Toast; onClose: () => void }> = ({ toast, onClose }) => {
  useEffect(() => {
    if (toast.duration) {
      const timer = setTimeout(onClose, toast.duration);
      return () => clearTimeout(timer);
    }
  }, [toast.duration, onClose]);

  const glassAttributes = buildGlassDataAttributes(true, 2);

  return (
    <motion.div
      layout
      variants={toastVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      className={cn(
        'flex items-center gap-3 px-4 py-3 rounded-[var(--radius-lg)]',
        'border shadow-[var(--shadow-md)]',
        toastStyles[toast.type],
        'cursor-pointer',
      )}
      onClick={onClose}
      {...glassAttributes}
    >
      {toastIcons[toast.type]}
      <span className="flex-1 text-sm font-medium">{toast.message}</span>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onClose();
        }}
        className="p-1 rounded-[var(--radius-sm)] hover:bg-black/10 transition-colors"
      >
        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M6 18L18 6M6 6l12 12"
          />
        </svg>
      </button>
    </motion.div>
  );
};

/**
 * ToastProvider 业务组件（重组版）。
 *
 * 业务逻辑保留: toasts state / addToast / removeToast / ToastContext / createPortal 全部原样保留。
 * UI 层重组: toast item 挂载 data-glass 属性，保留专属 motion variants。
 */
export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = (type: ToastType, message: string, duration = 5000) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, type, message, duration }]);
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
      {createPortal(
        <div className="fixed top-4 right-4 z-[100] flex flex-col-reverse gap-2 max-w-sm pointer-events-none">
          <AnimatePresence mode="popLayout">
            {toasts.map((toast) => (
              <div key={toast.id} className="pointer-events-auto">
                <ToastItem toast={toast} onClose={() => removeToast(toast.id)} />
              </div>
            ))}
          </AnimatePresence>
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
};
