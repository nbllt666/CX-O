/**
 * @file select.tsx — Select 组件（第2波表单组件，Liquid Glass 定制）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波2 表单组件
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\select.tsx
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §Select + §SelectProps + §GlassComponentProps
 *   - D1 frontend_design_tokens.schema.json §component.select（token 消费，不硬编码颜色）
 *   - D2 glass_tier_config.schema.json §tiers（data-glass-tier 属性值）
 *   - D3 theme.schema.json（双主题通过 CSS 变量自动切换，无需 JS 介入）
 *   - D5 motion_springs.schema.json §springs.snappy（Select 默认 spring，下拉快速响应）
 *   - merged.md §4.2 定制策略 + §4.3 第2波（表单，第4-6周）
 *
 * Liquid Glass 定制（I5 §Select docstring + merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层（I1 GlassRenderer）接管玻璃渲染
 *   - 受控下拉选择器（自定义 listbox 模式，避免引入 @radix-ui/react-select 依赖）
 *   - 下拉打开/关闭使用 Framer Motion AnimatePresence + snappy spring
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 提供 aria 属性（aria-haspopup/aria-expanded/aria-activedescendant 等无障碍支持）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块1 token（通过 className 消费 CSS 变量）
 *   - 仅 import 模块3 springs/variants（通过 motion-variants.ts 工厂）
 *   - 仅 import 模块4 GlassTier 类型（data-glass-tier 属性值）
 *   - 仅 import 本模块基础设施（inject-glass-style / motion-variants / button 的 GlassComponentProps）
 *   - 仅 import 第三方库 react / framer-motion
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press，下拉触发器快速响应）
 * apple-design 对齐: damping=22 / stiffness=420 / mass=0.8（快速响应，低过冲）
 * ============================================================================
 */

import React from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import {
  injectGlassClassName,
  buildGlassDataAttributes,
  isValidGlassTier,
} from './inject-glass-style';
import {
  getComponentMotionVariants,
  getComponentSpringTransition,
  getDefaultComponentSpring,
} from './motion-variants';
import type { GlassComponentProps } from './button';

// =============================================================================
// SelectOption + SelectProps（对应 I5 §SelectProps）
// =============================================================================

/**
 * Select 选项（对应 I5 §SelectProps.options 数组元素）。
 *
 * label 为展示文本，value 为提交值，disabled 标记该选项不可选。
 */
export interface SelectOption {
  /** 展示文本 */
  readonly label: string;
  /** 提交值 */
  readonly value: string;
  /** 是否禁用该选项 */
  readonly disabled?: boolean;
}

/**
 * Select 组件 props（对应 I5 §SelectProps）。
 *
 * 继承 GlassComponentProps（Liquid Glass 扩展）。
 * 采用受控模式（value + onValueChange），自定义 listbox 实现。
 */
export interface SelectProps extends GlassComponentProps {
  /** 当前选中值（受控模式，undefined 表示未选中） */
  readonly value?: string;
  /** 选中值变化回调（受控模式） */
  readonly onValueChange?: (value: string) => void;
  /** 选项列表 */
  readonly options: ReadonlyArray<SelectOption>;
  /** 占位文本（未选中时展示） */
  readonly placeholder?: string;
  /** 是否禁用 */
  readonly disabled?: boolean;
  /** 自定义 className（应用到 listbox 容器） */
  readonly className?: string;
  /** 触发器 id（用于 label 关联） */
  readonly id?: string;
  /** 无障碍标签 */
  readonly 'aria-label'?: string;
  /** 无障碍关联标签 id */
  readonly 'aria-labelledby'?: string;
}

// =============================================================================
// 辅助: 计算 active index 移动（跳过 disabled 选项，循环）
// =============================================================================

/**
 * 计算 active index 移动（跳过 disabled 选项，循环到边界回绕）。
 *
 * @param current 当前 active index
 * @param direction 移动方向（1=向下，-1=向上）
 * @param options 选项列表
 * @returns 新的 active index（落在非 disabled 选项上）
 */
function moveActiveIndex(
  current: number,
  direction: 1 | -1,
  options: ReadonlyArray<SelectOption>,
): number {
  const len = options.length;
  if (len === 0) return -1;
  let next = current + direction;
  for (let i = 0; i < len; i++) {
    if (next < 0) next = len - 1;
    else if (next >= len) next = 0;
    if (!options[next]?.disabled) return next;
    next += direction;
  }
  return current;
}

// =============================================================================
// Select 组件实现
// =============================================================================

