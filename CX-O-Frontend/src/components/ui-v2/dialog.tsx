/**
 * @file dialog.tsx — Dialog 组件（第1波基础组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\dialog.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Dialog + §DialogProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.dialog（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.gentle（Dialog 默认 spring，模态过渡）
 *   - merged.md §4.2 定制策略（fork 后注入 Liquid Glass 样式，不靠 props 传递）
 *
 * Liquid Glass 定制（I5 §Dialog docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 模态过渡使用 gentle spring（I3 springs.gentle）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - AnimatePresence 管理入场/出场（merged.md §4.2）
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion / react-dom
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: gentle（D5 §springs.gentle.useCase=modal-transition）
 * apple-design 对齐: damping=32 / stiffness=200 / mass=1（柔和模态过渡）
 * ============================================================================
 */

import React, { useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  injectGlassClassName,
  buildGlassDataAttributes,
  isValidGlassTier,
} from './inject-glass-style';
import {
  getComponentMotionVariants,
  getComponentSpringTransition,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// DialogProps（对应 I5 §DialogProps）
// =============================================================================

/**
 * Dialog 组件 props（对应 I5 §DialogProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 对应 shadcn Dialog 的 open/onOpenChange 模式。
 */
export interface DialogProps extends GlassComponentProps {
  /** 是否打开（受控模式） */
  open: boolean;
  /** 打开/关闭状态变化回调（受控模式） */
  onOpenChange?: (open: boolean) => void;
  /** 标题（可选，渲染在 Dialog 头部） */
  title?: string;
  /** 尺寸（sm/md/lg/xl） */
  size?: 'sm' | 'md' | 'lg' | 'xl';
  /** 子元素（Dialog 内容） */
  children?: React.ReactNode;
  /** 底部区域（可选，通常放操作按钮） */
  footer?: React.ReactNode;
  /** 点击 overlay 是否关闭（默认 true） */
  closeOnOverlay?: boolean;
  /** 按 ESC 键是否关闭（默认 true） */
  closeOnEscape?: boolean;
  /** 自定义 className（应用到 Dialog content） */
  className?: string;
}

// =============================================================================
// size 样式映射（通过 className 消费 token，不硬编码颜色）
// =============================================================================

/**
 * Dialog size 样式映射。
 */
const sizeStyles: Record<NonNullable<DialogProps['size']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
};

// =============================================================================
// Dialog 组件实现
// =============================================================================

/**
 * Dialog 组件（第1波基础组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Dialog: ``Dialog(props: DialogProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 模态过渡使用 gentle spring（I3 springs.gentle）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - AnimatePresence 管理入场/出场
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: gentle（D5 §springs.gentle.useCase=modal-transition）
 *
 * @param props Dialog 组件配置（含 open/onOpenChange + Liquid Glass 扩展字段）
 * @returns 渲染后的 Dialog（通过 createPortal 挂载到 document.body）
 */
