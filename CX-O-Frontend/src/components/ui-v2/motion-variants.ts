/**
 * @file motion-variants.ts — 引用模块3 springs 的 motion variants 工厂
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础设施
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\motion-variants.ts
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §GlassComponentProps.motionVariants + §Button/Card/Dialog/Tooltip/Table/Tabs/Badge/Avatar motion
 *   - D5 motion_springs.schema.json §springs（6 spring）+ §variants（enter/exit/hover/press）
 *   - I3 frontend_motion.pyi §springs + §createMotionVariants
 *   - merged.md §4.2 定制策略（Framer Motion variants 替换 shadcn 默认 Tailwind transition）
 *
 * 核心职责:
 *   - 引用模块3 springs 字典（6 spring 预设曲线）
 *   - 为波1+波2+波3+波4 15 组件（Button/Input/Card/Dialog/Tooltip/Form/Select/Checkbox/RadioGroup/Table/Tabs/Badge/Avatar/ChatPanel/AudioTrack）提供默认 spring 映射
 *   - 提供 getComponentMotionVariants 工厂，生成 Framer Motion variants
 *   - 替换 shadcn 默认 Tailwind transition（merged.md §4.2）
 *   - prefers-reduced-motion 命中时降级为静态状态（D5 §reducedMotion.framerBehavior）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块3 springs + createMotionVariants + Variants 类型
 *   - 禁止 import 模块5/7/8/9 内部实现
 *
 * OBS-C 守护（D5 §springs.character.useCaseRestriction = 'character-only'）:
 *   - character spring 仅用于角色立绘动效，禁止用于任何 UI 组件
 *   - 本文件默认 spring 映射不含 character，若调用方传入 character 则由模块3
 *     assertCharacterSpring 在 createMotionVariants 内部抛出 FE-MOT-006
 *
 * apple-design 原则落地（D5 §appleDesignPrinciples）:
 *   - §springFirst: 所有 transition 使用 spring（绑定 springs 字典）
 *   - §pointerDownImmediate: press 状态注入即时 scale 0.96（createMotionVariants 内置）
 *   - §spatialConsistency: enter/exit 使用同一 spring（同路径进出）
 * ============================================================================
 */

import {
  createMotionVariants,
  getSpringTransition,
  type SpringKey,
  type SpringConfig,
  type MotionVariantsConfig,
  type VariantStates,
} from '@/lib/motion';
import type { Variants } from 'framer-motion';

// =============================================================================
// 波1+波2+波3+波4 15 组件默认 spring 映射（对齐 I5 §Button/Input/Card/Dialog/Tooltip/Form/Select/Checkbox/RadioGroup/Table/Tabs/Badge/Avatar/ChatPanel/AudioTrack docstring）
// =============================================================================

/**
 * 波1+波2+波3+波4 15 组件支持的组件名联合类型。
 *
 * 对齐 C5 §shadcnMigrationWaves.wave1 + wave2 + wave3 + wave4:
 *   - wave1: ['Button', 'Input', 'Card', 'Dialog', 'Tooltip']
 *   - wave2: ['Form', 'Select', 'Checkbox', 'RadioGroup']
 *   - wave3: ['Table', 'Tabs', 'Badge', 'Avatar']
 *   - wave4: ['ChatPanel', 'AudioTrack']（业务封装，基于 shadcn 基础组件重组）
 */
export type Wave1_2_3_4ComponentName =
  | 'Button'
  | 'Input'
  | 'Card'
  | 'Dialog'
  | 'Tooltip'
  | 'Form'
  | 'Select'
  | 'Checkbox'
  | 'RadioGroup'
  | 'Table'
  | 'Tabs'
  | 'Badge'
  | 'Avatar'
  | 'ChatPanel'
  | 'AudioTrack';

/**
 * 波1+波2+波3 13 组件支持的组件名联合类型（向后兼容别名）。
 *
 * @deprecated 使用 Wave1_2_3_4ComponentName 代替。波4 扩展后保留此别名以维持向后兼容。
 */
