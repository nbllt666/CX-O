/**
 * @file inject-glass-style.ts — Liquid Glass 样式注入工具（fork 后注入，不靠 props 传递）
 * ============================================================================
 * 模块: 模块6 基础组件层（shadcn ui-v2）— 波1 基础设施
 * 落点: C:\CX-O\CX-O-Frontend\src\components\ui-v2\inject-glass-style.ts
 *
 * 契约对齐:
 *   - I5 frontend_components_uiv2.pyi §injectGlassStyle + §GlassInjectionConfig + §GlassInjectionError
 *   - D2 glass_tier_config.schema.json（GlassTier 1-4 唯一真相源）
 *   - D1 frontend_design_tokens.schema.json（token 消费，glass.css 提供 Tier 3 CSS 变量）
 *   - E1 frontend_error_codes.schema.json COM 段（FE-COM-001/002/003/004）
 *   - merged.md §4.2 定制策略（fork 后注入，避免 API 污染）
 *
 * 核心约束（I5 §injectGlassStyle + merged.md §4.2）:
 *   - shadcn 源码 fork 到 ui-v2/，直接修改源码注入 Liquid Glass 样式
 *   - **不靠 props 传递**，避免 API 污染（核心约束）
 *   - 注入 data-glass 属性（若 injectDataAttribute=true）
 *   - 注入 Framer Motion variants 替换 shadcn 默认 Tailwind transition（若 injectMotionVariants=true）
 *   - 绑定 springKey 到对应 spring 预设（来自 I3 springs 字典）
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-6 AGENTS.md §4.3）:
 *   - 仅 import 模块3 springs（校验 springKey 合法性 + OBS-C character 守护）
 *   - 仅 import 模块4 GlassTier 类型（D2 唯一真相源）
 *   - 禁止 import 模块5/7/8/9 内部实现
 *   - 禁止硬编码颜色（通过 className + Tailwind utility 消费 token）
 *
 * 错误码（E1 COM 段，本模块注册）:
 *   - FE-COM-001: 单组件迁移违规（migrateWave 校验失败，单组件层）
 *   - FE-COM-002: Glass 注入失败（本文件 GlassInjectionError 抛出）
 *   - FE-COM-003: 单页面混用新旧组件（单页面层）
 *   - FE-COM-004: 单组件零引用（legacy 删除前未清理）
 *   注意: MIG 段错误码（FE-MIG-001/002/003/004）属于模块0 迁移编排层，不在本模块注册
 * ============================================================================
 */

import { springs, type SpringKey } from '@/lib/motion';
import type { GlassTier } from '@/lib/glass/tier-detector';

// =============================================================================
// GlassTier 范围常量（对齐 D2 glass_tier_config.schema.json tiers.tierId）
// =============================================================================

/** GlassTier 合法范围（D2 唯一真相源：1 | 2 | 3 | 4） */
const GLASS_TIER_RANGE: ReadonlySet<number> = new Set([1, 2, 3, 4]);

// =============================================================================
// COM 段错误码注册表（对齐 E1 frontend_error_codes.schema.json COM 段）
// =============================================================================

/** COM 段错误码字面量联合类型（对齐 E1 COM 段） */
export type ComErrorCode = 'FE-COM-001' | 'FE-COM-002' | 'FE-COM-003' | 'FE-COM-004';

/** COM 段错误码元数据（对齐 E1 §errorCodes COM 段 4 个错误码的完整定义） */
export interface ComErrorCodeDefinition {
  readonly code: ComErrorCode;
  readonly name: string;
  readonly severity: 'error' | 'warning';
  readonly description: string;
  readonly trigger: string;
  readonly relatedContract: readonly string[];
}

/**
 * COM 段错误码注册表（对齐 E1 §errorCodes COM 段）。
 *
 * 此常量是模块6 抛出异常时的错误码元数据唯一来源，禁止在其他位置硬编码错误码描述。
 * 4 个错误码均已在 E1 frontend_error_codes.schema.json 的 COM 段注册（GN-004 OBS-S3-4 修复）。
 */
