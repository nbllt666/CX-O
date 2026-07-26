/**
 * @file grid-system.tsx
 * @module 模块9a/响应式断点层
 *
 * 12 列响应式栅格系统组件。基于 CSS Grid 实现，支持响应式 span/offset。
 *
 * 契约对齐：
 * - 列数 12 对齐 D6 gridSystem.columns（const=12）+ Tailwind grid-cols-12
 * - gutter 分级对齐 D6 gridSystem.gutter（lg+ 24 / md 16 / sm 12）+ C3 grid
 * - maxContentWidth 1440 对齐 D6 gridSystem.maxContentWidth
 * - gutter 值消费模块1 的 CSS 变量 var(--semantic-spacing-*)，fallback 对齐 C3 grid
 * - 错误码 FE-RES-002 对齐 C3 errorCodes.gridCalculationError（fallback-to-default-layout）
 *
 * 跨模块约束：
 * - gutter 通过 var(--semantic-spacing-*) 消费模块1（Token 设计系统层）的 spacing token
 * - 不 import 模块1-8 的任何内部实现（横切层不得反向依赖业务模块）
 * - 模块1 token 未产出时，fallback 值保证栅格系统正常工作
 *
 * @example 基础栅格
 * ```tsx
 * import { Row, Col } from '@/lib/responsive/grid-system';
 *
 * function BasicGrid() {
 *   return (
 *     <Row>
 *       <Col span={6}>左侧 6 列</Col>
 *       <Col span={6}>右侧 6 列</Col>
 *     </Row>
 *   );
 * }
 * ```
 *
 * @example 响应式 span
 * ```tsx
 * function ResponsiveGrid() {
 *   return (
 *     <Row gutter="auto">
 *       <Col span={{ sm: 12, md: 6, lg: 4, xl: 3 }}>
 *         响应式列：手机全宽 / 平板半宽 / 桌面 1/3 / 大屏 1/4
 *       </Col>
 *     </Row>
 *   );
 * }
 * ```
 *
 * @example Dashboard 三栏布局（对齐 D6 dashboardLayout.lgPlus）
 * ```tsx
 * function DashboardLayout() {
 *   return (
 *     <Row maxContentWidth>
 *       <Col span={{ lg: 2 }}><CharacterSidebar /></Col>
 *       <Col span={{ lg: 8 }}><MainContent /></Col>
 *       <Col span={{ lg: 2 }}><AuxiliaryPanel /></Col>
 *     </Row>
 *   );
 * }
 * ```
 */

import type { CSSProperties, ReactNode } from 'react';

import {
  BREAKPOINT_ORDER,
  GUTTER,
  MAX_CONTENT_WIDTH,
  GRID_COLUMNS,
  RESPONSIVE_ERROR_CODES,
  type BreakpointKey,
} from './breakpoints';
import { useBreakpoint } from './use-breakpoint';

// ============================================================================
// 一、类型定义
// ============================================================================

/**
 * gutter 尺寸。对齐 D6 gridSystem.gutter 的三档分级。
 * - 'sm': sm 断点 gutter（12px）
 * - 'md': md 断点 gutter（16px）
 * - 'lg': lg+ 断点 gutter（24px）
 * - 'auto': 根据当前断点自动选择（默认）
 */
export type GutterSize = 'sm' | 'md' | 'lg' | 'auto';

/**
 * gutter 值类型。支持多种指定方式：
 * - GutterSize: 尺寸关键词（消费 CSS 变量）
 * - number: 固定 px 值
 * - [number, number]: [rowGap, colGap] 分别指定
 */
export type GutterValue = GutterSize | number | [number, number];

/**
 * 响应式值类型。支持单一值或按断点指定不同值。
 *
 * @example
 * ```ts
 * const span: ResponsiveValue<number> = 6; // 所有断点都是 6
 * const span: ResponsiveValue<number> = { sm: 12, md: 6, lg: 4 }; // 按断点指定
 * ```
 */
export type ResponsiveValue<T> = T | Partial<Record<BreakpointKey, T>>;

/**
 * Col 的 span 值。1-12 的数字或响应式对象。
 */
export type ColSpan = ResponsiveValue<number>;

/**
 * Col 的 offset 值。0-11 的数字或响应式对象。
 */
export type ColOffset = ResponsiveValue<number>;

