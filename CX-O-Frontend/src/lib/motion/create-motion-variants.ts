/**
 * create-motion-variants.ts — variants 工厂（统一管理入场/出场/hover/press 状态）
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - D5 motion_springs.schema.json §variants（enter/exit/hover/press + factory）
 *   - I3 frontend_motion.pyi §createMotionVariants + §MotionVariantsConfig TypedDict
 *   - C2 frontend_motion_config.schema.json §appleDesignPhysics.pointerDownScale=0.96
 *   - E1 frontend_error_codes.schema.json FE-MOT-006（character 误用）/ FE-MOT-008（参数校验）
 *
 * apple-design 原则落地:
 *   - §pointerDownImmediate: press 状态注入即时 scale 0.96，无 300ms 延迟（delayMs=0）
 *   - §springFirst: 所有 transition 使用 spring（springs 字典绑定）
 *   - §spatialConsistency: 进入和退出沿同一路径（enter/exit 使用同一 spring）
 *
 * OBS-C 守护:
 *   - springKey='character' + 存在 hover/press 状态 → 抛出 FE-MOT-006
 *     （角色立绘不会有 hover/press 交互，出现即说明 character spring 被误用于 UI 组件）
 *   - assertCharacterSpring() 供调用方在已知组件名时主动调用
 *
 * reduced-motion 分支:
 *   - prefers-reduced-motion: reduce 命中时降级为短 opacity crossfade（150ms，仅 opacity/color）
 *   - strategy='static' 时移除所有 transition（直接跳到目标状态）
 */

import { springs, type SpringKey } from './springs';
import {
  type Variants,
  MotionParameterError,
  prefersReducedMotion,
  APPLE_DESIGN_PHYSICS,
  REDUCED_MOTION_RULES,
} from './gsap-utils';

/**
 * variants 工厂配置。
 *
 * 对应 I3 frontend_motion.pyi §MotionVariantsConfig TypedDict:
 *   { springKey: SpringKey; states: { initial?; animate?; exit?; hover?; press? } }
 */
export interface MotionVariantsConfig {
  /** spring 预设名（绑定到 springs 字典对应预设） */
  readonly springKey: SpringKey;
  /** 各状态 variants 覆写（initial/animate/exit/hover/press） */
  readonly states?: Partial<VariantStates>;
}

/**
 * variants 五状态结构。
 *
 * 对齐 D5 §variants:
 *   - enter: { initial, animate, transition }
 *   - exit: { exit, transition }
 *   - hover: { hover, transition }
 *   - press: { press, transition }
 */
export interface VariantStates {
  /** 初始/隐藏状态（对应 D5 §variants.enter.initial） */
  initial: Record<string, unknown>;
  /** 动画目标/可见状态（对应 D5 §variants.enter.animate） */
  animate: Record<string, unknown>;
  /** 出场状态（对应 D5 §variants.exit.exit） */
  exit: Record<string, unknown>;
  /** hover 状态（对应 D5 §variants.hover.hover） */
  hover: Record<string, unknown>;
  /** press/tap 状态（对应 D5 §variants.press.press，注入即时 scale 0.96） */
  press: Record<string, unknown>;
}

/**
 * 默认 variants 状态模板（使用 springs.glass）。
 *
 * 对齐 D5 §variants.enter/exit/hover/press 的 default 值。
 */
const DEFAULT_VARIANTS: VariantStates = {
  initial: { opacity: 0, scale: 0.95, y: 8 },
  animate: { opacity: 1, scale: 1, y: 0 },
  exit: { opacity: 0, scale: 0.95, y: 8 },
  hover: { scale: 1.02 },
  press: { scale: APPLE_DESIGN_PHYSICS.pointerDownScale }, // 0.96，即时反馈
};

/**
 * 工厂函数: 统一管理入场/出场/hover/press 状态 variants。
 *
 * 对应 I3 frontend_motion.pyi §createMotionVariants。
 * 对齐 D5 §variants.factory:
 *   factoryName: 'createMotionVariants'
 *   input: springName: 'glass' | 'snappy' | 'gentle' | 'bouncy' | 'sheet'
 *   output: { initial, animate, exit, hover, press }
 *
 * 使用约定（D5 §variants）:
 *   - 业务组件通过 variants={createMotionVariants({...})} 复用
 *   - 禁止散落硬编码 variants
 *   - springKey 绑定到 springs 字典对应预设
 *
 * apple-design 原则落地:
 *   - §pointerDownImmediate: press 状态注入即时 scale 0.96（无 300ms 延迟）
 *   - §springFirst: transition 使用 spring（springKey 绑定）
 *   - §spatialConsistency: enter/exit 使用同一 spring（同路径进出）
 *
 * OBS-C 守护:
 *   - springKey='character' + 存在 hover/press 状态 → 抛出 FE-MOT-006
 *     （角色立绘不应有 hover/press 交互，出现即说明误用于 UI 组件）
 *
 * reduced-motion 分支:
 *   - prefers-reduced-motion: reduce 命中时降级为短 opacity crossfade（150ms）
 *   - strategy='static' 时 transition 设为 { duration: 0 }
 *
 * @param config variants 配置
 * @returns Variants: Framer Motion variants 对象，可直接传给 motion 组件的 variants prop
 * @throws {MotionParameterError} 当 springKey 不在 6 条预设 spring 中 / states 为空对象 / character spring 误用于 UI 交互时抛出
 */