export type Wave1_2_3ComponentName = Exclude<Wave1_2_3_4ComponentName, 'ChatPanel' | 'AudioTrack'>;

/**
 * 波1+波2 9 组件支持的组件名联合类型（向后兼容别名）。
 *
 * @deprecated 使用 Wave1_2_3ComponentName 代替。波3 扩展后保留此别名以维持向后兼容。
 */
export type Wave1_2ComponentName =
  | 'Button'
  | 'Input'
  | 'Card'
  | 'Dialog'
  | 'Tooltip'
  | 'Form'
  | 'Select'
  | 'Checkbox'
  | 'RadioGroup';

/**
 * 波1 5 组件支持的组件名联合类型（向后兼容别名）。
 *
 * @deprecated 使用 Wave1_2_3ComponentName 代替。波2 扩展后保留此别名以维持向后兼容。
 */
export type Wave1ComponentName =
  | 'Button'
  | 'Input'
  | 'Card'
  | 'Dialog'
  | 'Tooltip';

/**
 * 波1+波2+波3+波4 15 组件默认 spring 映射（对齐 I5 §Button/Input/Card/Dialog/Tooltip/Form/Select/Checkbox/RadioGroup/Table/Tabs/Badge/Avatar/ChatPanel/AudioTrack docstring）。
 *
 * 映射依据（I5 docstring + D5 §springs.useCase）:
 *   - Button: snappy（按钮反馈，快速响应低过冲，D5 §springs.snappy.useCase=button-press）
 *   - Input: snappy（输入框聚焦反馈，快速响应）
 *   - Card: glass（玻璃面板入场，D5 §springs.glass.useCase=glass-card-enter）
 *   - Dialog: gentle（模态过渡，柔和，D5 §springs.gentle.useCase=modal-transition）
 *   - Tooltip: snappy（出现/消失快速响应，D5 §springs.snappy.useCase）
 *   - Form: gentle（表单容器整体过渡，柔和反馈，D5 §springs.gentle.useCase=default-transition）
 *   - Select: snappy（下拉触发器快速响应，D5 §springs.snappy.useCase=button-press）
 *   - Checkbox: snappy（勾选反馈快速响应，D5 §springs.snappy.useCase=button-press）
 *   - RadioGroup: snappy（单选切换快速响应，D5 §springs.snappy.useCase=toggle-switch）
 *   - Table: snappy（表格行 hover/选中反馈快速响应，D5 §springs.snappy.useCase=button-press）
 *   - Tabs: snappy（Tab 切换快速响应，apple-design §pointerDownImmediate）
 *   - Badge: glass（徽章入场柔和，D5 §springs.glass.useCase=glass-card-enter）
 *   - Avatar: glass（头像入场柔和，与 Card 一致，D5 §springs.glass.useCase=glass-card-enter）
 *   - ChatPanel: sheet（聊天面板入场，对齐 D5 §springs.sheet.useCase=sheet-modal）
 *   - AudioTrack: snappy（音轨交互快速响应，与时间线精度协同）
 *
 * OBS-C 守护: 所有默认 spring 均非 character（character 仅用于角色立绘）。
 *   - ChatPanel 虽集成角色情绪（I4 EmotionType），但面板本身非角色立绘，使用 sheet spring
 *   - AudioTrack 是音轨组件，使用 snappy spring
 *   - 注意 merged.md §4.4.1 表格 wave4 列出 "character / sheet"，但 character 仅用于角色立绘动效
 *     （D5 §springs.character.useCaseRestriction=character-only），业务封装组件不使用 character spring
 * apple-design 对齐: 所有 spring 均对齐 damping ≥ 1.0 / response 0.3-0.4。
 */
