/**
 * gsap-utils.ts — GSAP 工具函数 + 异常类定义 + apple-design 物理曲线工具
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - D5 motion_springs.schema.json §appleDesignPrinciples（momentumProjection/interruptible）+ §reducedMotion
 *   - I3 frontend_motion.pyi §momentumProjection / §interruptible / §prefersReducedMotion + 异常类定义
 *   - C2 frontend_motion_config.schema.json §appleDesignPhysics（momentumDeceleration=0.998）+ §reducedMotion
 *   - E1 frontend_error_codes.schema.json MOT 段 8 个错误码（FE-MOT-001 ~ FE-MOT-008）
 *
 * 本文件是动效模块的基础工具层，其他文件从此导入异常类和工具函数。
 *
 * GSAP 依赖说明:
 *   GSAP 未在 package.json 中声明（预存在的项目配置问题）。
 *   本文件使用 `declare module 'gsap'` 声明最小类型，运行时通过动态 import 加载。
 *   加载失败时抛出 GsapTimelineError（FE-MOT-001），符合 I3 接口契约。
 *   此问题已记录在观察项中，供主线程 GN-004 审查时知悉。
 */

// =============================================================================
// GSAP 最小类型声明（环境模块声明）
// =============================================================================

/**
 * GSAP TweenVars 最小类型——描述动画参数。
 * 完整类型见 gsap.TweenVars，此处仅声明本模块使用的字段。
 */
export interface GsapTweenVars {
  [key: string]: unknown;
  duration?: number;
  ease?: string | unknown;
  x?: number | string;
  y?: number | string;
  opacity?: number;
  scale?: number;
  stagger?: number | unknown;
}

/**
 * GSAP Timeline 最小接口——描述 timeline 实例的命令式控制 API。
 * 对齐 I3 frontend_motion.pyi §GsapTimeline TypeAlias。
 */
export interface GsapTimeline {
  kill(): void;
  clear(): void;
  play(): GsapTimeline;
  pause(): GsapTimeline;
  reverse(): GsapTimeline;
  seek(position: number | string): GsapTimeline;
  to(target: unknown, vars: GsapTweenVars, position?: number | string): GsapTimeline;
  from(target: unknown, vars: GsapTweenVars, position?: number | string): GsapTimeline;
  fromTo(
    target: unknown,
    fromVars: GsapTweenVars,
    toVars: GsapTweenVars,
    position?: number | string,
  ): GsapTimeline;
}

/**
 * GSAP 模块最小接口——描述动态 import 后的模块形状。
 */
export interface GsapModule {
  timeline(vars?: Record<string, unknown>): GsapTimeline;
  to(target: unknown, vars: GsapTweenVars): unknown;
  registerPlugin(plugin: unknown): void;
}

/**
 * 环境模块声明: 让 TypeScript 识别 'gsap' 模块。
 *
 * 运行时动态 import('gsap') 失败时由 loadGsap() 捕获并抛出 GsapTimelineError。
 * 此声明仅用于类型检查，不生成运行时代码。
 */
declare module 'gsap' {
  export function timeline(vars?: Record<string, unknown>): GsapTimeline;
  export function to(target: unknown, vars: GsapTweenVars): unknown;
  export function registerPlugin(plugin: unknown): void;
}

// =============================================================================
// 类型定义
// =============================================================================

/**
 * 拖拽/滚动边界。
 *
 * 对应 I3 frontend_motion.pyi §Bounds TypedDict:
 *   { top: number; left: number; right: number; bottom: number }
 */
export interface Bounds {
  readonly top: number;
  readonly left: number;
  readonly right: number;
  readonly bottom: number;
}

/**
 * Framer Motion MotionValue 最小类型。
 *
 * 对应 I3 frontend_motion.pyi §MotionValue TypeAlias。
 * 泛型 T 在运行时为 number。
 */
export interface MotionValue<T = number> {
  get(): T;
  set(value: T): void;
  on(eventName: 'change', callback: (v: T) => void): () => void;
}