export const Dialog: React.FC<DialogProps> = function Dialog({
  open,
  onOpenChange,
  title,
  size = 'md',
  children,
  footer,
  closeOnOverlay = true,
  closeOnEscape = true,
  className,
  dataGlass = true,
  glassTier,
  glassVariant,
  motionVariants,
}) {
  // 构建 data-glass + data-glass-tier 属性（由 WebGL 层接管渲染）
  const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
  const glassAttributes = buildGlassDataAttributes(dataGlass, validTier);

  // 获取 gentle spring 的 transition 参数（用于构建 overlay/content variants）
  // Dialog 默认使用 gentle spring（D5 §springs.gentle.useCase=modal-transition）
  const springTransition = getComponentSpringTransition(glassVariant ?? 'gentle');

  // 构建 overlay variants（opacity 变化，使用 gentle spring）
  // 若调用方提供 motionVariants 则直接使用，否则使用默认 overlay variants
  const overlayVariants: Variants =
    motionVariants ??
    ({
      initial: { opacity: 0 },
      animate: { opacity: 1, transition: springTransition },
      exit: { opacity: 0, transition: springTransition },
    } as Variants);

  // 构建 content variants（opacity + scale + y 变化，使用 gentle spring）
  // content variants 基于 getComponentMotionVariants 生成（含 apple-design 物理参数）
  const contentVariants: Variants =
    motionVariants ??
    getComponentMotionVariants({
      componentName: 'Dialog',
      springKey: glassVariant,
    });

  // ESC 键关闭（closeOnEscape=true 时启用）
  const handleEscape = useCallback(
    (e: KeyboardEvent) => {
      if (closeOnEscape && e.key === 'Escape' && onOpenChange) {
        onOpenChange(false);
      }
    },
    [closeOnEscape, onOpenChange],
  );

  // 注册/注销 ESC 键监听 + 锁定 body 滚动
  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleEscape);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [open, handleEscape]);

  // 点击 overlay 关闭（closeOnOverlay=true 时启用）
  const handleOverlayClick = useCallback(() => {
    if (closeOnOverlay && onOpenChange) {
      onOpenChange(false);
    }
  }, [closeOnOverlay, onOpenChange]);

  // 构建 content 基础 className（通过 className 消费 token，不硬编码颜色）
  const contentBaseClassName = cn(
    'relative w-full mx-4',
    'bg-[var(--dialog-bg)]',
    'rounded-[var(--dialog-radius)] shadow-[var(--dialog-shadow)]',
    'border border-[var(--dialog-border)]',
    'text-[var(--dialog-text)]',
    'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
    sizeStyles[size],
    className,
  );

  // 注入 glass 样式类（仅当调用方提供 glassTier 时注入 CSS 降级样式）
  const composedContentClassName = validTier
    ? injectGlassClassName(contentBaseClassName, validTier)
    : contentBaseClassName;

  // SSR 安全：如果 document 不存在则返回 null
  if (typeof document === 'undefined') return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center"
          // overlay 不挂载 data-glass 属性（overlay 是纯遮罩层，不需要玻璃渲染）
        >
          {/* Overlay: 半透明背景 + backdrop-blur */}
          <motion.div
            className="absolute inset-0 bg-[var(--dialog-overlay)] backdrop-blur-[var(--dialog-backdrop-blur)]"
            variants={overlayVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            onClick={handleOverlayClick}
            aria-hidden="true"
          />
          {/* Content: Dialog 主体（挂载 data-glass 属性，由 WebGL 层接管渲染） */}
          <motion.div
            className={composedContentClassName}
            // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
            data-glass={glassAttributes['data-glass'] ?? undefined}
            data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
            variants={contentVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            role="dialog"
            aria-modal="true"
            aria-labelledby={title ? 'dialog-title' : undefined}
          >
            {/* Header（标题 + 关闭按钮） */}
            {title && (
              <div className="px-6 py-4 border-b border-[var(--dialog-border)] flex items-center justify-between">
                <h2
                  id="dialog-title"
                  className="text-lg font-semibold text-[var(--dialog-text)]"
                >
                  {title}
                </h2>
                {onOpenChange && (
                  <button
                    type="button"
                    onClick={() => onOpenChange(false)}
                    className="p-1 rounded-[var(--radius-sm)] text-[var(--color-text-tertiary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] transition-none"
                    aria-label="关闭"
                  >
                    <svg
                      className="w-5 h-5"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      aria-hidden="true"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M6 18L18 6M6 6l12 12"
                      />
                    </svg>
                  </button>
                )}
              </div>
            )}
            {/* Body（Dialog 内容） */}
            <div className="px-6 py-4 max-h-[70vh] overflow-y-auto">{children}</div>
            {/* Footer（底部操作区） */}
            {footer && (
              <div className="px-6 py-4 border-t border-[var(--dialog-border)] flex justify-end gap-3">
                {footer}
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
};

Dialog.displayName = 'Dialog';
