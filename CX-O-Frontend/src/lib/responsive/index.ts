/**
 * @file index.ts
 * @module 模块9/响应式性能层（9a 响应式断点层 + 9b 移动端降级层）
 *
 * 响应式性能层统一导出入口。聚合断点检测、移动端检测、栅格系统、
 * 移动端降级 9 项规则、触摸适配全部公开 API。
 *
 * 契约对齐：
 * - D6 responsive_breakpoints.schema.json（5 断点 + 栅格 + 触摸适配 + 移动端降级 + 错误码）
 * - C3 frontend_responsive_config.schema.json（断点宽度 + gutter + 触摸适配 + mobileDegrade 参数）
 * - E1 frontend_error_codes.schema.json（FE-RES-001/002/003 响应式层错误码）
 * - merged.md §6.1-6.4（断点定义 + 栅格 + 移动端降级 + 触摸适配）
 *
 * 模块边界：
 * - 本模块为横切层，被所有模块通过 React import 消费
 * - 跨模块导入约束：仅消费模块1 的 CSS 变量 token（var(--semantic-spacing-*)）
 *   + 模块4 useGlassTier（仅限 tier 切换接口，用于移动端降级规则 1）
 * - 禁止 import 模块1/2/3/5/6/7/8 的内部实现（rules-4 §4.3）
 *
 * @example 完整用法
 * ```tsx
 * import {
 *   useBreakpoint,
 *   useMobileDetect,
 *   useMobileDegrade,
 *   TouchAdapter,
 *   Row,
 *   Col,
 *   BREAKPOINTS,
 * } from '@/lib/responsive';
 *
 * function Dashboard() {
 *   const { current, isAtLeast, isMobile } = useBreakpoint();
 *   const { isTouch, hasHover } = useMobileDetect();
 *   const { isDegrading, rules, currentTier } = useMobileDegrade();
 *
 *   return (
 *     <Row maxContentWidth gutter="auto">
 *       <Col span={{ sm: 12, lg: 8 }}>
 *         <main>当前断点: {current} | 降级: {isDegrading ? 'ON' : 'OFF'} | tier: {currentTier}</main>
 *       </Col>
 *       <Col span={{ sm: 12, lg: 4 }}>
 *         <TouchAdapter onTap={() => select()}>
 *           <aside>侧边栏</aside>
 *         </TouchAdapter>
 *       </Col>
 *     </Row>
 *   );
 * }
 * ```
 */

// ============================================================================
// 一、断点常量（breakpoints.ts）— 模块9a
// ============================================================================

export {
  /** 5 个断点最小宽度阈值（sm 640 / md 768 / lg 1024 / xl 1280 / 2xl 1536） */
  BREAKPOINTS,
  /** 断点从小到大排序数组 */
  BREAKPOINT_ORDER,
  /** 断点元数据（glassTier / blurValue / isMobile 等，对齐 D6） */
  BREAKPOINT_META,
  /** SSR 默认断点 'lg'（桌面主战场起点） */
  DEFAULT_BREAKPOINT,
  /** 栅格列数 12（对齐 D6 gridSystem.columns） */
  GRID_COLUMNS,
  /** 栅格间距分级（lgPlus 24 / md 16 / sm 12，对齐 D6 gridSystem.gutter） */
  GUTTER,
  /** 桌面主内容区最大宽度 1440px（对齐 D6 gridSystem.maxContentWidth） */
  MAX_CONTENT_WIDTH,
  /** 触摸适配参数（minTouchTargetSize 44 等，对齐 D6 touchAdaptation） */
  TOUCH_ADAPTATION,
  /** 移动端断点判定阈值 767px（< md 768） */
  MOBILE_BREAKPOINT_THRESHOLD,
  /** 5 个断点的 min-width matchMedia 查询字符串 */
  BREAKPOINT_MEDIA_QUERIES,
  /** 移动端判定 matchMedia 查询字符串 "(max-width: 767px)" */
  MOBILE_MEDIA_QUERY,
  /** hover 支持检测 matchMedia 查询字符串 "(hover: hover)" */
  HOVER_MEDIA_QUERY,
  /** coarse pointer 检测 matchMedia 查询字符串 "(pointer: coarse)" */
  COARSE_POINTER_MEDIA_QUERY,
  /** prefers-reduced-motion 媒体查询字符串 */
  REDUCED_MOTION_MEDIA_QUERY,
  /** 响应式层错误码（FE-RES-001 断点检测失败 / FE-RES-002 栅格计算错误） */
  RESPONSIVE_ERROR_CODES,
  /** 比较两个断点的宽度大小 */
  compareBreakpoints,
  /** 判断断点 a 是否 >= 断点 b */
  isBreakpointAtLeast,
  /** 获取指定断点以上（含）的所有断点列表 */
  getBreakpointsAtLeast,
} from './breakpoints';