/**
 * Row 的水平对齐方式。映射到 CSS Grid justify-items。
 */
export type RowJustify = 'start' | 'center' | 'end' | 'stretch';

/**
 * Row 的垂直对齐方式。映射到 CSS Grid align-items。
 */
export type RowAlign = 'start' | 'center' | 'end' | 'stretch' | 'baseline';

/**
 * Row 组件 props。
 */
export interface RowProps {
  /**
   * 栅格间距。
   *
   * - 'auto'（默认）：根据当前断点自动选择（lg+ 24px / md 16px / sm 12px）
   * - 'sm' / 'md' / 'lg'：固定使用某档 gutter（消费 var(--semantic-spacing-*)）
   * - number：固定 px 值
   * - [rowGap, colGap]：分别指定行列间距
   *
   * 对齐 D6 gridSystem.gutter + C3 grid.gutterLgPlus/gutterMdMinus/gutterSmMinus。
   */
  gutter?: GutterValue;

  /**
   * 水平对齐。映射到 CSS Grid justify-items。
   * @default 'stretch'
   */
  justify?: RowJustify;

  /**
   * 垂直对齐。映射到 CSS Grid align-items。
   * @default 'stretch'
   */
  align?: RowAlign;

  /**
   * 是否限制最大内容宽度。
   *
   * true 时设置 max-width: 1440px + margin: 0 auto（左右居中留白）。
   * 对齐 D6 gridSystem.maxContentWidth = 1440。
   * @default false
   */
  maxContentWidth?: boolean;

  /** 子元素（Col 组件） */
  children?: ReactNode;

  /** 自定义 className */
  className?: string;

  /** 自定义内联样式 */
  style?: CSSProperties;
}

/**
 * Col 组件 props。
 */
export interface ColProps {
  /**
   * 占据的列数（1-12）。
   *
   * 支持响应式对象，按断点指定不同列数。
   * 解析规则：从当前断点开始往小断点方向找，取第一个有定义的值。
   *
   * @example
   * ```tsx
   * <Col span={6} /> // 所有断点占 6 列
   * <Col span={{ sm: 12, md: 6, lg: 4 }} /> // 手机 12 列 / 平板 6 列 / 桌面 4 列
   * ```
   *
   * @default 12（全宽）
   */
  span?: ColSpan;

  /**
   * 左侧偏移列数（0-11）。
   *
   * 支持响应式对象，解析规则同 span。
   *
   * @example
   * ```tsx
   * <Col span={6} offset={3} /> // 占 6 列，左侧空 3 列（居中效果）
   * ```
   *
   * @default 0
   */
  offset?: ColOffset;

  /** 子元素 */
  children?: ReactNode;

  /** 自定义 className */
  className?: string;

  /** 自定义内联样式 */
  style?: CSSProperties;
}

// ============================================================================
// 二、响应式值解析
// ============================================================================

/**
 * 解析响应式值。
 *
 * 如果 value 是单一值（非对象），直接返回。
 * 如果 value 是响应式对象，从当前断点开始往小断点方向找，取第一个有定义的值。
 *
 * 解析规则对齐 Tailwind min-width 语义：
 * - 当前断点 current = 'lg' 表示视口 >= 1024
 * - 此时 sm / md / lg 的样式都生效，取最大断点（lg）的值
 * - 如果 lg 没定义，取 md 的值；如果 md 没定义，取 sm 的值
 *
 * @param value - 响应式值（单一值或对象）
 * @param current - 当前断点
 * @param defaultValue - 默认值（所有断点都未定义时返回）
 * @returns 解析后的值
 */
function resolveResponsiveValue<T>(
  value: ResponsiveValue<T>,
  current: BreakpointKey,
  defaultValue: T
): T {
  // 非对象（单一值）：直接返回
  if (typeof value !== 'object' || value === null) {
    return value as T;
  }

  // 响应式对象：从 current 开始往小断点方向找
  // BREAKPOINT_ORDER = ['sm', 'md', 'lg', 'xl', '2xl']（从小到大）
  const currentIdx = BREAKPOINT_ORDER.indexOf(current);

  // 从 currentIdx 往 0 的方向找（从大到小）
  for (let i = currentIdx; i >= 0; i--) {
    const key = BREAKPOINT_ORDER[i];
    const v = (value as Partial<Record<BreakpointKey, T>>)[key];
    if (v !== undefined) {
      return v;
    }
  }

  return defaultValue;
}

