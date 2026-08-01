/**
 * @file radio-group.tsx — RadioGroup 组件（第2波表单组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波2 表单组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\radio-group.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §RadioGroup + §RadioGroupProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.radio（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（RadioGroup 默认 spring，单选切换快速响应）
 *   - merged.md §4.2 定制策略 + §4.3 第2波（表单，第4-6周）
 *
 * Liquid Glass 定制（I5 §RadioGroup docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - RadioGroup 容器 + RadioGroupItem 子组件（通过 RadioContext 共享选中状态）
 *   - RadioGroupItem 勾选动画同 Checkbox（SVG circle + snappy spring）
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
 * 默认 spring: snappy（D5 §springs.snappy.useCase=toggle-switch，单选切换快速响应）
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
  getComponentMotionVariants,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// RadioContext（RadioGroup → RadioGroupItem 选中状态共享）
// =============================================================================

/**
 * RadioGroup 向 RadioGroupItem 提供的上下文值。
 *
 * RadioGroupItem 通过 context 获取当前选中值与变更回调，实现单选语义。
 */
interface RadioContextValue {
  /** 当前选中值（受控模式） */
  readonly value: string | undefined;
  /** 选中值变化回调（受控模式） */
  readonly onValueChange?: (value: string) => void;
  /** input name（用于表单提交，所有 RadioGroupItem 共享） */
  readonly name?: string;
  /** 整组是否禁用 */
  readonly disabled: boolean;
}

/**
 * RadioContext 默认值（RadioGroupItem 在 RadioGroup 外使用时的降级值）。
 *
 * 正常使用时 RadioGroupItem 必须作为 RadioGroup 的子元素。此默认值仅用于
 * 防 RadioGroupItem 被误用到 RadioGroup 外时避免运行时崩溃（选中状态为无）。
 */
const DEFAULT_RADIO_CONTEXT: RadioContextValue = {
  value: undefined,
  name: undefined,
  disabled: false,
};

const RadioContext = React.createContext<RadioContextValue>(DEFAULT_RADIO_CONTEXT);

// =============================================================================
// RadioGroupProps / RadioGroupItemProps（对应 I5 §RadioGroupProps）
// =============================================================================

/**
 * RadioGroup 组件 props（对应 I5 §RadioGroupProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * RadioGroup 为容器组件，通过 RadioContext 向 RadioGroupItem 共享选中状态。
 */
export interface RadioGroupProps extends GlassComponentProps {
  /** 当前选中值（受控模式） */
  readonly value?: string;
  /** 选中值变化回调（受控模式） */
  readonly onValueChange?: (value: string) => void;
  /** 子元素（应为 RadioGroupItem） */
  readonly children?: React.ReactNode;
  /** 自定义 className（应用到 RadioGroup 容器） */
  readonly className?: string;
  /** input name（所有 RadioGroupItem 共享，用于表单提交） */
  readonly name?: string;
  /** 整组是否禁用 */
  readonly disabled?: boolean;
  /** 无障碍标签 */
  readonly 'aria-label'?: string;
  /** 无障碍关联标签 id */
  readonly 'aria-labelledby'?: string;
}

/**
 * RadioGroupItem 组件 props。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * RadioGroupItem 必须作为 RadioGroup 的子元素，通过 RadioContext 获取选中状态。
 */
export interface RadioGroupItemProps extends GlassComponentProps {
  /** 该选项的值（选中时 onValueChange 回传此值） */
  readonly value: string;
  /** 该选项是否禁用（独立于 RadioGroup 的 disabled） */
  readonly disabled?: boolean;
  /** 标签文本（渲染在单选项右侧） */
  readonly label?: React.ReactNode;
  /** 自定义 className（应用到自定义 circle 容器） */
  readonly className?: string;
  /** input id（用于 label 关联） */
  readonly id?: string;
  /** 无障碍标签 */
  readonly 'aria-label'?: string;
}

// =============================================================================
// RadioGroup 组件实现
// =============================================================================

/**
 * RadioGroup 组件（第2波表单组件，Liquid Glass 定制）。
 *
 * 对应 I5 §RadioGroup: ``RadioGroup(props: RadioGroupProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 容器整体过渡使用 snappy spring（D5 §springs.snappy）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 通过 RadioContext 向 RadioGroupItem 共享选中状态
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=toggle-switch）
 *
 * @param props RadioGroup 组件配置（含 value/onValueChange + Liquid Glass 扩展字段）
 * @returns 渲染后的 RadioGroup
 */