export type {
  /** 断点 key 类型：'sm' | 'md' | 'lg' | 'xl' | '2xl' */
  BreakpointKey,
} from './breakpoints';

// ============================================================================
// 二、断点检测 hook（use-breakpoint.ts）— 模块9a
// ============================================================================

export {
  /** 响应式断点检测 hook（current / isAtLeast / isMobile / isDesktop / prefersReducedMotion） */
  useBreakpoint,
  /** prefers-reduced-motion 独立检测 hook */
  usePrefersReducedMotion,
  /** 同步获取当前断点（非 React 纯函数） */
  getCurrentBreakpoint,
} from './use-breakpoint';

export type {
  /** useBreakpoint 返回值类型 */
  UseBreakpointResult,
  /** usePrefersReducedMotion 返回值类型 */
  UsePrefersReducedMotionResult,
} from './use-breakpoint';

// ============================================================================
// 三、移动端检测 hook（use-mobile-detect.ts）— 模块9a
// ============================================================================

export {
  /** 移动端设备检测 hook（isMobile / isTouch / hasHover / isCoarsePointer） */
  useMobileDetect,
  /** 移动端检测便捷 hook（仅返回 isMobile） */
  useIsMobile,
  /** 触摸设备检测便捷 hook（仅返回 isTouch） */
  useIsTouch,
} from './use-mobile-detect';

export type {
  /** useMobileDetect 返回值类型 */
  UseMobileDetectResult,
  /** useIsMobile 返回值类型 */
  UseIsMobileResult,
  /** useIsTouch 返回值类型 */
  UseIsTouchResult,
} from './use-mobile-detect';

// ============================================================================
// 四、栅格系统组件（grid-system.tsx）— 模块9a
// ============================================================================

export {
  /** Row 栅格容器组件（CSS Grid 12 列） */
  Row,
  /** Col 栅格子组件（支持响应式 span/offset） */
  Col,
  /** 获取指定断点的 gutter 值（px，纯函数） */
  getGutterPx,
  /** 获取指定断点的 gutter CSS 变量引用（var(--semantic-spacing-*, fallback)） */
  getGutterCss,
} from './grid-system';

export type {
  /** Row 组件 props */
  RowProps,
  /** Col 组件 props */
  ColProps,
  /** gutter 尺寸类型 */
  GutterSize,
  /** gutter 值类型 */
  GutterValue,
  /** 响应式值类型 */
  ResponsiveValue,
  /** Col span 值类型 */
  ColSpan,
  /** Col offset 值类型 */
  ColOffset,
  /** Row 水平对齐方式 */
  RowJustify,
  /** Row 垂直对齐方式 */
  RowAlign,
} from './grid-system';

// ============================================================================
// 五、移动端降级规则定义（degradation-rules.ts）— 模块9b
// ============================================================================

export {
  /** 9 项降级规则 key 有序数组（索引 0-8 对应规则序号 1-9） */
  MOBILE_DEGRADE_RULE_KEYS,
  /** 规则 key → 序号映射（1-9） */
  RULE_KEY_TO_INDEX,
  /** 默认移动端降级配置（对齐 C3 mobileDegrade default） */
  DEFAULT_MOBILE_DEGRADE_CONFIG,
  /** 默认触摸适配配置（对齐 C3 touchAdaptation default + D6 touchAdaptation） */
  DEFAULT_TOUCH_ADAPTATION_CONFIG,
  /** 9 项降级规则中文描述（key → 描述映射） */
  MOBILE_DEGRADE_RULE_DESCRIPTIONS,
  /** 根据 C3 mobileDegrade 配置构建 9 项降级规则（配置驱动） */
  buildMobileDegradeRules,
  /** 根据规则 key 查找指定规则 */
  findRuleByKey,
  /** 过滤出已启用的降级规则 */
  filterEnabledRules,
  /** 统计已启用的降级规则数量（0-9） */
  countEnabledRules,
} from './degradation-rules';

