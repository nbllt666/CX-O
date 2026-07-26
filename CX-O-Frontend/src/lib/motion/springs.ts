/**
 * springs.ts — Framer Motion 6 条 spring 预设曲线
 *
 * 模块: 模块3 动效层
 * 契约对齐:
 *   - D5 motion_springs.schema.json §springs（6 spring 三参数 + useCase + appleDesignAlignment）
 *   - C2 frontend_motion_config.schema.json §springs（默认值与 D5 对齐）
 *   - I3 frontend_motion.pyi §springs 常量字典 + SpringConfig TypedDict
 *   - E1 frontend_error_codes.schema.json FE-MOT-002（spring 参数越界）/ FE-MOT-006（character 误用）
 *
 * 参数对齐模块1 token: src/styles/tokens/primitive.css §6.1 --motion-spring-* 系列
 *   --motion-spring-glass: 28 320 0.8        → springs.glass
 *   --motion-spring-snappy: 22 420 0.8       → springs.snappy
 *   --motion-spring-gentle: 32 200 1         → springs.gentle
 *   --motion-spring-bouncy: 14 280 1         → springs.bouncy
 *   --motion-spring-character: 18 240 1      → springs.character（OBS-C 收窄）
 *   --motion-spring-sheet: 30 300 1          → springs.sheet
 *
 * apple-design 对齐: damping ≥ 1.0 / response 0.3-0.4（bouncy/character 为例外，允许过冲）
 *
 * OBS-C 强约束: springs.character.useCaseRestriction = 'character-only'
 *   仅用于角色立绘动效，禁止用于任何 UI 组件。违反触发 FE-MOT-006。
 *   守护函数: assertCharacterSpring(componentName)
 */

import { MotionParameterError } from './gsap-utils';

/**
 * Spring 物理曲线配置。
 *
 * 对应 I3 frontend_motion.pyi §SpringConfig TypedDict:
 *   { type: 'spring'; damping: number; stiffness: number; mass: number }
 *
 * 参数范围约束由 D5 motion_springs.schema.json 定义（每条 spring 有独立 min/max）。
 */
export interface SpringConfig {
  /** 曲线类型，固定 'spring' */
  readonly type: 'spring';
  /** 阻尼系数（≥ 1.0 对齐 apple-design） */
  readonly damping: number;
  /** 刚度 */
  readonly stiffness: number;
  /** 质量 */
  readonly mass: number;
}

/**
 * Spring 预设名联合类型。
 *
 * 对应 I3 frontend_motion.pyi §MotionVariantsConfig.SpringKey:
 *   'glass' | 'snappy' | 'gentle' | 'bouncy' | 'character' | 'sheet'
 */
export type SpringKey = 'glass' | 'snappy' | 'gentle' | 'bouncy' | 'character' | 'sheet';

/**
 * Spring 使用场景限制枚举。
 * - 'character-only': 仅角色立绘动效（OBS-C 收窄，character spring 专属）
 * - 'unrestricted': 无限制（其他 5 条 spring）
 */
export type SpringUseCaseRestriction = 'character-only' | 'unrestricted';

/**
 * apple-design 对齐标记。
 * - 'damping-ge-1.0-response-0.3-0.4': 对齐 apple-design skill 默认
 * - 'exception-anime-only': 例外（二次元装饰专用，允许过冲）
 * - 'exception-character-only': 例外（角色专用，允许过冲）
 */
export type AppleDesignAlignment =
  | 'damping-ge-1.0-response-0.3-0.4'
  | 'exception-anime-only'
  | 'exception-character-only';

/**
 * 带元数据的 Spring 配置（含 useCase + useCaseRestriction + appleDesignAlignment）。
 *
 * 对齐 D5 motion_springs.schema.json §springs.* 每条 spring 的完整字段。
 */
export interface SpringPreset extends SpringConfig {
  /** 使用场景白名单 */
  readonly useCase: readonly string[];
  /** 使用场景限制（OBS-C: character spring = 'character-only'） */
  readonly useCaseRestriction: SpringUseCaseRestriction;
  /** apple-design 对齐标记 */
  readonly appleDesignAlignment: AppleDesignAlignment;
}

/**
 * UI 组件名黑名单——character spring 禁止用于以下 UI 组件。
 *
 * 来源: D5 motion_springs.schema.json §springs.character.useCaseRestriction.description
 *   "禁止用于任何 UI 组件（button/card/dialog/input/glass-panel 等）"
 *
 * 命中任一即触发 FE-MOT-006（character spring 误用）。
 */