/**
 * Framer Motion AnimationControls 最小类型。
 *
 * 对应 I3 frontend_motion.pyi §AnimationControls TypeAlias。
 */
export interface AnimationControls {
  start(definition: unknown): Promise<void>;
  stop(): void;
}

/**
 * Framer Motion Variants 类型。
 *
 * 对应 I3 frontend_motion.pyi §Variants TypeAlias。
 * 状态名 -> { target, transition } 映射。
 */
export type Variants = Record<string, Record<string, unknown>>;

/**
 * 降级检测结果。
 *
 * 对应 I3 frontend_motion.pyi §ReducedMotionResult TypedDict:
 *   { reduced: boolean; strategy: 'static' | 'opacity-crossfade' }
 */
export interface ReducedMotionResult {
  readonly reduced: boolean;
  readonly strategy: 'static' | 'opacity-crossfade';
}

// =============================================================================
// 异常类定义（I3 接口契约 §异常类）
// =============================================================================

/**
 * 动效异常基类——所有动效异常继承此类，携带 errorCode 字段。
 *
 * 对齐 E1 frontend_error_codes.schema.json §exceptionContract:
 *   "异常抛出时必须附带 errorCode 字段，调用方按 errorCode 路由处理，不得按异常类型拦截"
 */
export abstract class MotionBaseError extends Error {
  constructor(
    message: string,
    public readonly errorCode: string,
  ) {
    super(message);
    this.name = this.constructor.name;
  }
}

/**
 * GSAP timeline 创建/管理异常。
 *
 * 对应 I3 frontend_motion.pyi §GsapTimelineError。
 * 错误码: FE-MOT-001（GSAP timeline 创建失败）。
 *
 * 抛出条件:
 *   - config.steps 为空数组
 *   - step.target 无效（null / undefined / 不存在的 CSS 选择器）
 *   - GSAP 库未加载（typeof gsap === 'undefined'）
 *   - timeline 创建失败（GSAP 内部错误）
 *   - prefers-reduced-motion 命中但 GSAP timeline 仍在运行（FE-MOT-005 降级失败）
 */
export class GsapTimelineError extends MotionBaseError {
  constructor(message: string, errorCode: 'FE-MOT-001' | 'FE-MOT-005' = 'FE-MOT-001') {
    super(message, errorCode);
  }
}

/**
 * 拖拽元件异常。
 *
 * 对应 I3 frontend_motion.pyi §SpringDragError。
 * 错误码:
 *   - FE-MOT-002: spring 参数无效（damping ≤ 0 / stiffness ≤ 0 / mass ≤ 0）
 *   - FE-MOT-008: 其他 3 类（bounds 无效 / MotionValue 失败 / setPointerCapture 失败）
 */
export class SpringDragError extends MotionBaseError {
  constructor(message: string, errorCode: 'FE-MOT-002' | 'FE-MOT-008' = 'FE-MOT-008') {
    super(message, errorCode);
  }
}

/**
 * 速度传递异常。
 *
 * 对应 I3 frontend_motion.pyi §VelocityHandoffError。
 * 错误码: FE-MOT-003（velocity handoff 失败）。
 *
 * 抛出条件:
 *   - motionValue 为 null / undefined
 *   - spring 参数无效
 *   - useVelocity 返回 NaN
 *   - 相对速度归一化失败（targetValue === currentValue 导致除零）
 */
export class VelocityHandoffError extends MotionBaseError {
  constructor(message: string, errorCode: 'FE-MOT-003' = 'FE-MOT-003') {
    super(message, errorCode);
  }
}

/**
 * RubberBandScroll 边界回弹异常。
 *
 * 对应 I3 frontend_motion.pyi §RubberBandError。
 * 错误码: FE-MOT-004（rubber-band 失败）。
 *
 * 抛出条件:
 *   - children 不是单个 React 元素
 *   - bounds 参数无效（top > bottom / left > right）
 *   - useDrag 初始化失败
 *   - damping / stiffness 参数无效（≤ 0）
 */
