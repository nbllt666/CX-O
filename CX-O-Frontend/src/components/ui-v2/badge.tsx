/**
 * @file badge.tsx — Badge 组件（第3波数据展示组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波3 数据展示组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\badge.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Badge + §BadgeProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.badge（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.glass（Badge 默认 spring，徽章入场柔和）
 *   - merged.md §4.2 定制策略 + §4.3 第3波（数据展示，第7-9周）
 *
 * Liquid Glass 定制（I5 §Badge docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 内联徽章组件，支持 6 种 variant（default/secondary/success/warning/error/anime）
 *   - variant='anime' 时使用二次元配色（通过 CSS 变量 --badge-anime-bg/--badge-anime-text 消费 token，
 *     与模块5 二次元配色板对齐；本组件不直接 import 模块5，配色通过 token 注入）
 *   - 入场动画使用 Framer Motion + glass spring（scale 0.8 → 1 + fade in）
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
 * 默认 spring: glass（D5 §springs.glass.useCase=glass-card-enter，徽章入场柔和）
 * apple-design 对齐: damping=28 / stiffness=320 / mass=0.8（柔和入场）
 * ============================================================================
 */

import React from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  injectGlassClassName,
  buildGlassDataAttributes,
  isValidGlassTier,
} from './inject-glass-style';
import {
  getComponentSpringTransition,
  getDefaultComponentSpring,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// BadgeProps（对应 I5 §BadgeProps）
// =============================================================================

/**
 * Badge variant 字面量联合类型。
 *
 * 6 种 variant:
 *   - default: 默认（中性色）
 *   - secondary: 次要（弱化色）
 *   - success: 成功（绿色系）
 *   - warning: 警告（黄色系）
 *   - error: 错误（红色系）
 *   - anime: 二次元配色（樱花粉/梦境紫等，通过 CSS 变量消费 token）
 */
export type BadgeVariant =
  | 'default'
  | 'secondary'
  | 'success'
  | 'warning'
  | 'error'
  | 'anime';

/**
 * Badge size 字面量联合类型。
 */
export type BadgeSize = 'sm' | 'md';

/**
 * Badge 组件 props（对应 I5 §BadgeProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 内联徽章组件，支持 6 种 variant + 2 种 size。
 */
export interface BadgeProps extends GlassComponentProps {
  /** variant（default/secondary/success/warning/error/anime，默认 default） */
  readonly variant?: BadgeVariant;
  /** size（sm/md，默认 md） */
  readonly size?: BadgeSize;
  /** 子元素（徽章内容） */
  readonly children?: React.ReactNode;
  /** 自定义 className */
  readonly className?: string;
}

// =============================================================================
// variant/size 样式映射（通过 className 消费 token，不硬编码颜色）
// =============================================================================

/**
 * Badge variant 样式映射（对齐 D1 §component.badge + component.css）。
 *
 * 所有颜色通过 CSS 变量消费 token，双主题通过 [data-theme] 自动切换。
 * variant='anime' 通过 --badge-anime-bg/--badge-anime-text 消费模块5 二次元配色板 token。
 * 禁止硬编码颜色（违反 token 消费约定，GN-004 审查标记为不合规）。
 */
const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-[var(--badge-default-bg)] text-[var(--badge-default-text)]',
  secondary: 'bg-[var(--badge-secondary-bg)] text-[var(--badge-secondary-text)]',
  success: 'bg-[var(--badge-success-bg)] text-[var(--badge-success-text)]',
  warning: 'bg-[var(--badge-warning-bg)] text-[var(--badge-warning-text)]',
  error: 'bg-[var(--badge-error-bg)] text-[var(--badge-error-text)]',
  anime: 'bg-[var(--badge-anime-bg)] text-[var(--badge-anime-text)]',
};

/**
 * Badge size 样式映射。
 *
 * padding/fontSize/radius 均通过 CSS 变量或 Tailwind utility 消费 token。
 */
const sizeStyles: Record<BadgeSize, string> = {
  sm: 'px-2 py-0.5 text-xs rounded-[var(--radius-sm)]',
  md: 'px-2.5 py-1 text-sm rounded-[var(--radius-md)]',
};

// =============================================================================
// Badge 组件实现
// =============================================================================

/**
 * Badge 组件（第3波数据展示组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Badge: ``Badge(props: BadgeProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 入场动画使用 glass spring（scale 0.8 → 1 + fade in）
 *   - 6 种 variant（含 anime 二次元配色，通过 CSS 变量消费 token）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: glass（D5 §springs.glass.useCase=glass-card-enter，徽章入场柔和）
 *
 * @param props Badge 组件配置（含 variant/size + Liquid Glass 扩展字段）
 * @returns 渲染后的 Badge
 */
export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  function Badge(
    {
      className,
      variant = 'default',
      size = 'md',
      children,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    // 构建 data-glass + data-glass-tier 属性（由 WebGL 层接管渲染）
    const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
    const glassAttributes = buildGlassDataAttributes(dataGlass, validTier);

    // 入场动画的 glass spring transition（Badge 默认 spring）
    const enterSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Badge'),
    );

    // Badge 入场 variants（scale 0.8 → 1 + fade in，glass spring 柔和入场）
    // 若调用方提供 motionVariants 则直接使用，否则使用默认入场 variants
    const resolvedVariants: Variants =
      motionVariants ??
      ({
        initial: { opacity: 0, scale: 0.8 },
        animate: { opacity: 1, scale: 1, transition: enterSpring },
        exit: { opacity: 0, scale: 0.8, transition: enterSpring },
      } as Variants);

    // 构建 Badge 基础 className（通过 className 消费 token，不硬编码颜色）
    const badgeBaseClassName = cn(
      'inline-flex items-center justify-center',
      'font-medium whitespace-nowrap select-none',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      variantStyles[variant],
      sizeStyles[size],
      className,
    );

    // 注入 glass 样式类（仅当调用方提供 glassTier 时注入 CSS 降级样式）
    const composedClassName = validTier
      ? injectGlassClassName(badgeBaseClassName, validTier)
      : badgeBaseClassName;

    return (
      <motion.span
        ref={ref}
        className={composedClassName}
        // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
        data-glass={glassAttributes['data-glass'] ?? undefined}
        data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
        // data-badge-variant 属性（便于样式定制与测试定位）
        data-badge-variant={variant}
        // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
        variants={resolvedVariants}
        // Badge 入场动画（initial → animate）
        initial="initial"
        animate="animate"
        exit="exit"
        {...props}
      >
        {children}
      </motion.span>
    );
  },
);

Badge.displayName = 'Badge';