const UI_COMPONENT_BLACKLIST: ReadonlySet<string> = new Set([
  'button',
  'card',
  'dialog',
  'input',
  'glasspanel',
  'sheet',
  'drawer',
  'tab',
  'toggle',
  'modal',
  'popover',
  'tooltip',
  'menu',
  'navbar',
  'sidebar',
  'form',
  'select',
  'checkbox',
  'radio',
  'slider',
  'switch',
]);

/**
 * 6 条 spring 预设曲线字典。
 *
 * 对齐 D5 motion_springs.schema.json §springs + I3 frontend_motion.pyi §springs 常量字典。
 * 参数与模块1 token src/styles/tokens/primitive.css §6.1 完全一致。
 *
 * apple-design 原则落地（§springFirst）:
 *   所有 UI 主交互过渡使用 spring，禁用 linear/ease-in-out（装饰循环例外，见 bezier.ts）。
 *
 * 使用约定:
 *   - glass:    玻璃面板/卡片/模态入场
 *   - snappy:   按钮反馈/toggle/tab 切换
 *   - gentle:   模态/默认过渡/页面淡入
 *   - bouncy:   二次元装饰专用（粒子弹跳/图标摇摆）——例外：允许过冲
 *   - character: 角色立绘动效（OBS-C: character-only，禁止 UI 组件）
 *   - sheet:    Sheet/Drawer 入场
 */
export const springs = {
  /**
   * 玻璃面板入场 spring——用于 Liquid Glass 面板/卡片入场。
   * D5 范围: damping [20,36] / stiffness [200,500] / mass [0.5,1.5]
   */
  glass: {
    type: 'spring' as const,
    damping: 28,
    stiffness: 320,
    mass: 0.8,
    useCase: ['glass-panel-enter', 'glass-card-enter', 'glass-modal-enter'] as const,
    useCaseRestriction: 'unrestricted' as const,
    appleDesignAlignment: 'damping-ge-1.0-response-0.3-0.4' as const,
  },

  /**
   * 按钮反馈 spring——快速响应，低过冲。
   * D5 范围: damping [18,28] / stiffness [300,600] / mass [0.5,1.5]
   */
  snappy: {
    type: 'spring' as const,
    damping: 22,
    stiffness: 420,
    mass: 0.8,
    useCase: ['button-press', 'toggle-switch', 'tab-switch'] as const,
    useCaseRestriction: 'unrestricted' as const,
    appleDesignAlignment: 'damping-ge-1.0-response-0.3-0.4' as const,
  },

  /**
   * 模态/默认过渡 spring——柔和。
   * D5 范围: damping [28,40] / stiffness [150,300] / mass [0.5,1.5]
   */
  gentle: {
    type: 'spring' as const,
    damping: 32,
    stiffness: 200,
    mass: 1,
    useCase: ['modal-transition', 'default-transition', 'page-fade'] as const,
    useCaseRestriction: 'unrestricted' as const,
    appleDesignAlignment: 'damping-ge-1.0-response-0.3-0.4' as const,
  },

  /**
   * 二次元装饰专用 spring——弹性足，用于装饰动效。
   * D5 范围: damping [10,18] / stiffness [200,400] / mass [0.5,1.5]
   * apple-design 例外: exception-anime-only（允许过冲，不强制对齐默认）
   */
  bouncy: {
    type: 'spring' as const,
    damping: 14,
    stiffness: 280,
    mass: 1,
    useCase: ['anime-decoration', 'particle-bounce', 'icon-wiggle'] as const,
    useCaseRestriction: 'unrestricted' as const,
    appleDesignAlignment: 'exception-anime-only' as const,
  },

  /**
   * 角色动作 spring——OBS-C 收窄：仅用于角色立绘动效，不用于 UI 组件。
   *
   * 违反触发 errorCodes.MOTION_CHARACTER_MISUSE (FE-MOT-006)。
   * 守护: assertCharacterSpring(componentName) 在 UI 组件调用时抛出异常。
   *
   * D5 范围: damping [14,24] / stiffness [180,320] / mass [0.5,1.5]
   * apple-design 例外: exception-character-only（允许过冲）
   */
  character: {
    type: 'spring' as const,
    damping: 18,
    stiffness: 240,
    mass: 1,
    useCase: ['character-portrait-enter', 'character-expression-change', 'character-bounce'] as const,
    useCaseRestriction: 'character-only' as const,
    appleDesignAlignment: 'exception-character-only' as const,
  },

  /**
   * Sheet/Drawer spring——底部抽屉/侧边抽屉。
   * D5 范围: damping [24,36] / stiffness [200,400] / mass [0.5,1.5]
   */
  sheet: {
    type: 'spring' as const,
    damping: 30,
    stiffness: 300,
    mass: 1,
    useCase: ['sheet-enter', 'drawer-enter', 'bottom-sheet'] as const,
    useCaseRestriction: 'unrestricted' as const,
    appleDesignAlignment: 'damping-ge-1.0-response-0.3-0.4' as const,
  },
} as const satisfies Record<SpringKey, SpringPreset>;