export type {
  /** 移动端降级规则 key（9 项唯一标识符） */
  MobileDegradeRuleKey,
  /** 角色资产形态（'static-2d' | 'live2d' | 'vrm'） */
  CharacterAssetMode,
  /** 工具栏策略（'bottom-tab-drawer' | 'sidebar' | 'top-bar'） */
  ToolbarStrategy,
  /** 降级规则参数（各规则不同参数，统一为可选字段对象） */
  MobileDegradeRuleParams,
  /** 移动端降级规则定义（key + 序号 + 描述 + 启用 + 参数） */
  MobileDegradeRule,
  /** 移动端降级配置（对齐 C3 mobileDegrade 8 项参数） */
  MobileDegradeConfig,
  /** 触摸适配配置（对齐 C3 touchAdaptation 4 项参数） */
  TouchAdaptationConfig,
} from './degradation-rules';

// ============================================================================
// 六、移动端降级配置与触发（mobile-degradation.ts）— 模块9b
// ============================================================================

export {
  /** 移动端降级层错误码（FE-RES-003 移动端降级失败 响应式层） */
  MOBILE_DEGRADE_ERROR_CODES,
  /** 移动端降级失败异常类（携带 errorCode + ruleKey + failureType） */
  MobileDegradeError,
  /** 校验移动端降级配置合法性（对齐 C3 mobileDegrade 范围约束） */
  validateMobileDegradeConfig,
  /** 合并配置与默认值（对齐 C3 autoFill merge-with-defaults） */
  mergeWithDefaults,
  /** 判定当前是否应触发移动端降级（matchMedia('(max-width: 767px)')） */
  shouldApplyMobileDegrade,
  /** 获取移动端降级触发条件描述信息（用于埋点与监控上报） */
  getDegradeTriggerInfo,
  /** 生成 backdrop-filter CSS 变量覆盖映射（降级规则 4：blur ≤ 16px） */
  getBackdropFilterCssOverride,
  /** 创建视口外懒挂载 IntersectionObserver（降级规则 6） */
  createLazyMountObserver,
  /** 根据降级规则列表生成降级动作清单（供 hook 按分类路由执行） */
  buildDegradeActions,
} from './mobile-degradation';

export type {
  /** backdrop-filter CSS 变量覆盖映射 */
  BackdropFilterCssOverride,
  /** 视口外懒挂载回调接口 */
  LazyMountCallbacks,
  /** 降级动作描述（ruleKey + action + category） */
  DegradeAction,
} from './mobile-degradation';

// ============================================================================
// 七、移动端降级组合 hook（use-mobile-degradation.ts）— 模块9b
// ============================================================================

export {
  /** 移动端降级组合 hook（组合 useBreakpoint + useMobileDetect + useGlassTier） */
  useMobileDegrade,
  /** 移动端降级便捷 hook（仅返回降级状态，不执行 tier 切换） */
  useIsMobileDegrade,
} from './use-mobile-degradation';

export type {
  /** useMobileDegrade hook 选项 */
  UseMobileDegradeOptions,
  /** useMobileDegrade hook 返回值 */
  UseMobileDegradeResult,
  /** useIsMobileDegrade 返回值类型 */
  UseIsMobileDegradeResult,
} from './use-mobile-degradation';

// ============================================================================
// 八、触摸适配组件（touch-adapter.tsx）— 模块9b
// ============================================================================

export {
  /** TouchAdapter 触摸适配组件（tap/hover/press 手势映射 + 44×44px 最小点击区域） */
  TouchAdapter,
  /** 触摸适配 hook（提供 tap/hover/press 手势状态 + 事件处理器） */
  useTouchAdapter,
  /** 最小点击区域便捷 hook（返回 44×44px 样式） */
  useMinTouchTarget,
  /** 检测手势配置冲突（FE-RES-003 触摸适配冲突） */
  detectGestureConflict,
} from './touch-adapter';

export type {
  /** 手势状态枚举（'idle' | 'tap' | 'hover' | 'press'） */
  GestureState,
  /** useTouchAdapter hook 返回值 */
  UseTouchAdapterResult,
  /** useTouchAdapter hook 选项 */
  UseTouchAdapterOptions,
  /** TouchAdapter 组件 props */
  TouchAdapterProps,
  /** useMinTouchTarget 返回值类型 */
  UseMinTouchTargetResult,
  /** 手势冲突检测选项 */
  GestureConflictCheckOptions,
} from './touch-adapter';