export const DEFAULT_COMPONENT_SPRINGS: Readonly<Record<Wave1_2_3_4ComponentName, SpringKey>> = {
  // wave1 基础组件
  Button: 'snappy',
  Input: 'snappy',
  Card: 'glass',
  Dialog: 'gentle',
  Tooltip: 'snappy',
  // wave2 表单组件
  Form: 'gentle',
  Select: 'snappy',
  Checkbox: 'snappy',
  RadioGroup: 'snappy',
  // wave3 数据展示组件
  Table: 'snappy',
  Tabs: 'snappy',
  Badge: 'glass',
  Avatar: 'glass',
  // wave4 业务封装组件（基于 shadcn 基础组件重组，I5 §ChatPanel/AudioTrack docstring）
  ChatPanel: 'sheet', // 聊天面板入场，对齐 D5 §springs.sheet.useCase=sheet-modal（OBS-C: 非 character）
  AudioTrack: 'snappy', // 音轨交互快速响应，与时间线精度协同（OBS-C: 非 character）
} as const;

// =============================================================================
// 组件 motion 配置类型
// =============================================================================

/**
 * 组件 motion 配置（生成 Framer Motion motion 组件 props）。
 *
 * 此配置用于 getComponentMotionProps 返回值，可直接展开到 motion 组件。
 */
export interface ComponentMotionProps {
  /** Framer Motion variants 对象（由 createMotionVariants 生成） */
  readonly variants: Variants;
  /** 初始状态 variant 名 */
  readonly initial: string;
  /** 动画目标状态 variant 名 */
  readonly animate: string;
  /** 出场状态 variant 名 */
  readonly exit: string;
  /** hover 状态 variant 名 */
  readonly whileHover: string;
  /** press/tap 状态 variant 名 */
  readonly whileTap: string;
}

/**
 * 组件 motion variants 工厂配置（扩展 MotionVariantsConfig，附加 componentName）。
 */
export interface ComponentMotionVariantsConfig {
  /** 组件名（用于查找默认 spring 映射，支持波1+波2+波3+波4 15 组件） */
  readonly componentName: Wave1_2_3_4ComponentName;
  /** spring 预设 key（覆盖默认映射，可选。禁止使用 'character'，OBS-C） */
  readonly springKey?: SpringKey;
  /** variants 状态覆写（initial/animate/exit/hover/press） */
  readonly states?: Partial<VariantStates>;
}

// =============================================================================
// getComponentMotionVariants 工厂函数
// =============================================================================

/**
 * 工厂: 为波1+波2+波3+波4 15 组件生成 Framer Motion motion variants。
 *
 * 对齐 I5 §GlassComponentProps.motionVariants + D5 §variants.factory:
 *   factoryName: 'createMotionVariants'
 *   input: springName: 'glass' | 'snappy' | 'gentle' | 'bouncy' | 'sheet'
 *   output: { initial, animate, exit, hover, press }
 *
 * 职责:
 *   1. 查找组件默认 spring 映射（DEFAULT_COMPONENT_SPRINGS）
 *   2. 若调用方提供 springKey 则覆盖默认映射
 *   3. 调用模块3 createMotionVariants 生成 variants
 *   4. prefers-reduced-motion 命中时由 createMotionVariants 内部降级（D5 §reducedMotion）
 *
 * OBS-C 守护:
 *   - springKey='character' 时由 createMotionVariants 内部 assertCharacterSpringNotForUIInteraction 抛出 FE-MOT-006
 *   - 本函数不重复守护，依赖模块3 单一真相源
 *
 * @param config 组件 motion 配置（componentName + 可选 springKey/states 覆写）
 * @returns Framer Motion Variants 对象，可直接传给 motion 组件的 variants prop
 */
export function getComponentMotionVariants(config: ComponentMotionVariantsConfig): Variants {
  const { componentName, springKey, states } = config;

  // 查找组件默认 spring（若调用方未提供 springKey）
  const resolvedSpringKey: SpringKey = springKey ?? DEFAULT_COMPONENT_SPRINGS[componentName];

  // 调用模块3 createMotionVariants 生成 variants
  // createMotionVariants 内部处理:
  //   - springKey 合法性校验（FE-MOT-008）
  //   - OBS-C character 守护（FE-MOT-006）
  //   - prefers-reduced-motion 降级（D5 §reducedMotion.framerBehavior）
  //   - apple-design pointerDownImmediate（press scale 0.96，delayMs=0）
  const motionConfig: MotionVariantsConfig = {
    springKey: resolvedSpringKey,
    states,
  };

  // 类型断言: 模块3 Variants（Record<string, unknown>）→ framer-motion Variants
  // 两者结构兼容，但 TypeScript 严格模式下索引签名不兼容，需 as unknown as 断言
  return createMotionVariants(motionConfig) as unknown as Variants;
}