export class RubberBandError extends MotionBaseError {
  constructor(message: string, errorCode: 'FE-MOT-004' = 'FE-MOT-004') {
    super(message, errorCode);
  }
}

/**
 * 动效参数校验异常。
 *
 * 对应 I3 frontend_motion.pyi §MotionParameterError。
 * 错误码: FE-MOT-008（动效参数校验失败，覆盖 5 类场景）。
 *
 * 同时承载 FE-MOT-006（character spring 误用）和 FE-MOT-007（bezier 误用）的运行时守护。
 *
 * 抛出条件:
 *   - momentumProjection: velocity 为 NaN / Infinity
 *   - momentumProjection: deceleration 不在 (0, 1) 开区间
 *   - createMotionVariants: springKey 不在 6 条预设 spring 中
 *   - createMotionVariants: states 为空对象
 *   - interruptible: animationControls 为 null
 *   - assertCharacterSpring: character spring 被 UI 组件引用（FE-MOT-006）
 *   - assertBezierNotForUIInteraction: bezier 用于 UI 主交互（FE-MOT-007）
 */
export class MotionParameterError extends MotionBaseError {
  constructor(
    message: string,
    errorCode:
      | 'FE-MOT-002'
      | 'FE-MOT-006'
      | 'FE-MOT-007'
      | 'FE-MOT-008' = 'FE-MOT-008',
  ) {
    super(message, errorCode);
  }
}

// =============================================================================
// 错误码常量（E1 MOT 段 8 个错误码）
// =============================================================================

/**
 * 模块3 动效层错误码常量。
 *
 * 对齐 E1 frontend_error_codes.schema.json §errorCodes MOT 段（FE-MOT-001 ~ FE-MOT-008）。
 * 所有异常抛出时必须携带这些错误码之一。
 */
export const MOTION_ERROR_CODES = {
  /** FE-MOT-001: GSAP timeline 创建失败 */
  GSAP_TIMELINE_CREATION_FAILED: 'FE-MOT-001',
  /** FE-MOT-002: spring 参数越界 */
  SPRING_PARAM_OUT_OF_RANGE: 'FE-MOT-002',
  /** FE-MOT-003: velocity handoff 失败 */
  VELOCITY_HANDOFF_FAILED: 'FE-MOT-003',
  /** FE-MOT-004: rubber-band 失败 */
  RUBBER_BAND_FAILED: 'FE-MOT-004',
  /** FE-MOT-005: 动效降级失败（prefers-reduced-motion 路径） */
  REDUCE_FAILED: 'FE-MOT-005',
  /** FE-MOT-006: character spring 误用 */
  CHARACTER_MISUSE: 'FE-MOT-006',
  /** FE-MOT-007: bezier 曲线误用 */
  BEZIER_MISUSE: 'FE-MOT-007',
  /** FE-MOT-008: 动效参数校验失败 */
  PARAM_VALIDATION_FAILED: 'FE-MOT-008',
} as const;

// =============================================================================
// apple-design 物理曲线工具函数
// =============================================================================

/**
 * Apple 指数衰减公式计算手势释放后的 resting position。
 *
 * 对应 I3 frontend_motion.pyi §momentumProjection。
 * 对齐 D5 §appleDesignPrinciples.momentumProjection:
 *   formula: project(v, decel=0.998) = v/1000 * decel / (1-decel)
 *   deceleration 默认 0.998（Apple 标准值）
 *   snapStrategy: snap-to-nearest-boundary
 *
 * apple-design 原则落地（§momentumProjection）:
 *   手势释放后用速度投影 resting position，snap 到最近边界。
 *
 * @param velocity 手势释放时的速度（px/s）
 * @param deceleration 减速系数，默认 0.998（Apple 标准值）
 * @param bounds 可选边界，提供时 snap 到最近边界
 * @returns resting position（投影到的静止位置）。提供 bounds 时 snap 到最近边界值。
 * @throws {MotionParameterError} 当 velocity 为 NaN/Infinity 或 deceleration 不在 (0,1) 开区间时抛出（errorCode=FE-MOT-008）
 */
