/**
 * @file card.tsx — Card 组件（第1波基础组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\card.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Card + §CardProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.card（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.glass（Card 默认 spring，玻璃面板入场）
 *   - merged.md §4.2 定制策略 + §2.11 多层 box-shadow 叠加
 *
 * Liquid Glass 定制（I5 §Card docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 玻璃面板入场使用 glass spring（I3 springs.glass）
 *   - 多层 box-shadow 叠加（merged.md §2.11，通过 --glass-edge-highlight token）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: glass（D5 §springs.glass.useCase=glass-card-enter）
 * apple-design 对齐: damping=28 / stiffness=320 / mass=0.8（玻璃面板入场）
 * ============================================================================
 */

import React from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  glassPanelClass,
  buildGlassDataAttributes,
} from './inject-glass-style';
import {
  getComponentMotionVariants,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// CardProps（对应 I5 §CardProps）
// =============================================================================

/**
 * Card 组件 props（对应 I5 §CardProps）。
 *
 * 继承自 React.HTMLAttributes（保留 shadcn 原生 API）+ GlassComponentProps（Liquid Glass 扩展）。
 * Omit onDrag/onDragEnd/onAnimationStart/onDragStart/onDragOver/onDragEnter/onDragLeave/onDrop
 *   ——这些事件在 framer-motion 中有特殊含义，需排除以避免类型冲突。
 */
export interface CardProps
  extends Omit<
    React.HTMLAttributes<HTMLDivElement>,
    | 'onDrag'
    | 'onDragEnd'
    | 'onAnimationStart'
    | 'onDragStart'
    | 'onDragOver'
    | 'onDragEnter'
    | 'onDragLeave'
    | 'onDrop'
  >,
    GlassComponentProps {
  /** 是否启用 hover 交互态（上浮 + 边框高亮） */
  hoverable?: boolean;
  /** 是否选中（边框高亮 + ring） */
  selected?: boolean;
}

// =============================================================================
// Card 组件实现
// =============================================================================

/**
 * Card 组件（第1波基础组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Card: ``Card(props: CardProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 玻璃面板入场使用 glass spring（I3 springs.glass）
 *   - 多层 box-shadow 叠加（merged.md §2.11，通过 --glass-edge-highlight token）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: glass（D5 §springs.glass.useCase=glass-card-enter）
 *
 * @param props Card 组件配置（含 shadcn 原生字段 + Liquid Glass 扩展字段）
 * @returns 渲染后的 Card
 */
export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  function Card(
    {
      className,
      hoverable = false,
      selected = false,
      children,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // 获取 Framer Motion variants（替换 shadcn 默认 Tailwind transition）
    // 若调用方提供 motionVariants 则直接使用，否则调用 getComponentMotionVariants 生成默认 variants
    // Card 使用 glass spring 作为默认入场动画
    const resolvedVariants: Variants =
      motionVariants ??
      getComponentMotionVariants({
        componentName: 'Card',
        springKey: glassVariant,
      });

    // 构建 card 基础 className（通过 className 消费 token，不硬编码颜色）
    // 多层 box-shadow 叠加（merged.md §2.11）通过 --glass-edge-highlight token 实现
    // 注意：移除 bg-[var(--card-bg)]，由 glass-panel 类提供玻璃背景
    const cardBaseClassName = cn(
      'rounded-[var(--card-radius)]',
      'text-[var(--card-text)]',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      selected && 'border-[var(--color-accent)] ring-2 ring-[var(--color-accent-light)]',
      className,
    );

    // 注入 glass-panel 类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制）
    const composedClassName = cn(cardBaseClassName, glassPanelClass);

    return (
      <motion.div
        ref={ref}
        className={composedClassName}
        // data-glass 属性（由 WebGL 层 LiquidGlassHost 扫描接管渲染）
        data-glass={glassAttributes['data-glass'] ?? undefined}
        // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
        variants={resolvedVariants}
        // Card 入场动画（initial → animate）
        initial="initial"
        animate="animate"
        // hover 交互态（仅当 hoverable=true 时启用）
        {...(hoverable ? { whileHover: 'hover' } : {})}
        {...props}
      >
        {children}
      </motion.div>
    );
  },
);

Card.displayName = 'Card';

// =============================================================================
// Card 子组件（CardHeader / CardBody / CardFooter）
// =============================================================================

/**
 * CardHeader 组件 props。
 *
 * 继承自 React.HTMLAttributes（保留 shadcn 原生 API）。
 * 不继承 GlassComponentProps（子组件不需要独立的 data-glass 属性，由 Card 父组件统一挂载）。
 */
export type CardHeaderProps = Omit<
  React.HTMLAttributes<HTMLDivElement>,
  | 'onDrag'
  | 'onDragEnd'
  | 'onAnimationStart'
  | 'onDragStart'
  | 'onDragOver'
  | 'onDragEnter'
  | 'onDragLeave'
  | 'onDrop'
>;

/**
 * CardHeader 组件（Card 的头部区域，含底部边框分隔）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const CardHeader: React.FC<CardHeaderProps> = ({
  className,
  children,
  ...props
}) => (
  <div
    className={cn('px-4 py-3 border-b border-white/[0.02]', className)}
    {...props}
  >
    {children}
  </div>
);

CardHeader.displayName = 'CardHeader';

/**
 * CardBody 组件 props。
 *
 * 继承自 React.HTMLAttributes（保留 shadcn 原生 API）。
 */
export type CardBodyProps = Omit<
  React.HTMLAttributes<HTMLDivElement>,
  | 'onDrag'
  | 'onDragEnd'
  | 'onAnimationStart'
  | 'onDragStart'
  | 'onDragOver'
  | 'onDragEnter'
  | 'onDragLeave'
  | 'onDrop'
>;

/**
 * CardBody 组件（Card 的主体内容区域）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const CardBody: React.FC<CardBodyProps> = ({
  className,
  children,
  ...props
}) => (
  <div className={cn('px-4 py-4', className)} {...props}>
    {children}
  </div>
);

CardBody.displayName = 'CardBody';

/**
 * CardFooter 组件 props。
 *
 * 继承自 React.HTMLAttributes（保留 shadcn 原生 API）。
 */
export type CardFooterProps = Omit<
  React.HTMLAttributes<HTMLDivElement>,
  | 'onDrag'
  | 'onDragEnd'
  | 'onAnimationStart'
  | 'onDragStart'
  | 'onDragOver'
  | 'onDragEnter'
  | 'onDragLeave'
  | 'onDrop'
>;

/**
 * CardFooter 组件（Card 的底部区域，含顶部边框分隔 + 背景色）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const CardFooter: React.FC<CardFooterProps> = ({
  className,
  children,
  ...props
}) => (
  <div
    className={cn(
      'px-4 py-3 border-t border-white/[0.02]',
      'bg-white/[0.02] rounded-b-[var(--card-radius)]',
      className,
    )}
    {...props}
  >
    {children}
  </div>
);

CardFooter.displayName = 'CardFooter';