export const COM_ERROR_CODES: Readonly<Record<ComErrorCode, ComErrorCodeDefinition>> = {
  'FE-COM-001': {
    code: 'FE-COM-001',
    name: '迁移违规（单组件层）',
    severity: 'error',
    description:
      'validateMigration 校验单组件时发现阻断式违规（如关键组件缺失 data-glass 属性）。' +
      '注意：与 FE-MIG-001 区分——本错误码是单组件执行层违规，FE-MIG-001 是波次编排层阻塞。',
    trigger:
      'validateMigration 单组件校验：组件缺失 data-glass 属性 / motion variants 未替换默认 transition / 硬编码颜色。' +
      '仅由模块6 组件层抛出。',
    relatedContract: ['I5 frontend_components_uiv2.pyi', 'E1 frontend_error_codes.schema.json'],
  },
  'FE-COM-002': {
    code: 'FE-COM-002',
    name: 'Glass 注入失败',
    severity: 'error',
    description:
      'injectGlassStyle 执行 Liquid Glass 样式注入时失败（componentName 无效 / shadcn 源码不存在 / ' +
      'glassTier 无效 / springKey 不在 I3 springs 字典中 / 源码注入失败）。',
    trigger:
      'injectGlassStyle: componentName 不是有效 shadcn 组件 / glassTier 不在 1-4 范围 / ' +
      'springKey 不在 I3 springs 字典 / springKey=character 误用于 UI 组件（OBS-C）。',
    relatedContract: ['I5 frontend_components_uiv2.pyi', 'D5 motion_springs.schema.json'],
  },
  'FE-COM-003': {
    code: 'FE-COM-003',
    name: '新旧组件混用（单页面层）',
    severity: 'error',
    description:
      'validateMigration 检测到同一页面同时引用 @/components/（旧）和 @/components/ui-v2/（新）组件。' +
      '注意：与 FE-MIG-003 区分——本错误码是单页面混用检测，FE-MIG-003 是 lint 规则编排层冲突。',
    trigger:
      'validateMigration 页面级校验：同页面同时引用 components/ 与 ui-v2/ 组件。' +
      '由 eslint-plugin-import 自定义规则或模块6 校验工具抛出。',
    relatedContract: ['I5 frontend_components_uiv2.pyi', 'C5 frontend_migration_config.schema.json'],
  },
  'FE-COM-004': {
    code: 'FE-COM-004',
    name: '旧组件零引用校验失败（单组件层）',
    severity: 'error',
    description:
      'deleteLegacy 单组件级零引用扫描失败（仍有页面引用 @/components/_legacy/ 组件）。' +
      '注意：与 FE-MIG-004 区分——本错误码是单组件层零引用校验，FE-MIG-004 是 _legacy/ 目录整体删除校验。',
    trigger:
      '单组件级零引用扫描：删除旧组件前检测到仍有页面引用。' +
      '由模块6 单组件零引用校验工具抛出。',
    relatedContract: ['I5 frontend_components_uiv2.pyi', 'C5 frontend_migration_config.schema.json'],
  },
} as const;

// =============================================================================
// 异常类（对应 I5 §GlassInjectionError，FE-COM-002）
// =============================================================================

/**
 * Liquid Glass 样式注入异常（对应 I5 §GlassInjectionError）。
 *
 * 抛出条件（对齐 I5 §GlassInjectionError + E1 §FE-COM-002.trigger）:
 *   - injectGlassStyle: componentName 不是有效 shadcn 组件
 *   - injectGlassStyle: shadcn 源码文件不存在（fork 失败）
 *   - injectGlassStyle: glassTier 无效（不在 1-4 范围）
 *   - injectGlassStyle: springKey 不在 I3 springs 字典中
 *   - injectGlassStyle: springKey=character 误用于 UI 组件（OBS-C 守护）
 *   - injectGlassStyle: 源码注入失败（语法错误/占位符未找到）
 *
 * 调用方处理约定（对齐 I5 §GlassInjectionError 调用方处理）:
 *   - 捕获后降级到 Tier 3 CSS backdrop-filter（merged.md §4.3 OBS-D）
 *   - 在 note 中记录注入失败事件
 *   - 上报玻璃注入失败告警
 *
 * 错误码: FE-COM-002（对应 E1 frontend_error_codes.schema.json Glass 注入失败）
 */
export class GlassInjectionError extends Error {
  /** 错误码（固定 FE-COM-002） */
  public readonly errorCode: ComErrorCode;
  /** 严重级别（对齐 E1 §errorCodes.severity） */
  public readonly severity: 'error' | 'warning';
  /** 触发该异常的组件名（用于 note 记录与 GN-004 审查回溯） */
  public readonly componentName: string;