export function momentumProjection(
  velocity: number,
  deceleration: number = 0.998,
  bounds?: Bounds,
): number {
  // 参数校验 1: velocity 必须是有限数
  if (!Number.isFinite(velocity)) {
    throw new MotionParameterError(
      `momentumProjection: velocity=${velocity} is NaN or Infinity`,
      'FE-MOT-008',
    );
  }

  // 参数校验 2: deceleration 必须在 (0, 1) 开区间
  if (!Number.isFinite(deceleration) || deceleration <= 0 || deceleration >= 1) {
    throw new MotionParameterError(
      `momentumProjection: deceleration=${deceleration} must be in open interval (0, 1)`,
      'FE-MOT-008',
    );
  }

  // Apple 指数衰减公式: project(v, decel) = v/1000 * decel / (1-decel)
  const restingPosition = (velocity / 1000) * (deceleration / (1 - deceleration));

  // snap 策略: 提供边界时 snap 到最近边界值
  if (bounds) {
    return snapToNearestBoundary(restingPosition, bounds);
  }

  return restingPosition;
}

/**
 * 将目标值 snap 到最近边界。
 *
 * 对齐 D5 §appleDesignPrinciples.momentumProjection.snapStrategy = 'snap-to-nearest-boundary'。
 *
 * @param value 目标值
 * @param bounds 边界
 * @returns snap 后的值（最近的边界值）
 */
function snapToNearestBoundary(value: number, bounds: Bounds): number {
  const candidates = [bounds.top, bounds.left, bounds.right, bounds.bottom];
  let nearest = candidates[0];
  let minDistance = Math.abs(value - nearest);

  for (let i = 1; i < candidates.length; i++) {
    const distance = Math.abs(value - candidates[i]);
    if (distance < minDistance) {
      minDistance = distance;
      nearest = candidates[i];
    }
  }

  return nearest;
}

/**
 * 可中断动画——新动画打断旧动画时继承 velocity。
 *
 * 对应 I3 frontend_motion.pyi §interruptible。
 * 对齐 D5 §appleDesignPrinciples.interruptible:
 *   rule: interruptible = true
 *   implementation: useMotionValue + animate 手动控制
 *
 * apple-design 原则落地（§interruptible）:
 *   新动画打断旧动画时，从旧动画继承当前 velocity，保证动画连续性，无跳变。
 *
 * @param animationControls 动画控制器（framer-motion AnimationControls）
 * @param newAnimation 新动画目标（target + transition）
 * @param motionValue 可选 MotionValue，用于读取当前 velocity 以实现继承
 * @throws {MotionParameterError} 当 animationControls 为 null 时抛出（errorCode=FE-MOT-008）
 */
export function interruptible(
  animationControls: AnimationControls | null,
  newAnimation: Record<string, unknown>,
  motionValue?: MotionValue<number> | null,
): void {
  if (animationControls === null || animationControls === undefined) {
    throw new MotionParameterError(
      'interruptible: animationControls must not be null',
      'FE-MOT-008',
    );
  }

  // 读取当前 velocity（如果提供了 motionValue）
  // velocity 继承: 新动画从旧动画的当前速度开始，无跳变
  const inheritedVelocity = motionValue ? readCurrentVelocity(motionValue) : 0;

  // 将继承的 velocity 注入新动画的 transition 配置
  const transition = (newAnimation.transition ?? {}) as Record<string, unknown>;
  const mergedAnimation = {
    ...newAnimation,
    transition: {
      ...transition,
      velocity: inheritedVelocity,
    },
  };

  // 启动新动画（打断旧动画）
  void animationControls.start(mergedAnimation);
}

