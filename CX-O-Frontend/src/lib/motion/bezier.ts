/**
 * bezier.ts — 4 条 bezier 曲线常量（仅装饰动效循环）
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - D5 motion_springs.schema.json §beziers（4 bezier + value + useCase + useCaseRestriction）
 *   - I3 frontend_motion.pyi §bezierCurves 常量字典 + BezierCurveConfig TypedDict
 *   - E1 frontend_error_codes.schema.json FE-MOT-007（bezier 曲线误用于 UI 主交互）
 *
 * 参数对齐模块1 token: src/styles/tokens/primitive.css §6.2 --motion-bezier-* 系列
 *   --motion-bezier-ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)       → easeInOut
 *   --motion-bezier-ease-spring: cubic-bezier(0.2, 0.8, 0.2, 1)     → easeSpring
 *   --motion-bezier-ease-glass: cubic-bezier(0.16, 1, 0.3, 1)       → easeGlass
 *   --motion-bezier-ease-character: cubic-bezier(0.34, 1.56, 0.64, 1) → easeCharacter
 *
 * 命名说明: 以 D5 motion_springs.schema.json §beziers 的命名为准（easeInOut/easeSpring/easeGlass/easeCharacter）。
 *   注意: C2 frontend_motion_config.schema.json §beziers 使用了不同命名（easeGlassIn/easeDecorate/easeLinear/easeSakura），
 *   这是契约内部不一致。闭合判据 #2 明确要求"与 D5 schema 对齐"，故本文件以 D5 命名为权威来源。
 *   已在观察项中记录，供主线程 GN-004 审查时知悉。
 *
 * apple-design 原则（§springFirst）:
 *   spring 为主交互曲线（禁用 linear/ease-in-out），bezier 仅用于装饰动效的循环动画
 *   （如星光闪烁、花瓣飘落、光晕脉动、星轨流光）。
 *   违反（bezier 用于 UI 主交互 enter/exit/hover/press/toggle）触发 FE-MOT-007。
 */

import { MotionParameterError } from './gsap-utils';

/**
 * Bezier 曲线配置。
 *
 * 对应 I3 frontend_motion.pyi §BezierCurveConfig TypedDict:
 *   { points: [number, number, number, number]; useCase: string }
 *
 * 扩展字段（对齐 D5 §beziers）:
 *   - cssValue: cubic-bezier 字符串（用于 CSS transition/animation）
 *   - useCaseRestriction: OBS-C 收窄标记（仅 easeCharacter = 'character-only'）
 */
export interface BezierCurveConfig {
  /** 控制点四元组 [c1x, c1y, c2x, c2y]（用于 JS 动画库如 GSAP） */
  readonly points: readonly [number, number, number, number];
  /** cubic-bezier 字符串（用于 CSS transition-timing-function / animation-timing-function） */
  readonly cssValue: string;
  /** 使用场景白名单 */
  readonly useCase: readonly string[];
  /** 使用场景限制（OBS-C: easeCharacter = 'character-only'，其他 = 'unrestricted'） */
  readonly useCaseRestriction: 'character-only' | 'unrestricted';
}

/**
 * Bezier 预设名联合类型。
 *
 * 对齐 D5 motion_springs.schema.json §beziers.required:
 *   easeInOut / easeSpring / easeGlass / easeCharacter
 */
export type BezierKey = 'easeInOut' | 'easeSpring' | 'easeGlass' | 'easeCharacter';

/**
 * UI 主交互状态名黑名单——bezier 禁止用于以下状态。
 *
 * 来源: D5 motion_springs.schema.json §beziers.description
 *   "仅用于装饰动效循环（UI 主交互禁用，违反触发 errorCodes.MOTION_BEZIER_MISUSE）"
 *   "beziers.* 中任一曲线用于 UI 主交互（enter/exit/hover/press/toggle 等非装饰场景）"
 *
 * 命中任一即触发 FE-MOT-007（bezier 曲线误用）。
 */
const UI_INTERACTION_STATES: ReadonlySet<string> = new Set([
  'enter',
  'exit',
  'hover',
  'press',
  'toggle',
  'focus',
  'active',
  'open',
  'close',
  'show',
  'hide',
  'mount',
  'unmount',
]);

