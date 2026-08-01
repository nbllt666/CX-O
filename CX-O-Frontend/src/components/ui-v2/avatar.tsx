/**
 * @file avatar.tsx — Avatar 组件（第3波数据展示组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波3 数据展示组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\avatar.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Avatar + §AvatarProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.avatar（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.glass（Avatar 默认 spring，头像入场柔和）
 *   - merged.md §4.2 定制策略 + §4.3 第3波（数据展示，第7-9周）+ §3.3 Chat 页面圆形 96px
 *
 * Liquid Glass 定制（I5 §Avatar docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 头像组件，支持图片加载失败时显示 fallback（默认显示首字母或图标）
 *   - 图片加载状态管理: loading → loaded → error
 *   - 入场动画使用 Framer Motion + glass spring（scale 0.8 → 1 + fade in）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 提供 AvatarFallback 子组件（参考 shadcn Avatar 风格）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: glass（D5 §springs.glass.useCase=glass-card-enter，头像入场柔和，与 Card 一致）
 * apple-design 对齐: damping=28 / stiffness=320 / mass=0.8（柔和入场）
 *
 * size 映射（I5 §Avatar docstring: Chat 页面圆形 96px）:
 *   - sm: 24px
 *   - md: 32px
 *   - lg: 48px
 *   - xl: 96px（Chat 页面角色头像）
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
  getComponentSpringTransition,
  getDefaultComponentSpring,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// AvatarProps + AvatarFallbackProps（对应 I5 §AvatarProps）
// =============================================================================

/**
 * Avatar size 字面量联合类型。
 *
 * 对应像素值（I5 §Avatar docstring: Chat 页面圆形 96px）:
 *   - sm: 24px
 *   - md: 32px
 *   - lg: 48px
 *   - xl: 96px（Chat 页面角色头像）
 */
export type AvatarSize = 'sm' | 'md' | 'lg' | 'xl';

/**
 * Avatar shape 字面量联合类型。
 */
export type AvatarShape = 'circle' | 'square';

/**
 * Avatar 图片加载状态。
 */
type AvatarLoadStatus = 'loading' | 'loaded' | 'error';

/**
 * Avatar 组件 props（对应 I5 §AvatarProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 头像组件，支持图片加载失败时显示 fallback。
 */
export interface AvatarProps extends GlassComponentProps {
  /** 图片地址（未提供或加载失败时显示 fallback） */
  readonly src?: string;
  /** 替代文本（无障碍，也用于生成默认 fallback 首字母） */
  readonly alt?: string;
  /** 自定义 fallback 内容（未提供时默认显示首字母或占位图标） */
  readonly fallback?: React.ReactNode;
  /** size（sm=24px/md=32px/lg=48px/xl=96px，默认 md） */
  readonly size?: AvatarSize;
  /** shape（circle/square，默认 circle） */
  readonly shape?: AvatarShape;
  /** 自定义 className */
  readonly className?: string;
  /** 子元素（作为 fallback 内容，优先级低于 fallback prop） */
  readonly children?: React.ReactNode;
}

/**
 * AvatarFallback 组件 props。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * fallback 内容容器，当图片加载失败或无 src 时显示。
 */
export interface AvatarFallbackProps extends GlassComponentProps {
  /** 子元素（fallback 内容） */
  readonly children?: React.ReactNode;
  /** 自定义 className */
  readonly className?: string;
}

// =============================================================================
// size 样式映射（通过 className 消费 token，不硬编码颜色）
// =============================================================================

/**
 * Avatar size 样式映射。
 *
 * 像素值对齐 I5 §Avatar docstring:
 *   - sm: 24px
 *   - md: 32px
 *   - lg: 48px
 *   - xl: 96px（Chat 页面角色头像）
 */
const sizeStyles: Record<AvatarSize, string> = {
  sm: 'h-6 w-6 text-xs',
  md: 'h-8 w-8 text-sm',
  lg: 'h-12 w-12 text-base',
  xl: 'h-24 w-24 text-2xl',
};

/**
 * Avatar shape 样式映射。
 */
const shapeStyles: Record<AvatarShape, string> = {
  circle: 'rounded-full',
  square: 'rounded-[var(--radius-md)]',
};

// =============================================================================
// 辅助: 从 alt 提取首字母作为默认 fallback
// =============================================================================

/**
 * 从 alt 文本提取首字母作为默认 fallback 内容。
 *
 * 取首个非空字符（支持中英文），若 alt 为空则返回占位图标 SVG。
 *
 * @param alt 替代文本
 * @returns 首字母或占位图标
 */
function getDefaultFallback(alt?: string): React.ReactNode {
  if (alt && alt.trim().length > 0) {
    return alt.trim().charAt(0).toUpperCase();
  }
  // 占位图标（用户 silhouette SVG，currentColor 消费 token）
  return (
    <svg
      className="h-1/2 w-1/2"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      aria-hidden="true"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 12a4 4 0 100-8 4 4 0 000 8zm0 2c-4 0-8 2-8 5v1h16v-1c0-3-4-5-8-5z"
      />
    </svg>
  );
}

// =============================================================================
// Avatar 组件实现
// =============================================================================

