/**
 * @file button.tsx — Button 组件（第1波基础组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\button.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Button + §ButtonProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.button（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（Button 默认 spring）
 *   - merged.md §4.2 定制策略（fork 后注入 Liquid Glass 样式，不靠 props 传递）
 *
 * Liquid Glass 定制（I5 §Button docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - pointer-down 即时反馈: 按下立即 scale 0.96，无 300ms 延迟（apple-design §pointerDownImmediate）
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press）
 * apple-design 对齐: damping=22 / stiffness=420 / mass=0.8（快速响应，低过冲）
 * ============================================================================
 */

import React from 'react';
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import type { GlassTier } from '@/lib/glass/tier-detector';
import type { SpringKey } from '@/lib/motion';
import {
  injectGlassClassName,
  buildGlassDataAttributes,
  isValidGlassTier,
} from './inject-glass-style';
import {
  getComponentMotionVariants,
} from './motion-variants';

// =============================================================================
// GlassComponentProps（对应 I5 §GlassComponentProps）
// =============================================================================

/**
 * Liquid Glass 组件扩展 props 基类（对应 I5 §GlassComponentProps）。
 *
 * 所有 ui-v2 组件 props 继承此接口，提供 Liquid Glass 扩展字段:
 *   - dataGlass: 是否挂载 data-glass 属性（默认 true，由 WebGL 层接管渲染）
 *   - glassTier: 强制指定 glass tier（可选，默认由 useGlassTier 自动检测）
 *   - glassVariant: spring 预设 key（覆盖组件默认 spring 映射）
 *   - motionVariants: Framer Motion variants（覆盖默认 variants，由 I3 createMotionVariants 生成）
 */
export interface GlassComponentProps {
  /** 是否挂载 data-glass 属性（默认 true，由 WebGL 层接管渲染） */
  readonly dataGlass?: boolean;
  /** 强制指定 glass tier（可选，默认由 useGlassTier 自动检测） */
  readonly glassTier?: GlassTier;
  /** spring 预设 key（glass/snappy/gentle/bouncy/character/sheet，覆盖组件默认 spring 映射） */
  readonly glassVariant?: SpringKey;
  /** Framer Motion variants，替换 shadcn 默认 Tailwind transition（由 I3 createMotionVariants 生成） */
  readonly motionVariants?: Variants;
}

// =============================================================================
// ButtonProps（对应 I5 §ButtonProps）
// =============================================================================

/**
 * Button 组件 props（对应 I5 §ButtonProps）。
 *
 * 继承自 React.ButtonHTMLAttributes（保留 shadcn 原生 API）+ GlassComponentProps（Liquid Glass 扩展）。
 * Omit onDrag/onDragEnd/onAnimationStart/onDragStart/onDragOver/onDragEnter/onDragLeave/onDrop
 *   ——这些事件在 framer-motion 中有特殊含义，需排除以避免类型冲突。
 */
export interface ButtonProps
  extends Omit<
    React.ButtonHTMLAttributes<HTMLButtonElement>,
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
  /** shadcn variant（primary/secondary/ghost/danger） */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  /** shadcn size（sm/md/lg） */
  size?: 'sm' | 'md' | 'lg';
  /** 加载状态（显示 spinner，禁用按钮） */
  loading?: boolean;
  /** 前置图标 */
  icon?: React.ReactNode;
}

// =============================================================================
// variant/size 样式映射（通过 className 消费 token，不硬编码颜色）
// =============================================================================

/**
 * Button variant 样式映射（对齐 D1 §component.button + component.css）。
 *
 * 所有颜色通过 CSS 变量消费 token，双主题通过 [data-theme] 自动切换。
 * 禁止硬编码颜色（违反 token 消费约定，GN-004 审查标记为不合规）。
 */
