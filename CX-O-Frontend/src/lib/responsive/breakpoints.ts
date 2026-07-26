/**
 * @file breakpoints.ts
 * @module 模块9a/响应式断点层
 *
 * 响应式断点常量定义。所有断点宽度、栅格参数、触摸适配参数均严格对齐：
 * - 数据契约 D6 responsive_breakpoints.schema.json（5 断点 + 栅格 + 触摸适配）
 * - 配置契约 C3 frontend_responsive_config.schema.json（断点宽度 + gutter + 触摸适配参数）
 * - 方案 merged.md §6.1-6.4（断点定义 + 栅格 + 移动端降级 + 触摸适配）
 *
 * 断点宽度采用 const 断言（as const），保证编译期不可漂移，对齐 D6 的 JSON Schema const 约束。
 * 任何模块消费断点值时，必须从本文件导入常量，禁止硬编码（rules-3 §三 配置契约强制）。
 */

// ============================================================================
// 一、断点定义（对齐 D6 breakpoints + C3 breakpoints + merged.md §6.1）
// ============================================================================

/**
 * 5 个响应式断点的最小宽度阈值（px）。
 *
 * 对齐 Tailwind 默认断点，与 D6 responsive_breakpoints.schema.json 中
 * 各断点的 minWidth const 值逐一对应：
 * - sm:  640  — 手机横屏 / 小平板（移动端，强制 Tier 3）
 * - md:  768  — 平板竖屏（桌面体验过渡断点）
 * - lg:  1024 — 平板横屏 / 小笔记本（桌面主战场起点，默认 Tier 1）
 * - xl:  1280 — 标准桌面（完整 WebGL + 角色高精度）
 * - 2xl: 1536 — 大桌面（多列布局 + 角色多实例）
 *
 * @example
 * ```ts
 * import { BREAKPOINTS } from '@/lib/responsive/breakpoints';
 * const mdQuery = `(min-width: ${BREAKPOINTS.md}px)`; // "(min-width: 768px)"
 * ```
 */
export const BREAKPOINTS = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
} as const;

/**
 * 断点 key 类型。对齐 D6 breakpoints 的 5 个属性名。
 *
 * 注意：D6 契约未定义 'base' 断点（< sm 的区间）。
 * 当视口 < 640px 时，useBreakpoint 的 current 返回 'sm'（最小断点），
 * 但 isAtLeast('sm') 返回 false 以精确反映 min-width 语义。
 */
export type BreakpointKey = keyof typeof BREAKPOINTS;

/**
 * 断点从小到大排序数组。用于断点比较与响应式值解析。
 * 索引越大表示断点越宽。
 */
export const BREAKPOINT_ORDER: readonly BreakpointKey[] = [
  'sm',
  'md',
  'lg',
  'xl',
  '2xl',
] as const;

/**
 * SSR 环境下的默认断点。
 *
 * 取 'lg'（桌面主战场起点），对齐 spec §四"桌面端为主战场"裁决。
 * 服务端渲染时无法访问 window.matchMedia，返回 'lg' 避免水合不匹配
 * 导致移动端样式闪烁（FOUC）。
 */
export const DEFAULT_BREAKPOINT: BreakpointKey = 'lg';

// ============================================================================
// 二、断点元数据（对齐 D6 breakpoints 各断点的 glassTier / blurValue / isMobile）
// ============================================================================

/**
 * 断点元数据。对齐 D6 responsive_breakpoints.schema.json 中每个断点的完整字段。
 *
 * 字段来源：
 * - glassTier: Liquid Glass Tier 选择（1-4），对齐 D2 glass_tier_config
 * - decorativeMotionEnabled: 装饰动效开关
 * - blurValue: backdrop-filter blur 值（桌面 20-24px / 移动 ≤ 16px）
 * - isMobile: 是否移动端断点（< md 为移动端，对齐 merged.md §6.3）
 *
 * @example
 * ```ts
 * import { BREAKPOINT_META } from '@/lib/responsive/breakpoints';
 * const tier = BREAKPOINT_META.lg.glassTier; // 1（WebGL2 完整效果）
 * ```
 */