  constructor(message: string, componentName: string) {
    super(message);
    this.name = 'GlassInjectionError';
    this.errorCode = 'FE-COM-002';
    this.severity = COM_ERROR_CODES['FE-COM-002'].severity;
    this.componentName = componentName;
    // 维持原型链（TS 编译到 ES5 后 extends Error 的已知问题修复）
    Object.setPrototypeOf(this, GlassInjectionError.prototype);
  }

  /** 获取错误码元数据（对齐 E1 §errorCodes 完整字段） */
  getErrorDefinition(): ComErrorCodeDefinition {
    return COM_ERROR_CODES['FE-COM-002'];
  }
}

// =============================================================================
// GlassInjectionConfig（对应 I5 §GlassInjectionConfig TypedDict）
// =============================================================================

/**
 * Liquid Glass 样式注入配置（对应 I5 §GlassInjectionConfig）。
 *
 * 对应 merged.md §4.2: shadcn 源码 fork 后注入 Liquid Glass 样式。
 */
export interface GlassInjectionConfig {
  /** shadcn 组件名（Button/Input/Card/Dialog/Tooltip 等） */
  readonly componentName: string;
  /** 目标 glass tier（1-4，D2 唯一真相源） */
  readonly glassTier: GlassTier;
  /** spring 预设 key（来自 I3 springs 字典：glass/snappy/gentle/bouncy/character/sheet） */
  readonly springKey: SpringKey;
  /** 是否注入 data-glass 属性（由 WebGL 层接管渲染） */
  readonly injectDataAttribute: boolean;
  /** 是否注入 Framer Motion variants 替换 shadcn 默认 transition */
  readonly injectMotionVariants: boolean;
}

// =============================================================================
// 波1 支持的 shadcn 组件名白名单（对齐 C5 shadcnMigrationWaves.wave1.components）
// =============================================================================

/**
 * 波1 支持的 shadcn 组件名白名单（对齐 C5 §shadcnMigrationWaves.wave1.components）。
 *
 * injectGlassStyle 仅支持波1 5 组件 + 后续波次组件（wave2/wave3/wave4）。
 * 不在此白名单的 componentName 抛出 GlassInjectionError（FE-COM-002）。
 */
const SUPPORTED_COMPONENT_NAMES: ReadonlySet<string> = new Set([
  // wave1 基础组件
  'Button',
  'Input',
  'Card',
  'Dialog',
  'Tooltip',
  // wave2 表单组件（预留，波2 实现后启用）
  'Form',
  'Select',
  'Checkbox',
  'RadioGroup',
  // wave3 数据展示组件（预留）
  'Table',
  'Tabs',
  'Badge',
  'Avatar',
  // wave4 业务封装组件（预留）
  'ChatPanel',
  'AudioTrack',
]);

/**
 * UI 组件黑名单（OBS-C 守护：character spring 禁用于 UI 组件）。
 *
 * 对齐 D5 motion_springs.schema.json §springs.character.useCaseRestriction = 'character-only'。
 * 当 springKey='character' 且 componentName 命中此黑名单时，抛出 GlassInjectionError（FE-COM-002）。
 *
 * 注意：此处的守护是 injectGlassStyle 层的二次防线，模块3 assertCharacterSpring 是一层守护。
 */
const UI_COMPONENT_BLACKLIST_FOR_CHARACTER: ReadonlySet<string> = new Set([
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
  'radiogroup',
  'slider',
  'switch',
  'table',
  'badge',
  'avatar',
]);

// =============================================================================
// injectGlassStyle 主函数（对应 I5 §injectGlassStyle）
// =============================================================================