// ============================================================================
// 三、gutter 解析
// ============================================================================

/**
 * gutter 尺寸到 CSS 变量名的映射。
 *
 * 消费模块1（Token 设计系统层）的 spacing token。
 * fallback 值对齐 D6 gridSystem.gutter + C3 grid。
 */
const GUTTER_CSS_VAR_MAP: Record<'sm' | 'md' | 'lg', { varName: string; fallback: number }> = {
  sm: { varName: '--semantic-spacing-sm', fallback: GUTTER.sm },
  md: { varName: '--semantic-spacing-md', fallback: GUTTER.md },
  lg: { varName: '--semantic-spacing-lg', fallback: GUTTER.lgPlus },
};

/**
 * 根据 gutter 尺寸生成 CSS gap 值。
 *
 * 优先消费模块1 的 CSS 变量 var(--semantic-spacing-*)，
 * 模块1 未产出时使用 fallback 值（对齐 C3 grid 配置）。
 *
 * @param size - gutter 尺寸（'sm' | 'md' | 'lg'）
 * @returns CSS gap 值字符串
 */
function getGutterCssValue(size: 'sm' | 'md' | 'lg'): string {
  const { varName, fallback } = GUTTER_CSS_VAR_MAP[size];
  return `var(${varName}, ${fallback}px)`;
}

/**
 * 解析 gutter 值为 CSS gap 属性值。
 *
 * @param gutter - gutter 值
 * @param isAtLeast - 断点判定函数（来自 useBreakpoint）
 * @returns CSS gap 值字符串
 */
function resolveGutter(
  gutter: GutterValue,
  isAtLeast: (key: BreakpointKey) => boolean
): string {
  // 数字：固定 px 值
  if (typeof gutter === 'number') {
    return `${gutter}px`;
  }

  // [rowGap, colGap]：分别指定
  if (Array.isArray(gutter)) {
    const [rowGap, colGap] = gutter;
    return `${rowGap}px ${colGap}px`;
  }

  // GutterSize
  if (gutter === 'auto') {
    // 根据断点自动选择
    const size: 'sm' | 'md' | 'lg' = isAtLeast('lg')
      ? 'lg'
      : isAtLeast('md')
        ? 'md'
        : 'sm';
    return getGutterCssValue(size);
  }

  // 'sm' | 'md' | 'lg'
  return getGutterCssValue(gutter);
}

// ============================================================================
// 四、span/offset 边界检查
// ============================================================================

/**
 * 校验并 clamp span 值到合法范围 [1, GRID_COLUMNS]。
 *
 * 越界时记录 FE-RES-002 警告并 fallback 到默认值。
 *
 * @param span - 原始 span 值
 * @returns 合法的 span 值
 */
function clampSpan(span: number): number {
  if (span < 1 || span > GRID_COLUMNS) {
    console.warn(
      `[${RESPONSIVE_ERROR_CODES.GRID_CALCULATION_ERROR}] ` +
        `Grid span ${span} is out of range [1, ${GRID_COLUMNS}]. ` +
        `Falling back to default span ${GRID_COLUMNS}.`
    );
    return GRID_COLUMNS;
  }
  return span;
}

/**
 * 校验并 clamp offset 值到合法范围 [0, GRID_COLUMNS - 1]。
 *
 * 越界时记录 FE-RES-002 警告并 fallback 到 0。
 *
 * @param offset - 原始 offset 值
 * @returns 合法的 offset 值
 */
function clampOffset(offset: number): number {
  if (offset < 0 || offset >= GRID_COLUMNS) {
    console.warn(
      `[${RESPONSIVE_ERROR_CODES.GRID_CALCULATION_ERROR}] ` +
        `Grid offset ${offset} is out of range [0, ${GRID_COLUMNS - 1}]. ` +
        `Falling back to offset 0.`
    );
    return 0;
  }
  return offset;
}

// ============================================================================
// 五、Row 组件
// ============================================================================

/**
 * Row 栅格容器组件。
 *
 * 基于 CSS Grid 实现 12 列等宽栅格。
 * - grid-template-columns: repeat(12, minmax(0, 1fr))
 * - gap: gutter 值（消费 var(--semantic-spacing-*)）
 *
 * @example
 * ```tsx
 * <Row gutter="auto" justify="center" align="center" maxContentWidth>
 *   <Col span={6}>内容</Col>
 * </Row>
 * ```
 */
