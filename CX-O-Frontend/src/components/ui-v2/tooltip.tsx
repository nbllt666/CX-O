/**
 * @file tooltip.tsx — Tooltip 组件（第1波基础组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\tooltip.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Tooltip + §TooltipProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.tooltip（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（Tooltip 默认 spring，出现/消失快速响应）
 *   - merged.md §4.2 定制策略（fork 后注入 Liquid Glass 样式，不靠 props 传递）
 *
 * Liquid Glass 定制（I5 §Tooltip docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 出现/消失使用 snappy spring（I3 springs.snappy，快速响应）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - AnimatePresence 管理入场/出场
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
 * 默认 spring: snappy（D5 §springs.snappy.useCase，出现/消失快速响应）
 * apple-design 对齐: damping=22 / stiffness=420 / mass=0.8（快速响应，低过冲）
 * ============================================================================
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
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
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// TooltipProps（对应 I5 §TooltipProps）
// =============================================================================

/**
 * Tooltip 组件 props（对应 I5 §TooltipProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 对应 shadcn Tooltip 的 content/children/side 模式。
 */
export interface TooltipProps extends GlassComponentProps {
  /** Tooltip 内容（ReactNode） */
  content: React.ReactNode;
  /** 子元素（触发 Tooltip 的元素） */
  children: React.ReactNode;
  /** 显示位置（top/right/bottom/left，默认 top） */
  side?: 'top' | 'right' | 'bottom' | 'left';
  /** 延迟显示时间（毫秒，默认 200ms） */
  delay?: number;
  /** 自定义 className（应用到 Tooltip content） */
  className?: string;
}

// =============================================================================
// Tooltip 组件实现
// =============================================================================

/**
 * Tooltip 组件（第1波基础组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Tooltip: ``Tooltip(props: TooltipProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 出现/消失使用 snappy spring（I3 springs.snappy，快速响应）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - AnimatePresence 管理入场/出场
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase，出现/消失快速响应）
 *
 * @param props Tooltip 组件配置（含 content/children/side + Liquid Glass 扩展字段）
 * @returns 渲染后的 Tooltip（通过 createPortal 挂载到 document.body）
 */
export const Tooltip: React.FC<TooltipProps> = function Tooltip({
  content,
  children,
  side = 'top',
  delay = 200,
  className,
  dataGlass = true,
  glassTier,
  glassVariant,
  motionVariants,
}) {
  const [isVisible, setIsVisible] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // 构建 data-glass + data-glass-tier 属性（由 WebGL 层接管渲染）
  const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
  const glassAttributes = buildGlassDataAttributes(dataGlass, validTier);

  // 获取 Framer Motion variants（替换 shadcn 默认 Tailwind transition）
  // 若调用方提供 motionVariants 则直接使用，否则调用 getComponentMotionVariants 生成默认 variants
  // Tooltip 使用 snappy spring 作为默认出现/消失动画
  const resolvedVariants: Variants =
    motionVariants ??
    getComponentMotionVariants({
      componentName: 'Tooltip',
      springKey: glassVariant,
    });

  // 计算 Tooltip 位置（基于 trigger 和 tooltip 的 boundingRect）
  const calculatePosition = useCallback(() => {
    if (!triggerRef.current || !tooltipRef.current) return;

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const tooltipRect = tooltipRef.current.getBoundingClientRect();

    let top = 0;
    let left = 0;

    switch (side) {
      case 'top':
        top = triggerRect.top - tooltipRect.height - 8;
        left = triggerRect.left + (triggerRect.width - tooltipRect.width) / 2;
        break;
      case 'bottom':
        top = triggerRect.bottom + 8;
        left = triggerRect.left + (triggerRect.width - tooltipRect.width) / 2;
        break;
      case 'left':
        top = triggerRect.top + (triggerRect.height - tooltipRect.height) / 2;
        left = triggerRect.left - tooltipRect.width - 8;
        break;
      case 'right':
        top = triggerRect.top + (triggerRect.height - tooltipRect.height) / 2;
        left = triggerRect.right + 8;
        break;
    }

    setCoords({ top, left });
  }, [side]);

  // 鼠标进入: 延迟显示
  const handleMouseEnter = useCallback(() => {
    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
      // 等待下一帧（tooltip 渲染后）再计算位置
      requestAnimationFrame(() => {
        calculatePosition();
      });
    }, delay);
  }, [delay, calculatePosition]);

  // 鼠标离开: 立即隐藏
  const handleMouseLeave = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setIsVisible(false);
  }, []);

  // 组件卸载时清理 timeout
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  // 构建 tooltip 基础 className（通过 className 消费 token，不硬编码颜色）
  const tooltipBaseClassName = cn(
    'fixed z-[100]',
    'px-[var(--tooltip-padding-x)] py-[var(--tooltip-padding-y)]',
    'text-[var(--tooltip-font-size)]',
    'bg-[var(--tooltip-bg)] text-[var(--tooltip-text)]',
    'rounded-[var(--tooltip-radius)] shadow-[var(--tooltip-shadow)]',
    'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
    'pointer-events-none',
    className,
  );

  // 注入 glass 样式类（仅当调用方提供 glassTier 时注入 CSS 降级样式）
  const composedTooltipClassName = validTier
    ? injectGlassClassName(tooltipBaseClassName, validTier)
    : tooltipBaseClassName;

  // SSR 安全：如果 document 不存在则不渲染 portal
  if (typeof document === 'undefined') {
    return (
      <div
        ref={triggerRef}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className="inline-block"
      >
        {children}
      </div>
    );
  }

  return (
    <>
      {/* Trigger 元素（监听 mouseEnter/mouseLeave） */}
      <div
        ref={triggerRef}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className="inline-block"
      >
        {children}
      </div>
      {/* Tooltip content（通过 createPortal 挂载到 document.body） */}
      {createPortal(
        <AnimatePresence>
          {isVisible && (
            <motion.div
              ref={tooltipRef}
              className={composedTooltipClassName}
              style={{ top: coords.top, left: coords.left }}
              // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
              data-glass={glassAttributes['data-glass'] ?? undefined}
              data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
              // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
              variants={resolvedVariants}
              initial="initial"
              animate="animate"
              exit="exit"
              role="tooltip"
            >
              {content}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
};

Tooltip.displayName = 'Tooltip';