export const BREAKPOINT_META = {
  sm: {
    minWidth: BREAKPOINTS.sm,
    targetDevice: '手机横屏' as const,
    glassTier: 3 as const,
    decorativeMotionEnabled: false as const,
    blurValue: 'blur(16px) saturate(1.8)' as const,
    isMobile: true as const,
  },
  md: {
    minWidth: BREAKPOINTS.md,
    targetDevice: '平板竖屏' as const,
    glassTier: 2 as const,
    decorativeMotionEnabled: true as const,
    blurValue: 'blur(20px) saturate(1.8)' as const,
    isMobile: false as const,
  },
  lg: {
    minWidth: BREAKPOINTS.lg,
    targetDevice: '小笔记本' as const,
    glassTier: 1 as const,
    decorativeMotionEnabled: true as const,
    blurValue: 'blur(24px) saturate(1.8)' as const,
    isMobile: false as const,
  },
  xl: {
    minWidth: BREAKPOINTS.xl,
    targetDevice: '标准桌面' as const,
    glassTier: 1 as const,
    decorativeMotionEnabled: true as const,
    blurValue: 'blur(24px) saturate(1.8)' as const,
    isMobile: false as const,
  },
  '2xl': {
    minWidth: BREAKPOINTS['2xl'],
    targetDevice: '大桌面' as const,
    glassTier: 1 as const,
    decorativeMotionEnabled: true as const,
    blurValue: 'blur(24px) saturate(1.8)' as const,
    isMobile: false as const,
  },
} as const;

// ============================================================================
// 三、栅格系统参数（对齐 D6 gridSystem + C3 grid + merged.md §6.2）
// ============================================================================

/**
 * 栅格列数。const=12 对齐 D6 gridSystem.columns 与 Tailwind grid-cols-12。
 */
export const GRID_COLUMNS = 12 as const;

/**
 * 栅格间距（gutter）按断点分级（px）。
 *
 * 对齐 D6 gridSystem.gutter 与 C3 grid：
 * - lgPlus: 24 — lg 及以上断点 gutter（const=24，D6 gridSystem.gutter.lgPlus）
 * - md:     16 — md 断点 gutter（const=16，D6 gridSystem.gutter.md）
 * - sm:     12 — sm 断点 gutter（const=12，D6 gridSystem.gutter.sm）
 *
 * 注意：D6 契约中 md- 含 md 与 sm，md 字段指 md 断点专属值。
 */
export const GUTTER = {
  lgPlus: 24,
  md: 16,
  sm: 12,
} as const;

/**
 * 桌面（lg+）主内容区最大宽度（px）。const=1440 对齐 D6 gridSystem.maxContentWidth。
 * 左右留白，避免大屏下内容拉伸过宽影响可读性。
 */
export const MAX_CONTENT_WIDTH = 1440 as const;

// ============================================================================
// 四、触摸适配参数（对齐 D6 touchAdaptation + C3 touchAdaptation + merged.md §6.4）
// ============================================================================

/**
 * 触摸适配参数。对齐 D6 touchAdaptation 与 C3 touchAdaptation。
 *
 * - minTouchTargetSize: 最小点击区域尺寸（px），const=44 对齐 Apple HIG
 * - hoverToActiveOnCoarsePointer: hover 态在 pointer: coarse 设备降级为 active
 * - longPressForContextMenu: 长按手势替代右键菜单
 * - rubberBandOnlyIOS: rubber-band 滚动仅在 iOS 原生滚动容器启用
 */
export const TOUCH_ADAPTATION = {
  minTouchTargetSize: 44,
  hoverToActiveOnCoarsePointer: true,
  longPressForContextMenu: true,
  rubberBandOnlyIOS: true,
} as const;

/**
 * 移动端断点判定阈值（px）。
 *
 * 对齐 D6 mobileDegrades.triggerCondition "matchMedia('(max-width: 767px)')"。
 * 视口 < 768px（即 < md 断点）判定为移动端，触发移动端降级策略 9 项。
 */
export const MOBILE_BREAKPOINT_THRESHOLD = BREAKPOINTS.md - 1; // 767

// ============================================================================
// 五、matchMedia 查询字符串（从 BREAKPOINTS 常量生成，不硬编码）
// ============================================================================

/**
 * 5 个断点的 min-width matchMedia 查询字符串。
 *
 * 从 BREAKPOINTS 常量动态生成，保证断点值不漂移。
 * 用于 useBreakpoint / useMobileDetect 中的 window.matchMedia 查询。
 *
 * @example
 * ```ts
 * import { BREAKPOINT_MEDIA_QUERIES } from '@/lib/responsive/breakpoints';
 * const mql = window.matchMedia(BREAKPOINT_MEDIA_QUERIES.md); // "(min-width: 768px)"
 * ```
 */
export const BREAKPOINT_MEDIA_QUERIES: Record<BreakpointKey, string> = {
  sm: `(min-width: ${BREAKPOINTS.sm}px)`,
  md: `(min-width: ${BREAKPOINTS.md}px)`,
  lg: `(min-width: ${BREAKPOINTS.lg}px)`,
  xl: `(min-width: ${BREAKPOINTS.xl}px)`,
  '2xl': `(min-width: ${BREAKPOINTS['2xl']}px)`,
};