/**
 * 函数: shadcn 组件源码 fork 后注入 Liquid Glass 样式（对应 I5 §injectGlassStyle）。
 *
 * 实现细节（merged.md §4.2）:
 *   - shadcn 源码 fork 到 ui-v2/，直接修改源码注入 Liquid Glass 样式
 *   - **不靠 props 传递**，避免 API 污染（核心约束）
 *   - 注入 data-glass 属性（若 injectDataAttribute=true）
 *   - 注入 Framer Motion variants 替换 shadcn 默认 Tailwind transition（若 injectMotionVariants=true）
 *   - 绑定 springKey 到对应 spring 预设（来自 I3 springs 字典）
 *
 * 本函数职责:
 *   1. 校验 config 字段合法性（componentName/glassTier/springKey）
 *   2. OBS-C 守护：character spring 禁用于 UI 组件
 *   3. 返回注入后的组件源码路径（如 `src/components/ui-v2/Button.tsx`）
 *
 * 实际的源码注入由开发者在 fork shadcn 源码时手动完成（本函数提供配置校验与路径生成）。
 * 运行时由 injectGlassClassName / buildGlassDataAttributes 辅助函数为组件动态注入样式。
 *
 * @param config 玻璃样式注入配置（componentName / glassTier / springKey / injectDataAttribute / injectMotionVariants）
 * @returns 注入后的组件源码路径（如 `src/components/ui-v2/Button.tsx`）
 * @throws {GlassInjectionError} 当 componentName 无效 / glassTier 无效 / springKey 不在 I3 springs 字典中 / springKey=character 误用于 UI 组件时抛出（errorCode=FE-COM-002）
 */
export function injectGlassStyle(config: GlassInjectionConfig): string {
  const { componentName, glassTier, springKey, injectDataAttribute, injectMotionVariants } = config;

  // 校验 1: componentName 必须在白名单内
  if (!componentName || !SUPPORTED_COMPONENT_NAMES.has(componentName)) {
    throw new GlassInjectionError(
      `injectGlassStyle: componentName '${componentName}' is not a valid shadcn component ` +
        `(supported: ${Array.from(SUPPORTED_COMPONENT_NAMES).join('/ ')})`,
      componentName,
    );
  }

  // 校验 2: glassTier 必须在 1-4 范围（D2 唯一真相源）
  if (!GLASS_TIER_RANGE.has(glassTier)) {
    throw new GlassInjectionError(
      `injectGlassStyle: glassTier ${glassTier} is invalid, must be one of [1, 2, 3, 4] ` +
        `(D2 glass_tier_config.schema.json tiers.tierId)`,
      componentName,
    );
  }

  // 校验 3: springKey 必须在 I3 springs 字典中
  if (!springKey || !(springKey in springs)) {
    throw new GlassInjectionError(
      `injectGlassStyle: springKey '${springKey}' is not in I3 springs dictionary ` +
        `(valid: glass/snappy/gentle/bouncy/character/sheet)`,
      componentName,
    );
  }

  // OBS-C 守护: character spring 禁用于 UI 组件（D5 §springs.character.useCaseRestriction）
  if (springKey === 'character') {
    const normalized = componentName.toLowerCase().replace(/[\s_-]/g, '');
    if (UI_COMPONENT_BLACKLIST_FOR_CHARACTER.has(normalized)) {
      throw new GlassInjectionError(
        `injectGlassStyle: character spring must not be used for UI component '${componentName}' ` +
          `(OBS-C: useCaseRestriction=character-only, only for character portrait animation)`,
        componentName,
      );
    }
  }

  // 返回注入后的组件源码路径（约定路径：src/components/ui-v2/{ComponentName}.tsx）
  const targetPath = `src/components/ui-v2/${componentName}.tsx`;

  // 标记注入配置（用于 note 记录与 GN-004 审查回溯，不影响返回值）
  // injectDataAttribute / injectMotionVariants 控制注入范围，此处仅做语义记录
  void injectDataAttribute;
  void injectMotionVariants;

  return targetPath;
}

// =============================================================================
// 运行时辅助函数：为组件动态注入 glass 样式（Tier 3 CSS 降级路径）
// =============================================================================

/**
 * 运行时辅助: 为组件 className 注入 Liquid Glass 样式类（Tier 3 CSS 降级路径）。
 *
 * 对齐 D2 glass_tier_config.schema.json §tiers.tier3.technology:
 *   css-backdrop-filter-blur16-saturate1.8-box-shadow-svg-filter
 *
 * 消费 token（不硬编码，对齐 D1 + glass.css）:
 *   - backdrop-filter: var(--glass-tier3-backdrop-filter) → blur(16px) saturate(1.8)
 *   - background: var(--glass-bg) → 半透明玻璃背景
 *   - box-shadow: var(--glass-edge-highlight) → 多层 box-shadow 高光
 *   - border: var(--glass-border) → 玻璃边框
 *
 * 双主题自动切换（对齐 D3 + merged.md §4.2）:
 *   通过 CSS 变量自动切换，无需 JS 介入。theme-dark.css / theme-light.css 通过 [data-theme] 覆盖。
 *
 * @param baseClassName 组件基础 className（来自 shadcn 原生样式）
 * @param glassTier 当前 glass tier（仅 Tier 3/4 注入 CSS 降级样式，Tier 1/2 由 WebGL 层接管）
 * @returns 注入 glass 样式后的 className 字符串
 */