/**
 * Select 组件（第2波表单组件，Liquid Glass 定制）。
 *
 * 对应 I5 §Select: ``Select(props: SelectProps): JSX.Element``。
 *
 * Liquid Glass 定制（merged.md §4.2）:
 *   - 挂载 data-glass 属性，由 WebGL 层接管玻璃渲染
 *   - 受控下拉选择器（自定义 listbox 模式，避免引入 @radix-ui/react-select 依赖）
 *   - 下拉打开/关闭使用 Framer Motion AnimatePresence + snappy spring
 *   - Framer Motion variants 替换 shadcn 默认 Tailwind transition
 *   - 通过 className + Tailwind utility 消费 token，不硬编码颜色
 *   - 双主题通过 CSS 变量自动切换，无需 JS 介入
 *   - 无障碍: aria-haspopup="listbox" / aria-expanded / aria-activedescendant / role=listbox/option
 *
 * 默认 spring: snappy（D5 §springs.snappy.useCase=button-press）
 *
 * @param props Select 组件配置（含 value/onValueChange/options + Liquid Glass 扩展字段）
 * @returns 渲染后的 Select
 */
export const Select = React.forwardRef<HTMLDivElement, SelectProps>(
  function Select(
    {
      className,
      value,
      onValueChange,
      options,
      placeholder = '请选择',
      disabled = false,
      id,
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
    const [open, setOpen] = React.useState(false);
    const [activeIndex, setActiveIndex] = React.useState(-1);
    const containerRef = React.useRef<HTMLDivElement | null>(null);
    // 稳定的唯一前缀，用于 option id 生成（aria-activedescendant 关联）
    const reactId = React.useId();

    // 合并内部容器 ref 与外部 forwarded ref
    const setContainerRef = React.useCallback(
      (node: HTMLDivElement | null) => {
        containerRef.current = node;
        if (!ref) return;
        if (typeof ref === 'function') {
          ref(node);
        } else {
          ref.current = node;
        }
      },
      [ref],
    );

    // 选中项索引
    const selectedIndex = React.useMemo(() => {
      if (value === undefined) return -1;
      return options.findIndex((opt) => opt.value === value);
    }, [value, options]);

    const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : undefined;
    const displayLabel = selectedOption ? selectedOption.label : placeholder;

    // 打开时初始化 activeIndex（优先停在选中项，否则第一项）
    React.useEffect(() => {
      if (open) {
        setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
      }
    }, [open, selectedIndex]);

    // 点击外部关闭下拉
    React.useEffect(() => {
      if (!open) return;
      function handlePointerDown(e: MouseEvent) {
        const target = e.target as Node;
        if (containerRef.current && !containerRef.current.contains(target)) {
          setOpen(false);
        }
      }
      document.addEventListener('mousedown', handlePointerDown);
      return () => document.removeEventListener('mousedown', handlePointerDown);
    }, [open]);

    // 获取 Framer Motion variants（替换 shadcn 默认 Tailwind transition）
    // Select 使用 snappy spring；dropdown 使用 y:-4→0 的下拉感（通过 states 覆写）
    // resolvedVariants 同时服务触发器（hover/press）与下拉面板（initial/animate/exit）
    const resolvedVariants: Variants =
      motionVariants ??
      getComponentMotionVariants({
        componentName: 'Select',
        springKey: glassVariant,
        states: {
          initial: { opacity: 0, scale: 0.96, y: -4 },
          animate: { opacity: 1, scale: 1, y: 0 },
          exit: { opacity: 0, scale: 0.96, y: -4 },
        },
      });

    // chevron 旋转动画的 snappy spring transition
    const chevronSpring = getComponentSpringTransition(
      glassVariant ?? getDefaultComponentSpring('Select'),
    );
    const chevronVariants: Variants = {
      closed: { rotate: 0, transition: chevronSpring },
      open: { rotate: 180, transition: chevronSpring },
    } as Variants;

    // 选中某选项
    const handleSelect = (optionValue: string) => {
      onValueChange?.(optionValue);
      setOpen(false);
    };

    // 触发器点击: 切换打开状态
    const handleTriggerClick = () => {
      if (disabled) return;
      setOpen((prev) => !prev);
    };

    // 选项点击
    const handleOptionClick = (option: SelectOption) => {
      if (option.disabled) return;
      handleSelect(option.value);
    };

    // 键盘导航（挂在触发器上，focus 停留在触发器，aria-activedescendant 跟踪 active option）
    const handleKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
      if (disabled) return;
      switch (e.key) {
        case 'Enter':
        case ' ': {
          e.preventDefault();
          if (!open) {
            setOpen(true);
          } else {
            const active = options[activeIndex];
            if (active && !active.disabled) {
              handleSelect(active.value);
            }
          }
          break;
        }
        case 'ArrowDown': {
          e.preventDefault();
          if (!open) {
            setOpen(true);
          } else {
            setActiveIndex((prev) => moveActiveIndex(prev, 1, options));
          }
          break;
        }
        case 'ArrowUp': {
          e.preventDefault();
          if (!open) {
            setOpen(true);
          } else {
            setActiveIndex((prev) => moveActiveIndex(prev, -1, options));
          }
          break;
        }
        case 'Home': {
          if (open) {
            e.preventDefault();
            setActiveIndex(0);
          }
          break;
        }
        case 'End': {
          if (open) {
            e.preventDefault();
            setActiveIndex(options.length - 1);
          }
          break;
        }
        case 'Escape': {
          if (open) {
            e.preventDefault();
            setOpen(false);
          }
          break;
        }
        case 'Tab': {
          if (open) setOpen(false);
          break;
        }
      }
    };

    // 构建 data-glass + data-glass-tier 属性（由 WebGL 层接管渲染）
    const validTier = isValidGlassTier(glassTier) ? glassTier : undefined;
    const glassAttributes = buildGlassDataAttributes(dataGlass, validTier);

    // option id 生成器（供 aria-activedescendant 关联）
    const optionId = (index: number) => `${reactId}-option-${index}`;

    // 触发器 className（通过 className 消费 token，不硬编码颜色）
    const triggerBaseClassName = cn(
      'relative w-full inline-flex items-center justify-between gap-2',
      'px-[var(--select-padding-x)] py-[var(--select-padding-y)]',
      'text-[var(--select-text)] text-[var(--select-font-size)]',
      'bg-[var(--select-bg)] border border-[var(--select-border)]',
      'rounded-[var(--select-radius)]',
      'focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2',
      'transition-none', // 移除 shadcn 默认 Tailwind transition，由 Framer Motion 接管
      disabled && 'opacity-50 cursor-not-allowed',
      !selectedOption && 'text-[var(--select-placeholder)]',
      className,
    );

    // 注入 glass 样式类（仅当调用方提供 glassTier 时注入 CSS 降级样式）
    const composedTriggerClassName = validTier
      ? injectGlassClassName(triggerBaseClassName, validTier)
      : triggerBaseClassName;

    // 下拉面板 className
    const dropdownClassName = cn(
      'absolute z-50 top-full left-0 right-0 mt-1',
      'max-h-60 overflow-y-auto',
      'py-1',
      'bg-[var(--select-dropdown-bg)]',
      'border border-[var(--select-dropdown-border)]',
      'rounded-[var(--select-radius)]',
      'shadow-[var(--select-dropdown-shadow)]',
      'transition-none',
    );

    return (
      <div ref={setContainerRef} className="relative w-full" {...props}>
        <motion.button
          type="button"
          id={id}
          className={composedTriggerClassName}
          // data-glass 属性（由 WebGL 层 GlassRenderer 扫描接管渲染）
          data-glass={glassAttributes['data-glass'] ?? undefined}
          data-glass-tier={glassAttributes['data-glass-tier'] ?? undefined}
          // Framer Motion variants（替换 shadcn 默认 Tailwind transition）
          variants={resolvedVariants}
          whileHover={disabled ? undefined : 'hover'}
          whileTap={disabled ? undefined : 'press'}
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-activedescendant={
            open && activeIndex >= 0 ? optionId(activeIndex) : undefined
          }
          aria-label={ariaLabel}
          aria-labelledby={ariaLabelledBy}
          onClick={handleTriggerClick}
          onKeyDown={handleKeyDown}
        >
          <span className="truncate">{displayLabel}</span>
          <motion.span
            className="inline-flex shrink-0"
            variants={chevronVariants}
            animate={open ? 'open' : 'closed'}
            initial={false}
            aria-hidden="true"
          >
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M6 9l6 6 6-6" />
            </svg>
          </motion.span>
        </motion.button>

        {/* 下拉面板: AnimatePresence + snappy spring 管理入场/出场 */}
        <AnimatePresence>
          {open && (
            <motion.ul
              className={dropdownClassName}
              role="listbox"
              variants={resolvedVariants}
              initial="initial"
              animate="animate"
              exit="exit"
            >
              {options.map((option, index) => {
                const isSelected = selectedIndex === index;
                const isActive = activeIndex === index;
                const optionClassName = cn(
                  'px-3 py-1.5 cursor-pointer text-sm',
                  'text-[var(--select-dropdown-text)]',
                  'flex items-center justify-between gap-2',
                  'transition-none',
                  option.disabled && 'opacity-50 cursor-not-allowed',
                  isActive && !option.disabled && 'bg-[var(--select-option-hover-bg)]',
                  isSelected && 'bg-[var(--select-option-selected-bg)]',
                );
                return (
                  <li
                    key={option.value}
                    id={optionId(index)}
                    role="option"
                    aria-selected={isSelected}
                    aria-disabled={option.disabled}
                    className={optionClassName}
                    onClick={() => handleOptionClick(option)}
                    onMouseEnter={() => !option.disabled && setActiveIndex(index)}
                  >
                    <span className="truncate">{option.label}</span>
                    {isSelected && (
                      <svg
                        className="h-4 w-4 shrink-0 text-[var(--select-check-color)]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2.5}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        aria-hidden="true"
                      >
                        <path d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </li>
                );
              })}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>
    );
  },
);

Select.displayName = 'Select';