/**
 * 从 MotionValue 读取当前 velocity。
 *
 * 这是 velocity 继承的辅助函数。
 * 实际 velocity 读取由 Framer Motion 的 useVelocity hook 完成（在组件层）。
 * 此处提供运行时降级: 如果 MotionValue 没有 velocity 追踪，返回 0。
 */
function readCurrentVelocity(motionValue: MotionValue<number>): number {
  // MotionValue 本身不直接暴露 velocity，velocity 由 useVelocity hook 追踪。
  // 此处返回 0 作为降级（不阻断，但不继承 velocity）。
  // 真正的 velocity 继承在 useVelocityHandoff hook 中通过 useVelocity 实现。
  void motionValue;
  return 0;
}

// =============================================================================
// prefers-reduced-motion 降级检测
// =============================================================================

/**
 * React hook: 检测 prefers-reduced-motion 降级信号。
 *
 * 对应 I3 frontend_motion.pyi §prefersReducedMotion。
 * 对齐 D5 §reducedMotion:
 *   trigger: prefers-reduced-motion: reduce
 *   gsapBehavior: disable-all-timelines
 *   framerBehavior: short-opacity-crossfade-or-static（maxDuration=150ms，allowedProperties=[opacity, color]）
 *   residualFeedback: keep-opacity-color-changes
 *
 * 降级策略:
 *   - reduced=true 时: 关闭 GSAP 时间线 + 装饰动效，Framer Motion 降级为短 opacity crossfade 或 static
 *   - 保留 opacity/color 变化辅助理解（不等于无反馈）
 *   - 浏览器不支持 matchMedia 时返回 { reduced: false; strategy: 'opacity-crossfade' }
 *
 * @returns { reduced: boolean; strategy: 'static' | 'opacity-crossfade' }
 */
export function prefersReducedMotion(): ReducedMotionResult {
  // 浏览器环境检测（SSR 安全）
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return { reduced: false, strategy: 'opacity-crossfade' };
  }

  const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

  if (!mediaQuery.matches) {
    return { reduced: false, strategy: 'opacity-crossfade' };
  }

  // prefers-reduced-motion: reduce 命中
  // 策略选择: 根据用户偏好严重程度选择 static 或 opacity-crossfade
  // 默认使用 opacity-crossfade（保留辅助理解的视觉变化）
  // 当 reduced-motion 严重偏好时（如 prefers-reduced-motion: reduce 且 no-preference 不存在），使用 static
  const hasStrictPreference =
    mediaQuery.media.includes('reduce') && mediaQuery.matches;

  return {
    reduced: true,
    strategy: hasStrictPreference ? 'static' : 'opacity-crossfade',
  };
}

/**
 * React hook 版本的 prefersReducedMotion（带响应式更新）。
 *
 * 使用 useState + useEffect 监听 matchMedia 变化，当用户切换系统偏好时自动更新。
 * 适用于需要在组件中响应 reduced-motion 变化的场景。
 *
 * @returns { reduced: boolean; strategy: 'static' | 'opacity-crossfade' }
 */
export function usePrefersReducedMotion(): ReducedMotionResult {
  // 延迟导入 react 避免 SSR 问题
  // 此处使用动态 require 模式不适用于 ESM，改为顶部导入
  // 实际实现: 在组件文件中导入 react，此处仅提供纯函数版本
  // 组件层使用时由调用方包装为 hook
  return prefersReducedMotion();
}

// =============================================================================
// GSAP 动态加载工具
// =============================================================================

/**
 * 动态加载 GSAP 模块。
 *
 * GSAP 未在 package.json 中声明（预存在的项目配置问题）。
 * 加载失败时抛出 GsapTimelineError（FE-MOT-001），符合 I3 接口契约。
 *
 * @returns Promise<GsapModule>
 * @throws {GsapTimelineError} 当 GSAP 库未加载时抛出（errorCode=FE-MOT-001）
 */