export function injectGlassClassName(baseClassName: string, glassTier: GlassTier): string {
  // Tier 1/2: 由 WebGL 层接管渲染（GlassRenderer 扫描 data-glass 元素），CSS 层仅保留透明背景
  // Tier 3: CSS backdrop-filter 降级路径（blur 16px saturate 1.8 + 多层 box-shadow）
  // Tier 4: background-color 半透明兜底（无 blur）
  const tier3GlassClasses = [
    'backdrop-[var(--glass-tier3-backdrop-filter)]',
    'bg-[var(--glass-bg)]',
    'shadow-[var(--glass-edge-highlight)]',
    'border-[var(--glass-border)]',
  ];

  const tier4GlassClasses = ['bg-[var(--glass-bg)]', 'border-[var(--glass-border)]'];

  // Tier 1/2: 仅注入最小透明背景类，WebGL 层负责实际玻璃渲染
  const tier12GlassClasses = ['bg-transparent'];

  let glassClasses: string[];
  if (glassTier === 3) {
    glassClasses = tier3GlassClasses;
  } else if (glassTier === 4) {
    glassClasses = tier4GlassClasses;
  } else {
    // Tier 1/2: WebGL 接管，CSS 层透明
    glassClasses = tier12GlassClasses;
  }

  // 合并基础 className 与 glass 样式类（基础在前，glass 在后覆盖）
  return [baseClassName, ...glassClasses].filter(Boolean).join(' ');
}

/**
 * 运行时辅助: 构建 data-glass + data-glass-tier 属性对象（由 WebGL 层接管渲染）。
 *
 * 对齐 I5 §GlassComponentProps.dataGlass + I5 §GlassComponentProps.glassTier:
 *   - data-glass="true": 标记为 Liquid Glass 元素，由 I1 GlassRenderer 扫描接管渲染
 *   - data-glass-tier="tier{N}": 标记目标 tier，对齐 D2 tiers.tierId
 *
 * 属性值对齐 D2 glass_tier_config.schema.json §tiers.tier*.name:
 *   - tier1-webgl2 / tier2-webgl1 / tier3-css / tier4-solid
 *
 * @param dataGlass 是否挂载 data-glass 属性（默认 true）
 * @param glassTier 目标 glass tier（1-4，可选，默认不挂载 data-glass-tier）
 * @returns 属性对象，可直接展开到组件 props
 */
export function buildGlassDataAttributes(
  dataGlass: boolean,
  glassTier?: GlassTier,
): Record<string, string> {
  const attributes: Record<string, string> = {};

  if (dataGlass) {
    attributes['data-glass'] = 'true';
  }

  if (glassTier !== undefined && GLASS_TIER_RANGE.has(glassTier)) {
    // 对齐 D2 §tiers.tier*.name 的语义化 tier 标识
    const tierNameMap: Record<number, string> = {
      1: 'tier1-webgl2',
      2: 'tier2-webgl1',
      3: 'tier3-css',
      4: 'tier4-solid',
    };
    attributes['data-glass-tier'] = tierNameMap[glassTier] ?? `tier${glassTier}`;
  }

  return attributes;
}

// =============================================================================
// GlassTier 范围守卫（供组件层使用）
// =============================================================================

/**
 * 守卫: 校验 glassTier 是否在合法范围（1-4）。
 *
 * 对齐 D2 glass_tier_config.schema.json §tiers.tierId: integer 1-4 唯一真相源。
 *
 * @param tier 待校验的 tier 值
 * @returns true 如果 tier 在 1-4 范围内
 */
export function isValidGlassTier(tier: unknown): tier is GlassTier {
  return typeof tier === 'number' && GLASS_TIER_RANGE.has(tier);
}