export const RadioGroup = React.forwardRef<HTMLDivElement, RadioGroupProps>(
  function RadioGroup(
    {
      className,
      value,
      onValueChange,
      children,
      name,
      disabled = false,
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

    // 获取 Framer Motion variants（替换 shadcn 默认 Tailwind transition）
    // RadioGroup 使用 snappy spring 作为默认入场/出场动画
    const resolvedVariants: Variants | undefined =
      motionVariants ??
      (glassVariant
        ? getComponentMotionVariants({
            componentName: 'RadioGroup',
            springKey: glassVariant,
          })
        : undefined);

    // 构建 RadioGroup 容器 className（通过 className 消费 token，不硬编码颜色）
    const groupBaseClassName = cn(
      'inline-flex flex-col gap-2 p-[var(--radio-group-padding)]',
      'rounded-[var(--radio-group-radius)]',
      'bg-[var(--radio-group-bg)]',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      className,
    );

    // 注入 glass-panel 类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制）
    const composedClassName = cn(groupBaseClassName, glassPanelClass);

    // 构造 RadioContext 值（向 RadioGroupItem 共享选中状态 + 变更回调 + name + disabled）
    const contextValue: RadioContextValue = {
      value,
      onValueChange,
      name,
      disabled,
    };

    return (
      <RadioContext.Provider value={contextValue}>
        <motion.div
          ref={ref}
          role="radiogroup"
          className={composedClassName}
          // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
          data-glass={glassAttributes['data-glass'] ?? undefined}
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
          // 仅当调用方提供 motionVariants 或 glassVariant 时注入 variants
          {...(resolvedVariants ? { variants: resolvedVariants } : {})}
          {...props}
        >
          {children}
        </motion.div>
      </RadioContext.Provider>
    );
  },
);

RadioGroup.displayName = 'RadioGroup';

// =============================================================================
// RadioGroupItem 组件实现
// =============================================================================

/**
 * RadioGroupItem 组件（RadioGroup 的子元素，单个单选项）。
 *
 * 必须作为 RadioGroup 的子元素使用。通过 RadioContext 获取当前选中状态:
 *   - selected = context.value === item.value
 *   - 点击触发 context.onValueChange(item.value)
 *
 * 勾选动画同 Checkbox: SVG circle + snappy spring（scale 0→1 动画）。
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=toggle-switch）
 */
export const RadioGroupItem = React.forwardRef<HTMLInputElement, RadioGroupItemProps>(
  function RadioGroupItem(
    {
      className,
      value,
      disabled: itemDisabled = false,
      label,
      id,
      'aria-label': ariaLabel,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    // 从 RadioContext 获取当前选中状态 + 变更回调 + name + 整组 disabled
    const context = React.useContext(RadioContext);
    const selected = context.value === value;
    const disabled = itemDisabled || context.disabled;

    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // 获取选中圆点动画的 snappy spring transition
    // RadioGroup 默认 spring 为 snappy（getDefaultComponentSpring('RadioGroup') => 'snappy'）
    const dotSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('RadioGroup'),
    );

    // 选中圆点 variants（SVG circle scale 0→1 动画 + snappy spring）
    // 若调用方提供 motionVariants 则直接使用，否则使用默认 scale variants
    const dotVariants: Variants =
      motionVariants ??
      ({
        unselected: { scale: 0, opacity: 0, transition: dotSpring },
        selected: { scale: 1, opacity: 1, transition: dotSpring },
      } as Variants);

    // change 事件处理: 点击该项即选中（radio 语义），回传该选项 value
    const handleChange = () => {
      context.onValueChange?.(value);
    };

    // 构建自定义 circle 容器 className（通过 className 消费 token，不硬编码颜色）
    const circleClassName = cn(
      'relative inline-flex h-5 w-5 shrink-0 items-center justify-center',
      'rounded-full border-2',
      'bg-[var(--radio-bg)] border-[var(--radio-border)]',
      selected && 'border-[var(--radio-checked-border)]',
      'focus-within:ring-2 focus-within:ring-[var(--color-accent)] focus-within:ring-offset-2',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      disabled && 'opacity-50 cursor-not-allowed',
      className,
    );

    // 注入 glass-panel 类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制）
    const composedCircleClassName = cn(circleClassName, glassPanelClass);

    return (
      <label
        className={cn(
          'inline-flex items-center gap-2',
          disabled ? 'cursor-not-allowed' : 'cursor-pointer',
        )}
      >
        <span
          className={composedCircleClassName}
          // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
          data-glass={glassAttributes['data-glass'] ?? undefined}
        >
          {/* 隐藏原生 radio input（保留无障碍属性 + 表单提交能力） */}
          <input
            ref={ref}
            type="radio"
            className="sr-only"
            checked={selected}
            onChange={handleChange}
            disabled={disabled}
            name={context.name}
            value={value}
            id={id}
            aria-label={ariaLabel}
            {...props}
          />
          {/* SVG 选中圆点（scale 动画 + snappy spring） */}
          <motion.svg
            viewBox="0 0 24 24"
            className="h-3.5 w-3.5 pointer-events-none fill-[var(--radio-dot-color)]"
            aria-hidden="true"
          >
            <motion.circle
              cx="12"
              cy="12"
              r="5"
              variants={dotVariants}
              animate={selected ? 'selected' : 'unselected'}
              initial={false}
              style={{ transformOrigin: 'center', transformBox: 'fill-box' }}
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

RadioGroupItem.displayName = 'RadioGroupItem';
