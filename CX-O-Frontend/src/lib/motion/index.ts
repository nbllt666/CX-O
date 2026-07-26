/**
 * index.ts — 模块3 动效层统一导出入口
 *
 * 模块: 模块3 动效层
 * 落点: C:\CX-O\CX-O-Frontend\src\lib\motion\
 *
 * 契约对齐:
 *   - D5 motion_springs.schema.json（6 spring + 4 bezier + apple-design 8 原则 + variants + gsapTimelines + reducedMotion + errorCodes）
 *   - I3 frontend_motion.pyi（useGsapTimeline / useSpringDrag / useVelocityHandoff / RubberBandScroll / createMotionVariants / momentumProjection / interruptible / prefersReducedMotion）
 *   - C2 frontend_motion_config.schema.json（spring 默认值 + GSAP 时间线预设 + apple-design 物理曲线参数 + 降级规则）
 *   - E1 frontend_error_codes.schema.json MOT 段（FE-MOT-001 ~ FE-MOT-008 共 8 个错误码）
 *
 * 跨模块导入约束（rules-0 §四 + 任务要求）:
 *   - 仅 import 模块1 token 常量（参数对齐，模块1 为 CSS token，本模块硬编码同值常量）
 *   - 仅 import 第三方库（framer-motion / gsap / react）
 *   - 禁止 import 模块4/5/6/7/8/9 内部实现
 *
 * 下游被依赖:
 *   - 模块5（二次元装饰动效）: 消费 springs.bouncy + bezierCurves + createMotionVariants
 *   - 模块6（基础组件 motion variants）: 消费 springs + createMotionVariants
 *   - 模块7（业务组件动效）: 消费 springs + createMotionVariants + useGsapTimeline
 *   - 模块8（页面切换动效）: 消费 useGsapTimeline + GSAP_TIMELINE_PRESETS
 */

// =============================================================================
// springs.ts — 6 条 spring 预设曲线
// =============================================================================
export {
  springs,
  validateSpringRange,
  assertCharacterSpring,
  getSpringTransition,
} from './springs';

export type {
  SpringConfig,
  SpringKey,
  SpringUseCaseRestriction,
  AppleDesignAlignment,
  SpringPreset,
} from './springs';

// =============================================================================
// bezier.ts — 4 条 bezier 曲线（仅装饰动效循环）
// =============================================================================
export {
  bezierCurves,
  assertBezierNotForUIInteraction,
  getBezierCssValue,
  getBezierPoints,
} from './bezier';

export type {
  BezierCurveConfig,
  BezierKey,
} from './bezier';

// =============================================================================
// gsap-utils.ts — 异常类 + 错误码 + apple-design 物理曲线工具 + GSAP 工具
// =============================================================================
export {
  // 异常类
  MotionBaseError,
  GsapTimelineError,
  SpringDragError,
  VelocityHandoffError,
  RubberBandError,
  MotionParameterError,
  // 错误码常量
  MOTION_ERROR_CODES,
  // apple-design 物理曲线工具
  momentumProjection,
  interruptible,
  prefersReducedMotion,
  usePrefersReducedMotion,
  // GSAP 工具
  loadGsap,
  // 常量
  GSAP_TIMELINE_PRESETS,
  APPLE_DESIGN_PHYSICS,
  REDUCED_MOTION_RULES,
} from './gsap-utils';

export type {
  GsapTweenVars,
  GsapTimeline,
  GsapModule,
  Bounds,
  MotionValue,
  AnimationControls,
  Variants,
  ReducedMotionResult,
  GsapStep,
  GsapTimelineConfig,
} from './gsap-utils';

// =============================================================================
// create-motion-variants.ts — variants 工厂
// =============================================================================
export {
  createMotionVariants,
} from './create-motion-variants';

export type {
  MotionVariantsConfig,
  VariantStates,
} from './create-motion-variants';

// =============================================================================
// use-gsap-timeline.ts — GSAP timeline hook（StrictMode 安全）
// =============================================================================
export {
  useGsapTimeline,
} from './use-gsap-timeline';

// =============================================================================
// use-spring-drag.ts — 拖拽 spring hook
// =============================================================================
export {
  useSpringDrag,
} from './use-spring-drag';

export type {
  SpringDragConfig,
  DragHandlers,
  SpringDragMotionValues,
} from './use-spring-drag';

// =============================================================================
// use-velocity-handoff.ts — velocity 传递 hook
// =============================================================================
export {
  useVelocityHandoff,
  normalizeRelativeVelocity,
} from './use-velocity-handoff';

// =============================================================================
// rubber-band-scroll.tsx — 橡皮筋滚动组件
// =============================================================================
export {
  RubberBandScroll,
} from './rubber-band-scroll';

export type {
  RubberBandScrollProps,
} from './rubber-band-scroll';
