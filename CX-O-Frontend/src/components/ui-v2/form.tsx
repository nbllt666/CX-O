/**
 * @file form.tsx — Form 组件（第2波表单组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波2 表单组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\form.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Form + §FormProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.form（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.gentle（Form 默认 spring，表单容器整体过渡）
 *   - merged.md §4.2 定制策略 + §4.3 第2波（表单，第4-6周，Settings/Agents/Acp 页面）
 *
 * Liquid Glass 定制（I5 §Form docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 表单容器整体过渡使用 gentle spring（D5 §springs.gentle.useCase=default-transition）
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 保留原生 onSubmit/onReset 等 FormHTMLAttributes API
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: gentle（D5 §springs.gentle.useCase=default-transition，表单容器柔和反馈）
 * apple-design 对齐: damping=32 / stiffness=200 / mass=1（柔和过渡）
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
import { getComponentMotionVariants } from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// FormProps（对应 I5 §FormProps）
// =============================================================================

/**
 * Form 组件 props（对应 I5 §FormProps）。
 *
 * 继承自 React.FormHTMLAttributes（保留 shadcn 原生 API，含 onSubmit/onReset）+ GlassComponentProps。
 * Omit onDrag/onDragEnd/onAnimationStart/onDragStart/onDragOver/onDragEnter/onDragLeave/onDrop
 *   ——这些事件在 framer-motion 中有特殊含义，需排除以避免类型冲突。
 */
export interface FormProps
  extends Omit<
      React.FormHTMLAttributes<HTMLFormElement>,
      | 'onDrag'
      | 'onDragEnd'
      | 'onAnimationStart'
      | 'onDragStart'
      | 'onDragOver'
      | 'onDragEnter'
      | 'onDragLeave'
      | 'onDrop'
    >,
    GlassComponentProps {}

// =============================================================================
// Form 组件实现
// =============================================================================

/**
 * Form 组件（第2波表单组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Form: ``Form(props: FormProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 表单容器整体过渡使用 gentle spring（D5 §springs.gentle）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 保留原生 onSubmit/onReset 等 FormHTMLAttributes API（通过 props 透传）
 *
 * 默认 spring: gentle（D5 §springs.gentle.useCase=default-transition）
 *
 * @param props Form 组件配置（含 shadcn 原生字段 + Liquid Glass 扩展字段）
 * @returns 渲染后的 Form
 */
export const Form = React.forwardRef<HTMLFormElement, FormProps>(
  function Form(
    {
      className,
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
    // Form 使用 gentle spring 作为默认入场/出场动画（表单容器整体过渡）
    // 调用方可通过 motionVariants 注入入场/出场动画（用于 AnimatePresence 表单入场/出场场景）
    const resolvedVariants: Variants | undefined =
      motionVariants ??
      (glassVariant
        ? getComponentMotionVariants({
            componentName: 'Form',
            springKey: glassVariant,
          })
        : undefined);

    // 构建 form 基础 className（通过 className 消费 token，不硬编码颜色）
    const formBaseClassName = cn(
      'w-full p-[var(--form-padding)] rounded-[var(--form-radius)]',
      'bg-[var(--form-bg)] text-[var(--form-text)]',
      'border border-[var(--form-border)]',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      className,
    );

    // 注入 glass 样式类（仅当调用方提供 glassTier 时注入 CSS 降级样式）
    // Tier 1/2: bg-transparent（WebGL 层接管渲染）
    // Tier 3: backdrop-filter + box-shadow（CSS 降级）
    // Tier 4: background-color 半透明兜底
    const composedClassName = validTier
      ? injectGlassClassName(formBaseClassName, validTier)
      : formBaseClassName;

    return (
      <motion.form
        ref={ref}
        className={composedClassName}
        // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
        data-glass={glassAttributes['data-glass'] ?? undefined}
        data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
        // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
        // 仅当调用方提供 motionVariants 或 glassVariant 时注入 variants
        {...(resolvedVariants ? { variants: resolvedVariants } : {})}
        // 保留原生 onSubmit/onReset 等 FormHTMLAttributes API（通过 props 透传）
        {...props}
      />
    );
  },
);

Form.displayName = 'Form';
