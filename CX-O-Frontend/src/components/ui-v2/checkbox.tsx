/**
 * @file checkbox.tsx — Checkbox 组件（第2波表单组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波2 表单组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\checkbox.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Checkbox + §CheckboxProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.checkbox（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（Checkbox 默认 spring，勾选快速响应）
 *   - merged.md §4.2 定制策略 + §4.3 第2波（表单，第4-6周）
 *
 * Liquid Glass 定制（I5 §Checkbox docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 自定义复选框（隐藏原生 input + 自定义 box + Framer Motion 勾选动画）
 *   - 勾选动画使用 SVG path + pathLength 动画（Framer Motion snappy spring）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 保留原生 input 的无障碍属性（role/aria-checked 等）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，勾选反馈快速响应）
 * apple-design 对齐: damping=22 / stiffness=420 / mass=0.8（快速响应，低过冲）
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
// CheckboxProps（对应 I5 §CheckboxProps）
// =============================================================================

/**
 * Checkbox 组件 props（对应 I5 §CheckboxProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 采用自定义复选框模式: 隐藏原生 input（保留无障碍属性）+ 自定义 box + SVG 勾选动画。
 */
export interface CheckboxProps extends GlassComponentProps {
  /** 是否选中（受控模式，默认 false） */
  readonly checked?: boolean;
  /** 选中状态变化回调（受控模式） */
  readonly onCheckedChange?: (checked: boolean) => void;
  /** 是否禁用 */
  readonly disabled?: boolean;
  /** 标签文本（渲染在复选框右侧） */
  readonly label?: React.ReactNode;
  /** 自定义 className（应用到自定义 box） */
  readonly className?: string;
  /** input id（用于 label 关联） */
  readonly id?: string;
  /** input name（用于表单提交） */
  readonly name?: string;
  /** input value（用于表单提交） */
  readonly value?: string;
  /** 是否必填 */
  readonly required?: boolean;
  /** 无障碍标签 */
  readonly 'aria-label'?: string;
  /** 无障碍关联标签 id */
  readonly 'aria-labelledby'?: string;
}

// =============================================================================
// Checkbox 组件实现
// =============================================================================

/**
 * Checkbox 组件（第2波表单组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Checkbox: ``Checkbox(props: CheckboxProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 自定义复选框（隐藏原生 input + 自定义 box + Framer Motion 勾选动画）
 *   - 勾选动画使用 SVG path + pathLength 动画（snappy spring）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 保留原生 input 的无障碍属性（aria-checked / role 由原生 input 提供）
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press）
 *
 * @param props Checkbox 组件配置（含 checked/onCheckedChange + Liquid Glass 扩展字段）
 * @returns 渲染后的 Checkbox
 */
export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  function Checkbox(
    {
      className,
      checked = false,
      onCheckedChange,
      disabled = false,
      label,
      id,
      name,
      value,
      required,
      'aria-label': ariaLabel,
      'aria-labelledby': ariaLabelledBy,
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

    // 获取勾选动画的 snappy spring transition（剥离元数据，供 Framer Motion transition 用）
    // Checkbox 默认 spring 为 snappy（getDefaultComponentSpring('Checkbox') => 'snappy'）
    // 调用方可通过 glassVariant 覆盖默认 spring 映射
    const checkSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Checkbox'),
    );

    // 勾选标记 variants（SVG path pathLength 0→1 动画 + snappy spring）
    // 若调用方提供 motionVariants 则直接使用，否则使用默认 pathLength variants
    const checkVariants: Variants =
      motionVariants ??
      ({
        unchecked: { pathLength: 0, opacity: 0, transition: checkSpring },
        checked: { pathLength: 1, opacity: 1, transition: checkSpring },
      } as Variants);

    // change 事件处理: 调用 onCheckedChange 回调
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      onCheckedChange?.(e.target.checked);
    };

    // 构建自定义 box className（通过 className 消费 token，不硬编码颜色）
    const boxClassName = cn(
      'relative inline-flex h-5 w-5 shrink-0 items-center justify-center',
      'rounded-[var(--checkbox-radius)] border-2',
      'bg-[var(--checkbox-bg)] border-[var(--checkbox-border)]',
      checked &&
        'bg-[var(--checkbox-checked-bg)] border-[var(--checkbox-checked-border)]',
      'focus-within:ring-2 focus-within:ring-[var(--color-accent)] focus-within:ring-offset-2',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      disabled && 'opacity-50 cursor-not-allowed',
      className,
    );

    // 注入 glass-panel 类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制）
    const composedBoxClassName = cn(boxClassName, glassPanelClass);

    return (
      <label
        className={cn(
          'inline-flex items-center gap-2',
          disabled ? 'cursor-not-allowed' : 'cursor-pointer',
        )}
      >
        <span
          className={composedBoxClassName}
          // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
          data-glass={glassAttributes['data-glass'] ?? undefined}
        >
          {/* 隐藏原生 input（保留无障碍属性 + 表单提交能力） */}
          <input
            ref={ref}
            type="checkbox"
            className="sr-only"
            checked={checked}
            onChange={handleChange}
            disabled={disabled}
            id={id}
            name={name}
            value={value}
            required={required}
            aria-label={ariaLabel}
            aria-labelledby={ariaLabelledBy}
            {...props}
          />
          {/* SVG 勾选标记（pathLength 动画 + snappy spring） */}
          <motion.svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5 pointer-events-none stroke-[var(--checkbox-check-color)]"
            fill="none"
            strokeWidth={3}
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <motion.path
              d="M5 13l4 4L19 7"
              variants={checkVariants}
              animate={checked ? 'checked' : 'unchecked'}
              initial={false}
            />
          </motion.svg>
        </span>
        {label && (
          <span className="text-sm text-[var(--color-text-primary)] select-none">
            {label}
          </span>
        )}
      </label>
    );
  },
);

Checkbox.displayName = 'Checkbox';