const variantStyles: Record<NonNullable<ButtonProps['variant']>, string> = {
  primary: cn(
    'bg-[var(--button-bg)] text-[var(--button-text)]',
    'hover:bg-[var(--button-bg-hover)] active:bg-[var(--button-bg-active)]',
  ),
  secondary: cn(
    'bg-[var(--color-surface)] text-[var(--color-text-primary)]',
    'hover:bg-[var(--color-bg-hover)] border border-[var(--button-border)]',
  ),
  ghost: cn(
    'text-[var(--color-text-secondary)]',
    'hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)]',
  ),
  danger: cn(
    'bg-[var(--color-error)] text-white',
    'hover:opacity-90',
  ),
};

/**
 * Button size 样式映射（对齐 D1 §component.button + component.css）。
 *
 * padding/radius/fontSize 均通过 CSS 变量消费 token。
 */
const sizeStyles: Record<NonNullable<ButtonProps['size']>, string> = {
  sm: 'px-3 py-1.5 text-sm rounded-[var(--radius-sm)]',
  md: cn(
    'px-[var(--button-padding-x)] py-[var(--button-padding-y)]',
    'text-[var(--button-font-size)] rounded-[var(--button-radius)]',
    'font-[var(--button-font-weight)] leading-[var(--button-line-height)]',
  ),
  lg: 'px-6 py-3 text-base rounded-[var(--radius-lg)]',
};

// =============================================================================
// Button 组件实现
// =============================================================================

/**
 * Button 组件（第1波基础组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Button: ``Button(props: ButtonProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - pointer-down 即时反馈: 按下立即 scale 0.96（apple-design §pointerDownImmediate）
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press）
 *
 * @param props Button 组件配置（含 shadcn 原生字段 + Liquid Glass 扩展字段）
 * @returns 渲染后的 Button
 */
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      className,
      variant = 'primary',
      size = 'md',
      loading = false,
      icon,
      children,
      disabled,
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

    // 获取 Framer Motion variants（替换 shadcn 默认 Tailwind transition）
    // 若调用方提供 motionVariants 则直接使用，否则调用 getComponentMotionVariants 生成默认 variants
    // 若调用方提供 glassVariant（spring key）则覆盖默认 spring 映射
    const resolvedVariants: Variants =
      motionVariants ??
      getComponentMotionVariants({
        componentName: 'Button',
        springKey: glassVariant,
      });

    // 构建 glass 样式类（仅当调用方提供 glassTier 时注入 CSS 降级样式）
    // Tier 1/2: bg-transparent（WebGL 层接管渲染）
    // Tier 3: backdrop-filter + box-shadow（CSS 降级）
    // Tier 4: background-color 半透明兜底
    const baseClassName = cn(
      'relative inline-flex items-center justify-center gap-2 font-medium overflow-hidden',
      'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2',
      'disabled:opacity-50 disabled:cursor-not-allowed',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      variantStyles[variant],
      sizeStyles[size],
      className,
    );

    const composedClassName = validTier
      ? injectGlassClassName(baseClassName, validTier)
      : baseClassName;

    return (
      <motion.button
        ref={ref}
        className={composedClassName}
        // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
        data-glass={glassAttributes['data-glass'] ?? undefined}
        data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
        // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
        variants={resolvedVariants}
        // Button 不需要入场/出场动画，仅使用 hover/press 交互态 variants
        whileHover="hover"
        whileTap="press"
        disabled={disabled || loading}
        {...props}
      >
        {/* 涟漪光效（pointer-events: none，不影响交互） */}
        <span
          className="absolute inset-0 rounded-inherit pointer-events-none opacity-0"
          aria-hidden="true"
        />
        {loading ? (
          <svg
            className="animate-spin h-4 w-4"
            viewBox="0 0 24 24"
            style={{ transformOrigin: 'center' }}
            aria-hidden="true"
          >
            <defs>
              <linearGradient id="button-spinner-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="currentColor" stopOpacity="0.3" />
                <stop offset="50%" stopColor="currentColor" stopOpacity="1" />
                <stop offset="100%" stopColor="currentColor" stopOpacity="0.3" />
              </linearGradient>
            </defs>
            <circle
              cx="12"
              cy="12"
              r="10"
              stroke="url(#button-spinner-gradient)"
              strokeWidth="4"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        ) : icon ? (
          icon
        ) : null}
        {children}
      </motion.button>
    );
  },
);

Button.displayName = 'Button';