/**
 * Avatar 组件（第3波数据展示组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Avatar: ``Avatar(props: AvatarProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 图片加载状态管理: loading → loaded → error
 *   - 入场动画使用 glass spring（scale 0.8 → 1 + fade in）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: glass（D5 §springs.glass.useCase=glass-card-enter，头像入场柔和）
 *
 * @param props Avatar 组件配置（含 src/alt/fallback/size/shape + Liquid Glass 扩展字段）
 * @returns 渲染后的 Avatar
 */
export const Avatar = React.forwardRef<HTMLSpanElement, AvatarProps>(
  function Avatar(
    {
      className,
      src,
      alt,
      fallback,
      size = 'md',
      shape = 'circle',
      children,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    // 图片加载状态管理: loading → loaded → error
    const [status, setStatus] = React.useState<AvatarLoadStatus>(
      src ? 'loading' : 'error',
    );

    // src 变化时重置状态（重新加载）
    React.useEffect(() => {
      if (src) {
        setStatus('loading');
      } else {
        setStatus('error');
      }
    }, [src]);

    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // 入场动画的 glass spring transition（Avatar 默认 spring）
    const enterSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Avatar'),
    );

    // Avatar 入场 variants（scale 0.8 → 1 + fade in，glass spring 柔和入场）
    const resolvedVariants: Variants =
      motionVariants ??
      ({
        initial: { opacity: 0, scale: 0.8 },
        animate: { opacity: 1, scale: 1, transition: enterSpring },
        exit: { opacity: 0, scale: 0.8, transition: enterSpring },
      } as Variants);

    // 构建 Avatar 基础 className（通过 className 消费 token，不硬编码颜色）
    const avatarBaseClassName = cn(
      'relative inline-flex items-center justify-center overflow-hidden',
      'shrink-0',
      'bg-[var(--avatar-bg)]',
      'border border-[var(--avatar-border)]',
      'shadow-[var(--avatar-shadow)]',
      'text-[var(--avatar-text)]',
      'font-medium select-none',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      sizeStyles[size],
      shapeStyles[shape],
      className,
    );

    // 注入 glass 样式类（v2: 直接拼接 glassPanelClass，不再区分 tier）
    const composedClassName = cn(avatarBaseClassName, glassPanelClass);

    // 确定 fallback 内容（优先级: fallback prop > children > 默认首字母/图标）
    const fallbackContent = fallback ?? children ?? getDefaultFallback(alt);

    // 是否显示 fallback（无 src / 加载中 / 加载失败时显示）
    const showFallback = !src || status !== 'loaded';

    return (
      <motion.span
        ref={ref}
        className={composedClassName}
        // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
        data-glass={glassAttributes['data-glass'] ?? undefined}
        // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
        variants={resolvedVariants}
        // Avatar 入场动画（initial → animate）
        initial="initial"
        animate="animate"
        exit="exit"
        {...props}
      >
        {/* 图片: src 提供时始终渲染（触发 onLoad/onError），通过 opacity 控制可见性 */}
        {src && (
          <img
            src={src}
            alt={alt ?? ''}
            className={cn(
              'h-full w-full object-cover',
              status !== 'loaded' && 'opacity-0',
            )}
            onLoad={() => setStatus('loaded')}
            onError={() => setStatus('error')}
          />
        )}
        {/* Fallback: 无 src / 加载中 / 加载失败时显示 */}
        {showFallback && (
          <AvatarFallback
            glassVariant={glassVariant}
            className={status === 'loading' ? 'opacity-60' : undefined}
          >
            {status === 'loading' ? null : fallbackContent}
          </AvatarFallback>
        )}
      </motion.span>
    );
  },
);

Avatar.displayName = 'Avatar';

// =============================================================================
// AvatarFallback 子组件实现
// =============================================================================

/**
 * AvatarFallback 组件（头像 fallback 内容容器）。
 *
 * 当图片加载失败或无 src 时显示。可独立使用，也可作为 Avatar 的 fallback 内容。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const AvatarFallback = React.forwardRef<HTMLSpanElement, AvatarFallbackProps>(
  function AvatarFallback(
    {
      className,
      children,
      dataGlass = false, // fallback 不独立挂载 data-glass（由 Avatar 父组件统一挂载）
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // 入场动画的 glass spring transition（与 Avatar 一致）
    const enterSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Avatar'),
    );

    // Fallback 入场 variants（fade in，glass spring）
    const resolvedVariants: Variants =
      motionVariants ??
      ({
        initial: { opacity: 0 },
        animate: { opacity: 1, transition: enterSpring },
        exit: { opacity: 0, transition: enterSpring },
      } as Variants);

    // 构建 AvatarFallback className（通过 className 消费 token，不硬编码颜色）
    const fallbackBaseClassName = cn(
      'absolute inset-0 flex items-center justify-center',
      'bg-[var(--avatar-fallback-bg)]',
      'text-[var(--avatar-fallback-text)]',
      'transition-none',
      className,
    );

    const composedClassName = cn(fallbackBaseClassName, glassPanelClass);

    return (
      <motion.span
        ref={ref}
        className={composedClassName}
        data-glass={glassAttributes['data-glass'] ?? undefined}
        variants={resolvedVariants}
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

AvatarFallback.displayName = 'AvatarFallback';