/**
 * 移动端判定 matchMedia 查询字符串。
 *
 * 对齐 D6 mobileDegrades.triggerCondition "matchMedia('(max-width: 767px)')"。
 */
export const MOBILE_MEDIA_QUERY = `(max-width: ${MOBILE_BREAKPOINT_THRESHOLD}px)`;

/**
 * hover 支持检测 matchMedia 查询字符串。
 *
 * 对齐 D6 touchAdaptation.hoverDegradeOnCoarsePointer.mediaQuery 的反向查询。
 * (hover: hover) 表示设备支持 hover（鼠标/触控笔），(hover: none) 表示纯触摸设备。
 */
export const HOVER_MEDIA_QUERY = '(hover: hover)';

/**
 * pointer 精度检测 matchMedia 查询字符串。
 *
 * 对齐 D6 touchAdaptation.hoverDegradeOnCoarsePointer.mediaQuery "(pointer: coarse)"。
 * coarse = 触摸屏，fine = 鼠标/触控笔。
 */
export const COARSE_POINTER_MEDIA_QUERY = '(pointer: coarse)';

/**
 * prefers-reduced-motion 媒体查询字符串。
 *
 * 用户系统级"减少动效"偏好检测，供动效模块（模块3）消费。
 * 对齐 merged.md §3.5 克制原则与失败回退锚点。
 */
export const REDUCED_MOTION_MEDIA_QUERY = '(prefers-reduced-motion: reduce)';

// ============================================================================
// 六、错误码（对齐 C3 errorCodes + E1 frontend_error_codes）
// ============================================================================

/**
 * 响应式层错误码。对齐 C3 frontend_responsive_config.schema.json errorCodes
 * 与 E1 frontend_error_codes.schema.json（RES 模块 3 错误码）。
 *
 * 9a 断点部分涉及前 2 个错误码：
 * - FE-RES-001: 断点检测失败（matchMedia 不可用或断点宽度非法）
 * - FE-RES-002: 栅格计算错误（columns=0 或 span/offset 越界）
 *
 * FE-RES-003（移动端降级失败）属于 9b 移动端降级部分，不在 9a 职责范围。
 */
export const RESPONSIVE_ERROR_CODES = {
  /** 断点检测失败 — severity: warning, recoveryAction: fallback-to-desktop */
  BREAKPOINT_DETECT_FAILED: 'FE-RES-001',
  /** 栅格计算错误 — severity: warning, recoveryAction: fallback-to-default-layout */
  GRID_CALCULATION_ERROR: 'FE-RES-002',
} as const;

// ============================================================================
// 七、断点比较工具函数
// ============================================================================

/**
 * 比较两个断点的宽度大小。
 *
 * @param a - 断点 A
 * @param b - 断点 B
 * @returns 负数（a < b）/ 0（a == b）/ 正数（a > b）
 *
 * @example
 * ```ts
 * compareBreakpoints('sm', 'lg'); // -2（sm 索引 0 < lg 索引 2）
 * compareBreakpoints('xl', 'md'); // 2（xl 索引 3 > md 索引 1）
 * ```
 */
export function compareBreakpoints(a: BreakpointKey, b: BreakpointKey): number {
  return BREAKPOINT_ORDER.indexOf(a) - BREAKPOINT_ORDER.indexOf(b);
}

/**
 * 判断断点 a 是否 >= 断点 b（按宽度阈值）。
 *
 * 纯值比较函数，不涉及 matchMedia 查询。
 * 用于静态断点比较场景（如响应式 span 解析）。
 *
 * @param a - 当前断点
 * @param b - 目标断点
 * @returns a >= b 时返回 true
 *
 * @example
 * ```ts
 * isBreakpointAtLeast('lg', 'md'); // true（lg 1024 >= md 768）
 * isBreakpointAtLeast('sm', 'md'); // false（sm 640 < md 768）
 * ```
 */
export function isBreakpointAtLeast(a: BreakpointKey, b: BreakpointKey): boolean {
  return compareBreakpoints(a, b) >= 0;
}

/**
 * 获取指定断点以上（含）的所有断点列表。
 *
 * @param key - 起始断点
 * @returns 从 key 到 2xl 的断点数组（从小到大）
 *
 * @example
 * ```ts
 * getBreakpointsAtLeast('lg'); // ['lg', 'xl', '2xl']
 * ```
 */
export function getBreakpointsAtLeast(key: BreakpointKey): BreakpointKey[] {
  const startIdx = BREAKPOINT_ORDER.indexOf(key);
  return BREAKPOINT_ORDER.slice(startIdx);
}