/**
 * 4 条 bezier 曲线字典。
 *
 * 对齐 D5 motion_springs.schema.json §beziers + I3 frontend_motion.pyi §bezierCurves 常量字典。
 * 参数与模块1 token src/styles/tokens/primitive.css §6.2 完全一致。
 *
 * 使用约定:
 *   - spring 为主交互曲线（禁用 linear/ease-in-out），bezier 仅用于装饰动效的循环动画
 *   - 典型场景: 星光闪烁（随机 duration 2-4s）、花瓣飘落、光晕脉动、星轨流光
 *   - easeCharacter: OBS-C 收窄，仅角色立绘装饰循环
 */
export const bezierCurves = {
  /**
   * 通用 ease-in-out（仅装饰循环）。
   * D5 value: cubic-bezier(0.4, 0, 0.2, 1)
   */
  easeInOut: {
    points: [0.4, 0, 0.2, 1] as const,
    cssValue: 'cubic-bezier(0.4, 0, 0.2, 1)',
    useCase: ['decoration-loop', 'particle-fade'] as const,
    useCaseRestriction: 'unrestricted' as const,
  },

  /**
   * spring 近似 bezier（仅装饰循环）。
   * D5 value: cubic-bezier(0.2, 0.8, 0.2, 1)
   */
  easeSpring: {
    points: [0.2, 0.8, 0.2, 1] as const,
    cssValue: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
    useCase: ['decoration-spring-like'] as const,
    useCaseRestriction: 'unrestricted' as const,
  },

  /**
   * 玻璃入场 bezier（仅装饰循环，UI 入场必须用 springs.glass）。
   * D5 value: cubic-bezier(0.16, 1, 0.3, 1)
   *
   * 注意: 此曲线用于装饰性的玻璃光泽闪烁循环，不是 UI 入场动画。
   * UI 入场动画必须使用 springs.glass（apple-design spring 优先原则）。
   */
  easeGlass: {
    points: [0.16, 1, 0.3, 1] as const,
    cssValue: 'cubic-bezier(0.16, 1, 0.3, 1)',
    useCase: ['glass-decoration-shimmer'] as const,
    useCaseRestriction: 'unrestricted' as const,
  },

  /**
   * 角色弹性 bezier（OBS-C 收窄：仅角色立绘装饰循环）。
   * D5 value: cubic-bezier(0.34, 1.56, 0.64, 1)（含过冲）
   *
   * 违反触发 errorCodes.MOTION_BEZIER_MISUSE (FE-MOT-007) 如果用于 UI 主交互。
   */
  easeCharacter: {
    points: [0.34, 1.56, 0.64, 1] as const,
    cssValue: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
    useCase: ['character-decoration-bounce'] as const,
    useCaseRestriction: 'character-only' as const,
  },
} as const satisfies Record<BezierKey, BezierCurveConfig>;

/**
 * OBS-C 守护: 断言 bezier 曲线未被 UI 主交互误用。
 *
 * 对齐 D5 motion_springs.schema.json §beziers.description:
 *   "UI 主交互禁用，违反触发 errorCodes.MOTION_BEZIER_MISUSE"
 *
 * 触发条件: bezier 用于 enter/exit/hover/press/toggle 等非装饰场景。
 * 调用方处理约定: block-build（阻断构建）。
 *
 * @param bezierName bezier 曲线名
 * @param interactionState 交互状态名（如 'enter' / 'exit' / 'hover' / 'press' / 'toggle'）
 * @throws {MotionParameterError} 当 interactionState 命中 UI 主交互黑名单时抛出（errorCode=FE-MOT-007）
 */
export function assertBezierNotForUIInteraction(
  bezierName: BezierKey,
  interactionState: string,
): void {
  const normalized = interactionState.toLowerCase().replace(/[\s_-]/g, '');
  if (UI_INTERACTION_STATES.has(normalized)) {
    throw new MotionParameterError(
      `Bezier curve '${bezierName}' must not be used for UI main interaction '${interactionState}', only for decoration loops`,
      'FE-MOT-007',
    );
  }
}

/**
 * 获取指定 bezier 曲线的 CSS cubic-bezier 字符串。
 *
 * 用于传递给 CSS transition-timing-function / animation-timing-function。
 *
 * @param key bezier 预设名
 * @returns cubic-bezier 字符串
 */
export function getBezierCssValue(key: BezierKey): string {
  return bezierCurves[key].cssValue;
}

/**
 * 获取指定 bezier 曲线的控制点四元组。
 *
 * 用于传递给 GSAP 等 JS 动画库的 ease 配置。
 *
 * @param key bezier 预设名
 * @returns [c1x, c1y, c2x, c2y] 控制点
 */
export function getBezierPoints(key: BezierKey): readonly [number, number, number, number] {
  return bezierCurves[key].points;
}
