/**
 * @file tabs.tsx — Tabs 组件（第3波数据展示组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波3 数据展示组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\tabs.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Tabs + §TabsProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.tabs（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（Tabs 默认 spring，Tab 切换快速响应）
 *   - merged.md §4.2 定制策略 + §4.3 第3波（数据展示，第7-9周）
 *
 * Liquid Glass 定制（I5 §Tabs docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 受控 Tab 容器 + TabList + TabTrigger + TabContent 子组件组合 API
 *   - 通过 TabsContext 共享当前选中值
 *   - Tab 切换使用 Framer Motion layoutId 实现 indicator 滑动动画（apple-design §spatialConsistency）
 *   - TabContent 切换使用 fade + slide 动画（AnimatePresence 管理）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 无障碍: role="tablist"/role="tab"/role="tabpanel" + aria-selected/aria-controls/aria-labelledby
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，Tab 切换快速响应）
 * apple-design 对齐: §pointerDownImmediate（pointer-down 即时反馈）+ §spatialConsistency（layoutId indicator 滑动）
 * ============================================================================
 */

import React from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  glassPanelClass,
  buildGlassDataAttributes,
} from './inject-glass-style';
import {
  getComponentMotionVariants,
  getComponentSpringTransition,
  getDefaultComponentSpring,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// TabsContext（Tabs → TabsTrigger/TabsContent 选中状态共享）
// =============================================================================

/**
 * Tabs 向子组件提供的上下文值。
 *
 * TabsTrigger 通过 context 获取当前选中值与变更回调，实现 Tab 切换语义。
 * TabsContent 通过 context 判断自身是否激活，决定是否渲染。
 */
interface TabsContextValue {
  /** 当前选中 Tab 的 value（受控模式） */
  readonly value: string | undefined;
  /** 选中值变化回调（受控模式） */
  readonly onValueChange?: (value: string) => void;
  /** Tab 方向（horizontal/vertical） */
  readonly orientation: 'horizontal' | 'vertical';
  /** layoutId 前缀（用于 indicator 滑动动画，同组 Tabs 共享唯一 layoutId） */
  readonly layoutId: string;
}

/**
 * TabsContext 默认值（子组件在 Tabs 外使用时的降级值）。
 *
 * 正常使用时 TabsTrigger/TabsContent 必须作为 Tabs 的子元素。
 * 此默认值仅用于防误用避免运行时崩溃。
 */
const DEFAULT_TABS_CONTEXT: TabsContextValue = {
  value: undefined,
  onValueChange: undefined,
  orientation: 'horizontal',
  layoutId: '__tabs_default_layout',
};

const TabsContext = React.createContext<TabsContextValue>(DEFAULT_TABS_CONTEXT);

// =============================================================================
// TabsProps / TabsListProps / TabsTriggerProps / TabsContentProps（对应 I5 §TabsProps）
// =============================================================================

/**
 * Tabs 组件 props（对应 I5 §TabsProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 受控 Tab 容器，通过 TabsContext 向子组件共享选中状态。
 */
export interface TabsProps extends GlassComponentProps {
  /** 当前选中 Tab 的 value（受控模式） */
  readonly value?: string;
  /** 选中值变化回调（受控模式） */
  readonly onValueChange?: (value: string) => void;
  /** 子元素（应为 TabsList + TabsContent 组合） */
  readonly children?: React.ReactNode;
  /** Tab 方向（horizontal/vertical，默认 horizontal） */
  readonly orientation?: 'horizontal' | 'vertical';
  /** 自定义 className（应用到 Tabs 容器） */
  readonly className?: string;
  /** 默认选中值（非受控模式初始化，受控模式忽略） */
  readonly defaultValue?: string;
}

/**
 * TabsList 组件 props（Tab 触发器列表容器）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * role="tablist" 容器，包含多个 TabsTrigger。
 */
export interface TabsListProps extends GlassComponentProps {
  /** 子元素（应为 TabsTrigger） */
  readonly children?: React.ReactNode;
  /** 自定义 className */
  readonly className?: string;
  /** 无障碍标签 */
  readonly 'aria-label'?: string;
  /** 无障碍关联标签 id */
  readonly 'aria-labelledby'?: string;
}

/**
 * TabsTrigger 组件 props（单个 Tab 触发器）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * role="tab"，通过 TabsContext 获取选中状态。
 */
export interface TabsTriggerProps extends GlassComponentProps {
  /** 该 Tab 的值（选中时 onValueChange 回传此值） */
  readonly value: string;
  /** 子元素（Tab 标签内容） */
  readonly children?: React.ReactNode;
  /** 是否禁用该 Tab */
  readonly disabled?: boolean;
  /** 自定义 className */
  readonly className?: string;
}

/**
 * TabsContent 组件 props（Tab 内容面板）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * role="tabpanel"，仅当对应 Tab 选中时渲染。
 */
export interface TabsContentProps extends GlassComponentProps {
  /** 该内容面板对应的 Tab value */
  readonly value: string;
  /** 子元素（面板内容） */
  readonly children?: React.ReactNode;
  /** 自定义 className */
  readonly className?: string;
}

// =============================================================================
// Tabs 组件实现
// =============================================================================

/**
 * Tabs 组件（第3波数据展示组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Tabs: ``Tabs(props: TabsProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - Tab 切换使用 snappy spring（快速响应，apple-design §pointerDownImmediate）
 *   - layoutId indicator 滑动动画（apple-design §spatialConsistency）
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 通过 TabsContext 向子组件共享选中状态
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press）
 *
 * @param props Tabs 组件配置（含 value/onValueChange + Liquid Glass 扩展字段）
 * @returns 渲染后的 Tabs
 */
export const Tabs = React.forwardRef<HTMLDivElement, TabsProps>(
  function Tabs(
    {
      className,
      value: controlledValue,
      onValueChange,
      children,
      orientation = 'horizontal',
      defaultValue,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    // 非受控模式内部状态（受控模式优先使用 controlledValue）
    const [internalValue, setInternalValue] = React.useState<string | undefined>(
      defaultValue,
    );
    const isControlled = controlledValue !== undefined;
    const currentValue = isControlled ? controlledValue : internalValue;

    // 选中值变化处理（受控 + 非受控兼容）
    const handleValueChange = React.useCallback(
      (nextValue: string) => {
        if (!isControlled) {
          setInternalValue(nextValue);
        }
        onValueChange?.(nextValue);
      },
      [isControlled, onValueChange],
    );

    // 稳定的 layoutId 前缀（用于 indicator 滑动动画，同组 Tabs 共享唯一 layoutId）
    const reactId = React.useId();
    const indicatorLayoutId = `tabs-indicator-${reactId}`;

    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // 获取 Framer Motion variants（替换 shadcn 默认 Tailwind transition）
    const resolvedVariants: Variants | undefined =
      motionVariants ??
      (glassVariant
        ? getComponentMotionVariants({
            componentName: 'Tabs',
            springKey: glassVariant,
          })
        : undefined);

    // 构建 Tabs 容器 className（通过 className 消费 token，不硬编码颜色）
    const tabsBaseClassName = cn(
      'inline-flex',
      orientation === 'horizontal' ? 'flex-col' : 'flex-row',
      'gap-2',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      className,
    );

    // 注入 glass-panel 类（CSS 兜底 + WebGL 主体切换由 .webgl-active class 控制）
    const composedClassName = cn(tabsBaseClassName, glassPanelClass);

    // 构造 TabsContext 值
    const contextValue: TabsContextValue = {
      value: currentValue,
      onValueChange: handleValueChange,
      orientation,
      layoutId: indicatorLayoutId,
    };

    return (
      <TabsContext.Provider value={contextValue}>
        <motion.div
          ref={ref}
          className={composedClassName}
          // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
          data-glass={glassAttributes['data-glass'] ?? undefined}
          {...(resolvedVariants ? { variants: resolvedVariants } : {})}
          {...props}
        >
          {children}
        </motion.div>
      </TabsContext.Provider>
    );
  },
);

Tabs.displayName = 'Tabs';

// =============================================================================
// TabsList 组件实现
// =============================================================================

/**
 * TabsList 组件（Tab 触发器列表容器，role="tablist"）。
 *
 * 通过 className 消费 token，不硬编码颜色。
 */
export const TabsList = React.forwardRef<HTMLDivElement, TabsListProps>(
  function TabsList(
    {
      className,
      children,
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
    const context = React.useContext(TabsContext);

    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // snappy spring transition（用于 indicator 滑动）
    const indicatorSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Tabs'),
    );

    // indicator 滑动 variants（layoutId 共享，snappy spring 驱动滑动）
    const indicatorVariants: Variants = {
      initial: { opacity: 0 },
      animate: { opacity: 1, transition: indicatorSpring },
      exit: { opacity: 0, transition: indicatorSpring },
    } as Variants;

    // 构建 TabsList className（通过 className 消费 token，不硬编码颜色）
    const listBaseClassName = cn(
      'inline-flex items-center gap-1',
      'p-1',
      'rounded-[var(--tabs-radius)]',
      'bg-[var(--tabs-bg)]',
      'border border-[var(--tabs-border)]',
      'transition-none',
      context.orientation === 'vertical' && 'flex-col',
      className,
    );

    const composedClassName = cn(listBaseClassName, glassPanelClass);

    // resolvedVariants 用于 TabsList 容器入场（可选）
    const resolvedVariants: Variants | undefined =
      motionVariants ??
      (glassVariant
        ? getComponentMotionVariants({
            componentName: 'Tabs',
            springKey: glassVariant,
          })
        : undefined);

    return (
      <motion.div
        ref={ref}
        role="tablist"
        aria-orientation={context.orientation}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        className={composedClassName}
        data-glass={glassAttributes['data-glass'] ?? undefined}
        {...(resolvedVariants ? { variants: resolvedVariants } : {})}
        {...props}
      >
        {/* indicator 滑动层: 使用 layoutId 实现选中 Tab 背景滑动（apple-design §spatialConsistency） */}
        {context.value !== undefined && (
          <motion.span
            layoutId={context.layoutId}
            className="pointer-events-none absolute inset-0 rounded-[var(--tabs-radius)] bg-[var(--tabs-indicator)]"
            variants={indicatorVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            style={{ zIndex: 0 }}
            aria-hidden="true"
          />
        )}
        {/* TabsTrigger 列表（提升 z-index 使其在 indicator 之上） */}
        <div
          className={cn(
            'relative flex',
            context.orientation === 'vertical' ? 'flex-col' : 'flex-row',
            'gap-1',
          )}
          style={{ zIndex: 1 }}
        >
          {children}
        </div>
      </motion.div>
    );
  },
);

TabsList.displayName = 'TabsList';

// =============================================================================
// TabsTrigger 组件实现
// =============================================================================

/**
 * TabsTrigger 组件（单个 Tab 触发器，role="tab"）。
 *
 * 必须作为 TabsList 的子元素使用。通过 TabsContext 获取当前选中状态:
 *   - selected = context.value === trigger.value
 *   - 点击触发 context.onValueChange(trigger.value)
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，pointer-down 即时反馈）
 */
export const TabsTrigger = React.forwardRef<HTMLButtonElement, TabsTriggerProps>(
  function TabsTrigger(
    {
      className,
      value,
      children,
      disabled = false,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    const context = React.useContext(TabsContext);
    const selected = context.value === value;

    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // snappy spring transition（用于 press 即时反馈）
    const pressSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Tabs'),
    );

    // TabsTrigger 交互态 variants（press scale 0.96，apple-design §pointerDownImmediate）
    const triggerVariants: Variants =
      motionVariants ??
      ({
        default: { scale: 1, transition: pressSpring },
        hover: { scale: 1.02, transition: pressSpring },
        press: { scale: 0.96, transition: pressSpring },
      } as Variants);

    // 点击处理
    const handleClick = () => {
      if (disabled) return;
      context.onValueChange?.(value);
    };

    // 键盘导航（ArrowLeft/ArrowRight/ArrowUp/ArrowDown/Home/End）
    const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
      if (disabled) return;
      // 方向键导航由 TabsList 层或外部 roving tabindex 管理
      // 这里仅处理 Enter/Space 触发选择
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        context.onValueChange?.(value);
      }
    };

    // 构建 TabsTrigger className（通过 className 消费 token，不硬编码颜色）
    const triggerBaseClassName = cn(
      'inline-flex items-center justify-center whitespace-nowrap',
      'px-3 py-1.5 text-sm font-medium',
      'rounded-[var(--tabs-radius)]',
      'select-none outline-none',
      'focus-visible:ring-2 focus-visible:ring-[var(--color-accent)] focus-visible:ring-offset-2',
      'transition-none',
      selected
        ? 'text-[var(--tabs-trigger-active-text)]'
        : 'text-[var(--tabs-text)]',
      !selected && 'hover:text-[var(--tabs-trigger-hover-text)]',
      disabled && 'opacity-50 cursor-not-allowed',
      !disabled && 'cursor-pointer',
      className,
    );

    const composedClassName = cn(triggerBaseClassName, glassPanelClass);

    return (
      <motion.button
        ref={ref}
        type="button"
        role="tab"
        aria-selected={selected}
        aria-controls={`tabs-content-${value}`}
        // 当未选中时设为 -1，选中时设为 0（roving tabindex 模式）
        tabIndex={selected ? 0 : -1}
        disabled={disabled}
        className={composedClassName}
        data-glass={glassAttributes['data-glass'] ?? undefined}
        variants={triggerVariants}
        initial={false}
        animate="default"
        whileHover={disabled ? undefined : 'hover'}
        whileTap={disabled ? undefined : 'press'}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        {...props}
      >
        {children}
      </motion.button>
    );
  },
);

TabsTrigger.displayName = 'TabsTrigger';

// =============================================================================
// TabsContent 组件实现
// =============================================================================

/**
 * TabsContent 组件（Tab 内容面板，role="tabpanel"）。
 *
 * 仅当对应 Tab 选中时渲染。切换使用 fade + slide 动画（AnimatePresence 管理）。
 */
export const TabsContent = React.forwardRef<HTMLDivElement, TabsContentProps>(
  function TabsContent(
    {
      className,
      value,
      children,
      dataGlass = true,
      glassTier,
      glassVariant,
      motionVariants,
      ...props
    },
    ref,
  ) {
    const context = React.useContext(TabsContext);
    const selected = context.value === value;

    // 构建 data-glass 属性（WebGL LiquidGlassHost 扫描 [data-glass="true"] 元素）
    const glassAttributes = buildGlassDataAttributes(dataGlass);

    // snappy spring transition（用于内容切换 fade + slide）
    const contentSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Tabs'),
    );

    // 内容面板切换 variants（fade + slide，方向跟随 orientation）
    const slideOffset = context.orientation === 'horizontal' ? 8 : 8;
    const contentVariants: Variants =
      motionVariants ??
      ({
        initial: { opacity: 0, x: slideOffset },
        animate: { opacity: 1, x: 0, transition: contentSpring },
        exit: { opacity: 0, x: -slideOffset, transition: contentSpring },
      } as Variants);

    // 构建 TabsContent className（通过 className 消费 token，不硬编码颜色）
    const contentBaseClassName = cn(
      'mt-2',
      'rounded-[var(--tabs-content-radius)]',
      'bg-[var(--tabs-content-bg)]',
      'p-4',
      'text-[var(--tabs-content-text)]',
      'transition-none',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-accent)]',
      className,
    );

    const composedClassName = cn(contentBaseClassName, glassPanelClass);

    return (
      <AnimatePresence mode="wait">
        {selected && (
          <motion.div
            ref={ref}
            id={`tabs-content-${value}`}
            role="tabpanel"
            aria-labelledby={`tabs-trigger-${value}`}
            tabIndex={0}
            className={composedClassName}
            data-glass={glassAttributes['data-glass'] ?? undefined}
            variants={contentVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            {...props}
          >
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    );
  },
);

TabsContent.displayName = 'TabsContent';