export function Row({
  gutter = 'auto',
  justify = 'stretch',
  align = 'stretch',
  maxContentWidth = false,
  children,
  className,
  style,
}: RowProps): JSX.Element {
  const { isAtLeast } = useBreakpoint();

  const gapValue = resolveGutter(gutter, isAtLeast);

  const rowStyle: CSSProperties = {
    display: 'grid',
    gridTemplateColumns: `repeat(${GRID_COLUMNS}, minmax(0, 1fr))`,
    gap: gapValue,
    justifyItems: justify,
    alignItems: align,
    ...(maxContentWidth && {
      maxWidth: `${MAX_CONTENT_WIDTH}px`,
      marginLeft: 'auto',
      marginRight: 'auto',
      width: '100%',
    }),
    ...style,
  };

  return (
    <div className={className} style={rowStyle}>
      {children}
    </div>
  );
}

// ============================================================================
// 六、Col 组件
// ============================================================================

/**
 * Col 栅格子组件。
 *
 * 通过 grid-column 属性占据指定列数，支持响应式 span/offset。
 *
 * CSS Grid 实现：
 * - grid-column: {offset + 1} / span {span}
 * - offset 通过 grid-column-start 实现（左侧空出 offset 列）
 *
 * @example
 * ```tsx
 * <Col span={6} offset={3}>居中 6 列</Col>
 * <Col span={{ sm: 12, md: 6, lg: 4 }}>响应式</Col>
 * ```
 */
export function Col({
  span = GRID_COLUMNS,
  offset = 0,
  children,
  className,
  style,
}: ColProps): JSX.Element {
  const { current } = useBreakpoint();

  // 解析响应式 span/offset
  const resolvedSpan = resolveResponsiveValue(span, current, GRID_COLUMNS);
  const resolvedOffset = resolveResponsiveValue(offset, current, 0);

  // 边界检查 + clamp
  const safeSpan = clampSpan(resolvedSpan);
  const safeOffset = clampOffset(resolvedOffset);

  // 额外检查：offset + span 不能超过总列数
  if (safeOffset + safeSpan > GRID_COLUMNS) {
    console.warn(
      `[${RESPONSIVE_ERROR_CODES.GRID_CALCULATION_ERROR}] ` +
        `Grid offset ${safeOffset} + span ${safeSpan} = ${safeOffset + safeSpan} ` +
        `exceeds total columns ${GRID_COLUMNS}. Clamping span to ${GRID_COLUMNS - safeOffset}.`
    );
  }

  const clampedSpan = Math.min(safeSpan, GRID_COLUMNS - safeOffset);

  // CSS Grid: grid-column: {start} / span {span}
  // start 从 1 开始计数（Grid 规范），offset 0 → start 1
  const gridColumn = `${safeOffset + 1} / span ${clampedSpan}`;

  const colStyle: CSSProperties = {
    gridColumn,
    ...style,
  };

  return (
    <div className={className} style={colStyle}>
      {children}
    </div>
  );
}

// ============================================================================
// 七、便捷工具函数
// ============================================================================

/**
 * 获取指定断点的 gutter 值（px）。
 *
 * 纯函数，不依赖 React。用于非 React 场景的 gutter 值查询。
 *
 * @param size - gutter 尺寸
 * @returns gutter 值（px）
 *
 * @example
 * ```ts
 * import { getGutterPx } from '@/lib/responsive/grid-system';
 * const px = getGutterPx('lg'); // 24
 * ```
 */
export function getGutterPx(size: 'sm' | 'md' | 'lg'): number {
  return GUTTER_CSS_VAR_MAP[size].fallback;
}

/**
 * 获取指定断点的 gutter CSS 变量引用。
 *
 * 返回 var(--semantic-spacing-*, fallback) 格式的 CSS 值，
 * 优先消费模块1 的 spacing token。
 *
 * @param size - gutter 尺寸
 * @returns CSS gap 值字符串
 *
 * @example
 * ```ts
 * import { getGutterCss } from '@/lib/responsive/grid-system';
 * const css = getGutterCss('lg'); // "var(--semantic-spacing-lg, 24px)"
 * ```
 */
export function getGutterCss(size: 'sm' | 'md' | 'lg'): string {
  return getGutterCssValue(size);
}