// =============================================================================
// getComponentMotionProps 工厂函数（生成 motion 组件 props）
// =============================================================================

/**
 * 工厂: 为波1+波2+波3+波4 15 组件生成 Framer Motion motion 组件 props。
 *
 * 返回值可直接展开到 motion 组件:
 *   ```tsx
 *   const motionProps = getComponentMotionProps({ componentName: 'Button' });
 *   <motion.button {...motionProps}>...</motion.button>
 *   ```
 *
 * 若调用方提供 motionVariants（I5 §GlassComponentProps.motionVariants），则直接使用调用方 variants，
 * 不再调用 getComponentMotionVariants（尊重调用方覆写）。
 *
 * @param config 组件 motion 配置（componentName + 可选 springKey/states 覆写 + 可选 motionVariants 覆写）
 * @returns motion 组件 props（variants + initial + animate + exit + whileHover + whileTap）
 */
export function getComponentMotionProps(
  config: ComponentMotionVariantsConfig & { motionVariants?: Variants },
): ComponentMotionProps {
  const { motionVariants } = config;

  // 若调用方提供 motionVariants（I5 §GlassComponentProps.motionVariants），直接使用
  // 否则调用 getComponentMotionVariants 生成默认 variants
  const variants: Variants = motionVariants ?? getComponentMotionVariants(config);

  // 返回 motion 组件 props（variant 名固定为 createMotionVariants 输出的 5 状态）
  return {
    variants,
    initial: 'initial',
    animate: 'animate',
    exit: 'exit',
    whileHover: 'hover',
    whileTap: 'press',
  };
}

// =============================================================================
// 辅助: 获取组件默认 spring key
// =============================================================================

/**
 * 辅助: 获取波1+波2+波3+波4 15 组件的默认 spring key。
 *
 * 对齐 DEFAULT_COMPONENT_SPRINGS 映射表。用于组件内部需要查询默认 spring 时调用。
 *
 * @param componentName 组件名（支持波1+波2+波3+波4 15 组件）
 * @returns 默认 spring key（snappy/glass/gentle/sheet）
 */
export function getDefaultComponentSpring(componentName: Wave1_2_3_4ComponentName): SpringKey {
  return DEFAULT_COMPONENT_SPRINGS[componentName];
}

// =============================================================================
// 辅助: 校验 spring key 是否可用于 UI 组件（OBS-C 守护便捷函数）
// =============================================================================

/**
 * 辅助: 校验 spring key 是否可用于 UI 组件（OBS-C 守护便捷函数）。
 *
 * 对齐 D5 §springs.character.useCaseRestriction = 'character-only'。
 * character spring 仅用于角色立绘动效，禁止用于任何 UI 组件。
 *
 * @param springKey 待校验的 spring key
 * @returns true 如果 spring key 可用于 UI 组件（即非 character）
 */
export function isSpringKeyForUI(springKey: SpringKey): boolean {
  return springKey !== 'character';
}

// =============================================================================
// 辅助: 获取 spring 物理参数（剥离元数据，供 Framer Motion transition prop 使用）
// =============================================================================

/**
 * 辅助: 获取指定 spring 的纯物理参数（剥离元数据）。
 *
 * 委托模块3 getSpringTransition 实现，用于传递给 Framer Motion 的 transition prop。
 * Framer Motion 只认 type/damping/stiffness/mass 四字段。
 *
 * @param springKey spring 预设名
 * @returns SpringConfig 物理参数（type/damping/stiffness/mass）
 */
export function getComponentSpringTransition(springKey: SpringKey): SpringConfig {
  return getSpringTransition(springKey);
}