export function createMotionVariants(config: MotionVariantsConfig): Variants {
  const { springKey, states } = config;

  // 参数校验 1: springKey 必须在 6 条预设 spring 中（运行时二次校验，类型层已约束）
  if (!springKey || !(springKey in springs)) {
    throw new MotionParameterError(
      `createMotionVariants: springKey '${springKey}' is not in 6 preset springs (glass/snappy/gentle/bouncy/character/sheet)`,
      'FE-MOT-008',
    );
  }

  // 参数校验 2: states 不能为空对象（如果提供了 states）
  if (states !== undefined && states !== null && Object.keys(states).length === 0) {
    throw new MotionParameterError(
      'createMotionVariants: states must not be an empty object',
      'FE-MOT-008',
    );
  }

  // OBS-C 守护: character spring + hover/press 状态 = UI 组件误用
  if (springKey === 'character') {
    assertCharacterSpringNotForUIInteraction(states);
  }

  // 获取 spring transition 配置
  const springPreset = springs[springKey];
  const springTransition = {
    type: springPreset.type,
    damping: springPreset.damping,
    stiffness: springPreset.stiffness,
    mass: springPreset.mass,
  };

  // 检测 prefers-reduced-motion
  const reducedMotion = prefersReducedMotion();

  // 合并默认状态与用户覆写
  const mergedStates = mergeVariantStates(DEFAULT_VARIANTS, states);

  // reduced-motion 分支: 降级 transition
  const transitionConfig = reducedMotion.reduced
    ? buildReducedMotionTransition(reducedMotion.strategy)
    : springTransition;

  // hover/press 使用 snappy spring（快速响应），除非 reduced-motion 命中
  const hoverPressTransition = reducedMotion.reduced
    ? buildReducedMotionTransition(reducedMotion.strategy)
    : {
        type: springs.snappy.type,
        damping: springs.snappy.damping,
        stiffness: springs.snappy.stiffness,
        mass: springs.snappy.mass,
      };

  // 构建 Framer Motion Variants 对象
  const variants: Variants = {
    initial: {
      ...mergedStates.initial,
      transition: transitionConfig,
    },
    animate: {
      ...mergedStates.animate,
      transition: transitionConfig,
    },
    exit: {
      ...mergedStates.exit,
      transition: transitionConfig,
    },
    hover: {
      ...mergedStates.hover,
      transition: hoverPressTransition,
    },
    // press 状态: 注入即时 scale 0.96（apple-design pointerDownImmediate）
    // delayMs=0 保证无 300ms 延迟
    press: {
      ...mergedStates.press,
      transition: {
        ...hoverPressTransition,
        delay: 0, // 无延迟，pointer-down 即时反馈
      },
    },
  };

  return variants;
}

/**
 * OBS-C 守护: 断言 character spring 未被用于 UI 交互（hover/press）。
 *
 * 角色立绘动效不应有 hover/press 交互状态。
 * 如果 character spring + hover/press 状态同时出现，说明被误用于 UI 组件。
 *
 * @throws {MotionParameterError} 当 character spring + hover/press 状态同时存在时抛出（errorCode=FE-MOT-006）
 */
function assertCharacterSpringNotForUIInteraction(
  states?: Partial<VariantStates>,
): void {
  if (!states) return;

  const hasHover = states.hover !== undefined && Object.keys(states.hover).length > 0;
  const hasPress = states.press !== undefined && Object.keys(states.press).length > 0;

  if (hasHover || hasPress) {
    const interactionType = hasHover && hasPress ? 'hover/press' : hasHover ? 'hover' : 'press';
    throw new MotionParameterError(
      `Character spring must not be used for UI interaction '${interactionType}', only for character portrait animation (useCaseRestriction=character-only)`,
      'FE-MOT-006',
    );
  }
}

/**
 * 合并默认 variant 状态与用户覆写。
 *
 * 深合并策略: 用户提供的 states 覆盖默认值，未提供的使用默认值。
 */
function mergeVariantStates(
  defaults: VariantStates,
  overrides?: Partial<VariantStates>,
): VariantStates {
  if (!overrides) {
    return defaults;
  }

  return {
    initial: { ...defaults.initial, ...overrides.initial },
    animate: { ...defaults.animate, ...overrides.animate },
    exit: { ...defaults.exit, ...overrides.exit },
    hover: { ...defaults.hover, ...overrides.hover },
    press: { ...defaults.press, ...overrides.press },
  };
}

/**
 * 构建 reduced-motion 降级 transition 配置。
 *
 * 对齐 D5 §reducedMotion.framerBehavior:
 *   - action: short-opacity-crossfade-or-static
 *   - maxDuration: 150ms
 *   - allowedProperties: [opacity, color]
 *
 * @param strategy 降级策略（'static' 或 'opacity-crossfade'）
 * @returns 降级 transition 配置
 */
function buildReducedMotionTransition(
  strategy: 'static' | 'opacity-crossfade',
): Record<string, unknown> {
  if (strategy === 'static') {
    // static: 无动画，直接跳到目标状态
    return { duration: 0 };
  }

  // opacity-crossfade: 短 opacity crossfade（150ms，仅 opacity/color）
  return {
    duration: REDUCED_MOTION_RULES.framerBehavior.maxDuration / 1000, // 转换为秒
    ease: 'linear', // reduced-motion 下允许 linear（例外，非主交互）
  };
}