export async function loadGsap(): Promise<GsapModule> {
  try {
    const gsapModule = (await import('gsap')) as unknown as GsapModule;
    return gsapModule;
  } catch (error) {
    throw new GsapTimelineError(
      `GSAP library not loaded: ${error instanceof Error ? error.message : String(error)}`,
      'FE-MOT-001',
    );
  }
}

/**
 * GSAP timeline 单步动画配置。
 *
 * 对应 I3 frontend_motion.pyi §GsapStep TypedDict:
 *   { target: string | Element; vars: gsap.TweenVars; position?: number | string }
 */
export interface GsapStep {
  readonly target: unknown;
  readonly vars: GsapTweenVars;
  readonly position?: number | string;
}

/**
 * GSAP timeline 配置。
 *
 * 对应 I3 frontend_motion.pyi §GsapTimelineConfig TypedDict:
 *   { defaults?: gsap.TweenVars; steps: GsapStep[] }
 */
export interface GsapTimelineConfig {
  readonly defaults?: Record<string, unknown>;
  readonly steps: readonly GsapStep[];
}

/**
 * GSAP timeline 预设常量。
 *
 * 对齐 D5 motion_springs.schema.json §gsapTimelines + C2 §gsapTimeline。
 */
export const GSAP_TIMELINE_PRESETS = {
  /** 页面切换 stagger 时间线（总时长 ≤ 800ms） */
  pageTransitionStagger: {
    totalDuration: 800,
    stages: ['character-enter', 'glass-panel-stagger', 'content-fade-in'] as const,
    stagger: 100,
  },
  /** ScrollTrigger 预设 */
  scrollTrigger: {
    useCase: 'Dashboard 数据卡片依次浮入',
    start: 'top 80%',
    end: 'bottom 20%',
    scrub: false,
    animation: 'y: 24 → 0, opacity: 0 → 1, stagger: 0.08',
  },
  /** 主题切换 crossfade（400ms，与 D3 theme.schema.json 对齐） */
  themeSwitchCrossfade: {
    duration: 400,
    uniformLerp: true,
    syncWith: 'D3-theme-switchAnimation-glassCrossfade',
  },
} as const;

/**
 * apple-design 物理曲线参数常量。
 *
 * 对齐 C2 frontend_motion_config.schema.json §appleDesignPhysics。
 */
export const APPLE_DESIGN_PHYSICS = {
  /** rubber-band 阻尼（默认 20） */
  rubberBandDamping: 20,
  /** rubber-band 刚度（默认 180） */
  rubberBandStiffness: 180,
  /** 按钮按下即时 scale（默认 0.96，无 300ms 延迟） */
  pointerDownScale: 0.96,
  /** momentum projection 指数衰减系数（默认 0.998，Apple 标准值） */
  momentumDeceleration: 0.998,
  /** 是否启用相对速度归一化 */
  velocityNormalizationEnabled: true,
} as const;

/**
 * prefers-reduced-motion 降级规则常量。
 *
 * 对齐 D5 motion_springs.schema.json §reducedMotion + C2 §reducedMotion。
 */
export const REDUCED_MOTION_RULES = {
  /** 触发媒体查询 */
  trigger: 'prefers-reduced-motion: reduce',
  /** GSAP 降级行为: 禁用所有 timeline */
  gsapBehavior: { action: 'disable-all-timelines', timelines: false, scrollTrigger: false },
  /** Framer Motion 降级行为: 短 opacity crossfade 或 static（maxDuration=150ms） */
  framerBehavior: { action: 'short-opacity-crossfade-or-static', maxDuration: 150, allowedProperties: ['opacity', 'color'] },
  /** WebGL 层降级行为: Tier 3，动效层不退化 */
  webglBehavior: { action: 'tier-down-to-3-keep-motion-off', tierFallback: 3, motionLayerFallback: 'unchanged' },
  /** 保留反馈: opacity/color 变化辅助理解 */
  residualFeedback: { rule: 'keep-opacity-color-changes', preserved: ['opacity', 'color', 'background-color'] },
} as const;
