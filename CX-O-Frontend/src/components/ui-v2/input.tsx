/**
 * @file input.tsx — Input 组件（第1波基础组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\input.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Input + §InputProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.input（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（Input 默认 spring）
 *   - merged.md §4.2 定制策略（fork 后注入 Liquid Glass 样式，不靠 props 传递）
 *
 * Liquid Glass 定制（I5 §Input docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 核心交互元件禁装饰（I4 validateDecorationBoundary 校验，Input 为核心交互元件）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition（调用方可通过 motionVariants 注入）
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
 * 默认 spring: snappy（D5 §springs.snappy.useCase，快速响应）
 * 核心交互元件: Input 为核心交互元件，禁装饰（I4 validateDecorationBoundary）
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
// InputProps（对应 I5 §InputProps）
// =============================================================================

/**
 * Input 组件 props（对应 I5 §InputProps）。
 *
 * 继承自 React.InputHTMLAttributes（保留 shadcn 原生 API）+ GlassComponentProps（Liquid Glass 扩展）。
 * Omit onDrag/onDragEnd/onAnimationStart/onDragStart/onDragOver/onDragEnter/onDragLeave/onDrop
 *   ——这些事件在 framer-motion 中有特殊含义，需排除以避免类型冲突。
 *
 * 核心交互元件禁装饰（I4 validateDecorationBoundary）:
 *   Input 为核心交互元件，禁止添加装饰性动效（如粒子/光效/呼吸等），
 *   仅保留必要的 focus 反馈与 data-glass 属性挂载。
 */
export interface InputProps
  extends Omit<
    React.InputHTMLAttributes<HTMLInputElement>,
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
  /** 标签文本（可选，渲染在 input 上方） */
  label?: string;
  /** 错误信息（可选，渲染在 input 下方，触发错误样式） */
  error?: string;
  /** 前置图标（可选，渲染在 input 左侧） */
  icon?: React.ReactNode;
  /** 后置图标/后缀（可选，渲染在 input 右侧） */
  suffix?: React.ReactNode;
}

// =============================================================================
// Input 组件实现
// =============================================================================

/**
 * Input 组件（第1波基础组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Input: ``Input(props: InputProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 核心交互元件禁装饰（I4 validateDecorationBoundary 校验）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition（调用方可通过 motionVariants 注入）
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase，快速响应）
 *
 * 核心交互元件禁装饰说明:
 *   Input 为核心交互元件，禁止添加装饰性动效（如粒子/光效/呼吸等）。
 *   仅保留 focus 反馈（CSS :focus 伪类）与 data-glass 属性挂载。
 *   调用方可通过 motionVariants 注入入场/出场动画（用于 AnimatePresence 场景）。
 *
 * @param props Input 组件配置（含 shadcn 原生字段 + Liquid Glass 扩展字段）
 * @returns 渲染后的 Input
 */
export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  function Input(
    {
      className,
      label,
      error,
      icon,
      suffix,
      type = 'text',
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
    // 注意: Input 为核心交互元件，不使用 hover/press 交互态 variants（禁装饰）
    //       variants 仅用于入场/出场动画（由父组件 AnimatePresence 控制）
    const resolvedVariants: Variants | undefined =
      motionVariants ??
      (glassVariant
        ? getComponentMotionVariants({
            componentName: 'Input',
            springKey: glassVariant,
          })
        : undefined);

    // 构建 input 基础 className（通过 className 消费 token，不硬编码颜色）
    const inputBaseClassName = cn(
      'w-full px-[var(--input-padding-x)] py-[var(--input-padding-y)]',
      'text-[var(--input-font-size)] rounded-[var(--input-radius)]',
      'bg-[var(--input-bg)] text-[var(--input-text)]',
      'border border-[var(--input-border)]',
      'placeholder:text-[var(--input-placeholder)]',
      // focus 状态: 使用 CSS :focus 伪类（核心交互元件的原生交互态）
      'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent',
      // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      'transition-none',
      'disabled:opacity-50 disabled:cursor-not-allowed',
      Boolean(icon) && 'pl-10',
      Boolean(suffix) && 'pr-10',
      Boolean(error) && 'border-[var(--color-error)] focus:ring-[var(--color-error)]',
      className,
    );

    // 注入 glass-panel 类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制）
    const composedInputClassName = cn(inputBaseClassName, glassPanelClass);

    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
            {label}
          </label>
        )}
        <div className="relative">
          {icon && (
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)] pointer-events-none">
              {icon}
            </div>
          )}
          <motion.input
            ref={ref}
            type={type}
            className={composedInputClassName}
            // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
            data-glass={glassAttributes['data-glass'] ?? undefined}
            // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
            // 仅当调用方提供 motionVariants 或 glassVariant 时注入 variants
            {...(resolvedVariants ? { variants: resolvedVariants } : {})}
            {...props}
          />
          {suffix && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)] pointer-events-none">
              {suffix}
            </div>
          )}
        </div>
        {error && <p className="mt-1.5 text-sm text-[var(--color-error)]">{error}</p>}
      </div>
    );
  },
);

Input.displayName = 'Input';

// =============================================================================
// Textarea 组件（Input 的多行变体，共享 Liquid Glass 定制）
// =============================================================================

/**
 * Textarea 组件 props（继承 InputProps 的 Liquid Glass 扩展）。
 *
 * 继承自 React.TextareaHTMLAttributes + GlassComponentProps（Liquid Glass 扩展）。
 */
export interface TextareaProps
  extends Omit<
    React.TextareaHTMLAttributes<HTMLTextAreaElement>,
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
  /** 标签文本（可选） */
  label?: string;
  /** 错误信息（可选） */
  error?: string;
}

/**
 * Textarea 组件（Input 的多行变体，Liquid Glass 定制）。
 *
 * 共享 Input 的 Liquid Glass 定制策略:
 *   - 挂载 data-glass 属性
 *   - 核心交互元件禁装饰
 *   - 通过 className 消费 token
 *   - 双主题通过 CSS 变量自动切换
 */
export const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    {
      className,
      label,
      error,
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

    // 获取 Framer Motion variants（同 Input，核心交互元件禁装饰）
    const resolvedVariants: Variants | undefined =
      motionVariants ??
      (glassVariant
        ? getComponentMotionVariants({
            componentName: 'Input',
            springKey: glassVariant,
          })
        : undefined);

    // 构建 textarea 基础 className
    const textareaBaseClassName = cn(
      'w-full px-[var(--input-padding-x)] py-[var(--input-padding-y)]',
      'text-[var(--input-font-size)] rounded-[var(--input-radius)]',
      'bg-[var(--input-bg)] text-[var(--input-text)]',
      'border border-[var(--input-border)]',
      'placeholder:text-[var(--input-placeholder)]',
      'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent',
      'transition-none',
      'disabled:opacity-50 disabled:cursor-not-allowed',
      'resize-none min-h-[100px]',
      Boolean(error) && 'border-[var(--color-error)] focus:ring-[var(--color-error)]',
      className,
    );

    // 注入 glass-panel 类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制）
    const composedTextareaClassName = cn(textareaBaseClassName, glassPanelClass);

    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
            {label}
          </label>
        )}
        <motion.textarea
          ref={ref}
          className={composedTextareaClassName}
          data-glass={glassAttributes['data-glass'] ?? undefined}
          {...(resolvedVariants ? { variants: resolvedVariants } : {})}
          {...props}
        />
        {error && <p className="mt-1.5 text-sm text-[var(--color-error)]">{error}</p>}
      </div>
    );
  },
);

Textarea.displayName = 'Textarea';