/**
 * D5 motion_springs.schema.json §springs 各 spring 的 [min, max] 范围表。
 *
 * 用于 validateSpringRange 校验。对齐 D5 schema 中每条 spring 的 minimum/maximum。
 */
const SPRING_RANGES: Record<
  SpringKey,
  { damping: [number, number]; stiffness: [number, number]; mass: [number, number] }
> = {
  glass: { damping: [20, 36], stiffness: [200, 500], mass: [0.5, 1.5] },
  snappy: { damping: [18, 28], stiffness: [300, 600], mass: [0.5, 1.5] },
  gentle: { damping: [28, 40], stiffness: [150, 300], mass: [0.5, 1.5] },
  bouncy: { damping: [10, 18], stiffness: [200, 400], mass: [0.5, 1.5] },
  character: { damping: [14, 24], stiffness: [180, 320], mass: [0.5, 1.5] },
  sheet: { damping: [24, 36], stiffness: [200, 400], mass: [0.5, 1.5] },
};

/**
 * 校验 spring 参数是否在 D5 schema 声明的 [min, max] 范围内。
 *
 * 对齐 D5 motion_springs.schema.json §springs.*.damping/stiffness/mass 的 minimum/maximum。
 * 越界时抛出 MotionParameterError（FE-MOT-002 spring 参数越界）。
 *
 * 注意: 本函数仅做范围校验，不阻止 character spring 用于 UI 组件（那是 assertCharacterSpring 的职责）。
 *
 * @param key spring 预设名
 * @param config spring 配置
 * @throws {MotionParameterError} 当 damping/stiffness/mass 任一超出 D5 范围时抛出（errorCode=FE-MOT-002）
 */
export function validateSpringRange(key: SpringKey, config: SpringConfig): void {
  const range = SPRING_RANGES[key];
  const checks: Array<['damping' | 'stiffness' | 'mass', number, [number, number]]> = [
    ['damping', config.damping, range.damping],
    ['stiffness', config.stiffness, range.stiffness],
    ['mass', config.mass, range.mass],
  ];

  for (const [paramName, value, [min, max]] of checks) {
    if (value < min || value > max) {
      throw new MotionParameterError(
        `Motion param ${paramName}=${value} out of range [${min}, ${max}] for spring '${key}'`,
        'FE-MOT-002',
      );
    }
  }
}

/**
 * OBS-C 守护: 断言 character spring 未被 UI 组件误用。
 *
 * 对齐 D5 motion_springs.schema.json §springs.character.useCaseRestriction = 'character-only'。
 * 违反触发 errorCodes.MOTION_CHARACTER_MISUSE (FE-MOT-006)。
 *
 * 调用方处理约定: block-build（阻断构建）。
 *
 * @param componentName 调用方组件名（如 'Button' / 'Card' / 'CharacterPortrait'）
 * @throws {MotionParameterError} 当 componentName 命中 UI 组件黑名单时抛出（errorCode=FE-MOT-006）
 */
export function assertCharacterSpring(componentName: string): void {
  const normalized = componentName.toLowerCase().replace(/[\s_-]/g, '');
  if (UI_COMPONENT_BLACKLIST.has(normalized)) {
    throw new MotionParameterError(
      `Character spring must not be used for UI component '${componentName}', only for character portrait animation (useCaseRestriction=character-only)`,
      'FE-MOT-006',
    );
  }
}

/**
 * 获取指定 spring 预设的纯物理参数（剥离元数据）。
 *
 * 用于传递给 Framer Motion 的 transition prop（Framer Motion 只认 type/damping/stiffness/mass）。
 *
 * @param key spring 预设名
 * @returns SpringConfig 物理参数
 */
export function getSpringTransition(key: SpringKey): SpringConfig {
  const preset = springs[key];
  return {
    type: preset.type,
    damping: preset.damping,
    stiffness: preset.stiffness,
    mass: preset.mass,
  };
}
