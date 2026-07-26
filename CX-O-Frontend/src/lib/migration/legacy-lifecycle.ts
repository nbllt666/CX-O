/**
 * @file legacy-lifecycle.ts — 模块0_迁移编排层 废弃时间表管理
 *
 * 职责：
 *   废弃时间表三阶段生命周期管理（对齐 merged.md §4.6 + C5 §deprecationTimeline）：
 *     - markDeprecated（第12周末标记 @deprecated）
 *     - moveToLegacy（第14周末移到 components/_legacy/）
 *     - deleteLegacy（第16周末 GN-004 确认零引用后删除）
 *
 * 废弃时间表（对齐 C5 §deprecationTimeline + merged.md §4.6）：
 *   | 里程碑   | 动作                 | 判据                            |
 *   |---------|----------------------|---------------------------------|
 *   | 第12周末 | mark-deprecated      | 全部页面已切换到 ui-v2/         |
 *   | 第14周末 | move-to-legacy       | 无任何页面引用 components/      |
 *   | 第16周末 | delete-legacy        | GN-004 审查确认零引用           |
 *
 * 异常契约（对齐 AGENTS.md §3.8 + E1 MIG 段）：
 *   - markDeprecated: componentName 不存在 / 仍有页面引用该旧组件
 *     → MigrationBlockedError（FE-MIG-001）
 *   - moveToLegacy: referenceCount > 0 / 路径移动失败
 *     → MigrationBlockedError（FE-MIG-001）
 *   - deleteLegacy: 零引用校验失败 / GN-004 未确认零引用 / GN-004 审查记录缺失
 *     → LegacyDeletionError（FE-MIG-004）
 *
 * 跨模块异常归属（对齐 E1 §crossModuleDisambiguation 规则5）：
 *   - 单组件层零引用校验失败 → FE-COM-004（COM 模块，模块0 不越界）
 *   - _legacy/ 目录整体删除校验失败 → FE-MIG-004（MIG 模块，本模块抛出）
 *
 * 配置驱动（对齐 C5 §deprecationTimeline）：
 *   废弃时间表动作由 C5 §deprecationTimeline.week12Action/week14Action/week16Action 驱动。
 */

import type {
  DeprecatedConfig,
  LegacyConfig,
  LegacyDeletionConfig,
} from './types';
import {
  MigrationBlockedError,
  LegacyDeletionError,
} from './errors';
import { getMigrationConfig } from './migrate-wave';

// =============================================================================
// 废弃生命周期文件操作接口（抽象文件系统操作，支持测试注入）
// =============================================================================

/**
 * 废弃生命周期文件操作接口（抽象文件系统操作）。
 *
 * 模块0 不直接访问文件系统，通过此接口抽象文件操作。
 * 默认实现提供占位行为（返回预期路径，不实际操作文件系统）。
 * 生产环境通过 setLegacyFileSystemOperator 注入真实实现（Node.js fs 模块）。
 * 测试时可注入 mock 实现以验证生命周期逻辑。
 */
export interface LegacyFileSystemOperator {
  /**
   * 检查旧组件是否存在（对齐 I5 §markDeprecated raises: componentName 不存在）。
   * @returns 旧组件源码路径（若存在），null 表示不存在
   */
  checkComponentExists(componentName: string): string | null;

  /**
   * 统计组件的引用计数（对齐 I5 §markDeprecated raises: 仍有页面引用该旧组件）。
   * @returns 引用该组件的页面数
   */
  countReferences(componentName: string): number;

  /**
   * 标记组件 @deprecated JSDoc 注解（对齐 merged.md §4.6 第12周末）。
   * @returns 标记后的旧组件源码路径
   */
  addDeprecatedJSDoc(componentName: string, config: DeprecatedConfig): string;

  /**
   * 移动组件到 _legacy/ 目录（对齐 merged.md §4.6 第14周末）。
   * @returns _legacy/ 目录下的新路径
   */
  moveComponentToLegacy(componentName: string, legacyPath: string): string;

  /**
   * 删除 _legacy/ 目录下的组件（对齐 merged.md §4.6 第16周末）。
   * @returns 已删除的路径（仅用于日志记录）
   */
  deleteLegacyComponent(componentName: string): string;

  /**
   * 统计 _legacy/ 目录整体引用计数（对齐 I5 §deleteLegacy raises: 仍有引用）。
   * @returns 引用 @/components/_legacy/ 的代码位置数
   */
  countLegacyReferences(): number;
}

/**
 * 默认文件操作实现（占位行为，实际操作由外部注入）。
 *
 * 默认实现：
 *   - checkComponentExists: 返回预期路径（假设组件存在）
 *   - countReferences: 返回 0（假设无引用）
 *   - addDeprecatedJSDoc: 返回预期路径
 *   - moveComponentToLegacy: 返回预期 _legacy/ 路径
 *   - deleteLegacyComponent: 返回预期删除路径
 *   - countLegacyReferences: 返回 0（假设无引用）
 *
 * 生产环境必须通过 setLegacyFileSystemOperator 注入真实实现。
 */
function createDefaultLegacyOperator(): LegacyFileSystemOperator {
  return {
    checkComponentExists(componentName: string): string | null {
      return `src/components/${componentName}.tsx`;
    },
    countReferences(_componentName: string): number {
      return 0;
    },
    addDeprecatedJSDoc(componentName: string, _config: DeprecatedConfig): string {
      return `src/components/${componentName}.tsx`;
    },
    moveComponentToLegacy(componentName: string, legacyPath: string): string {
      return legacyPath.endsWith('/')
        ? `${legacyPath}${componentName}.tsx`
        : `${legacyPath}/${componentName}.tsx`;
    },
    deleteLegacyComponent(componentName: string): string {
      return `src/components/_legacy/${componentName}.tsx`;
    },
    countLegacyReferences(): number {
      return 0;
    },
  };
}

// =============================================================================
// 模块级文件操作注入
// =============================================================================

let _legacyOperator: LegacyFileSystemOperator | null = null;

/**
 * 获取废弃生命周期文件操作器（惰性初始化默认实现）。
 */
export function getLegacyFileSystemOperator(): LegacyFileSystemOperator {
  if (_legacyOperator) {
    return _legacyOperator;
  }
  _legacyOperator = createDefaultLegacyOperator();
  return _legacyOperator;
}

/**
 * 设置废弃生命周期文件操作器（测试注入 mock 或注入 Node.js fs 真实实现）。
 */
export function setLegacyFileSystemOperator(
  operator: LegacyFileSystemOperator | null,
): void {
  _legacyOperator = operator;
}

// =============================================================================
// markDeprecated — 第12周末标记 @deprecated（严格匹配 I5 §markDeprecated 签名）
// =============================================================================

/**
 * 第12周末旧组件标记 @deprecated（严格匹配 I5 §markDeprecated 签名）。
 *
 * 对应 TS: `markDeprecated(config: DeprecatedConfig): string`
 *
 * 触发判据（merged.md §4.6 + C5 §deprecationTimeline.week12Condition）：
 *   - 第12周末: 全部页面已切换到 ui-v2/
 *   - 旧组件标记 @deprecated JSDoc 注解
 *
 * @param config 废弃标记配置（componentName / deprecatedAt / replacementPath / reason）
 * @returns string 标记后的旧组件源码路径（如 src/components/Button.tsx）
 * @throws MigrationBlockedError 当 componentName 不存在 / 仍有页面引用该旧组件时抛出（FE-MIG-001）
 */
export function markDeprecated(config: DeprecatedConfig): string {
  const { componentName, deprecatedAt, replacementPath, reason } = config;
  const fullConfig = getMigrationConfig();
  const { deprecationTimeline } = fullConfig;

  // 配置驱动：检查 week12Action 是否为 mark-deprecated（对齐 C5 §deprecationTimeline.week12Action）
  if (deprecationTimeline.week12Action !== 'mark-deprecated') {
    throw new MigrationBlockedError(
      `markDeprecated 跳过: C5 §deprecationTimeline.week12Action="${deprecationTimeline.week12Action}"，` +
        '当前配置不执行 mark-deprecated 动作。',
    );
  }

  const operator = getLegacyFileSystemOperator();

  // 校验1: componentName 存在（对齐 I5 §markDeprecated raises: componentName 不存在）
  const componentPath = operator.checkComponentExists(componentName);
  if (!componentPath) {
    throw new MigrationBlockedError(
      `markDeprecated 校验失败: 旧组件 ${componentName} 不存在（I5 §markDeprecated raises: componentName 不存在）。` +
        '对齐 E1 §FE-MIG-001（markDeprecated 路径，波次编排层阻塞）。',
    );
  }

  // 校验2: 无页面引用该旧组件（对齐 I5 §markDeprecated raises: 仍有页面引用该旧组件）
  // 判据对齐 C5 §deprecationTimeline.week12Condition: 全部页面已切换到 ui-v2/
  const refCount = operator.countReferences(componentName);
  if (refCount > 0) {
    throw new MigrationBlockedError(
      `markDeprecated 校验失败: 旧组件 ${componentName} 仍有 ${refCount} 处引用` +
        `（I5 §markDeprecated raises: 仍有页面引用该旧组件）。` +
        `对齐 C5 §deprecationTimeline.week12Condition: "${deprecationTimeline.week12Condition}"。` +
        '对齐 E1 §FE-MIG-001（markDeprecated 路径）。',
    );
  }

  // 执行标记 @deprecated JSDoc
  const markedPath = operator.addDeprecatedJSDoc(componentName, {
    componentName,
    deprecatedAt,
    replacementPath,
    reason,
  });

  return markedPath;
}

// =============================================================================
// moveToLegacy — 第14周末移到 _legacy/（严格匹配 I5 §moveToLegacy 签名）
// =============================================================================

/**
 * 第14周末旧组件移到 components/_legacy/（严格匹配 I5 §moveToLegacy 签名）。
 *
 * 对应 TS: `moveToLegacy(config: LegacyConfig): string`
 *
 * 触发判据（merged.md §4.6 + C5 §deprecationTimeline.week14Condition）：
 *   - 第14周末: 无任何页面引用 components/（referenceCount=0）
 *   - 旧组件移到 components/_legacy/ 目录
 *
 * @param config 移动配置（componentName / movedAt / legacyPath / referenceCount）
 * @returns string _legacy/ 目录下的新路径（如 src/components/_legacy/Button.tsx）
 * @throws MigrationBlockedError 当 referenceCount > 0 / 路径移动失败时抛出（FE-MIG-001）
 */
export function moveToLegacy(config: LegacyConfig): string {
  const { componentName, movedAt, legacyPath, referenceCount } = config;
  const fullConfig = getMigrationConfig();
  const { deprecationTimeline } = fullConfig;

  // 配置驱动：检查 week14Action 是否为 move-to-legacy（对齐 C5 §deprecationTimeline.week14Action）
  if (deprecationTimeline.week14Action !== 'move-to-legacy') {
    throw new MigrationBlockedError(
      `moveToLegacy 跳过: C5 §deprecationTimeline.week14Action="${deprecationTimeline.week14Action}"，` +
        '当前配置不执行 move-to-legacy 动作。',
    );
  }

  // 校验1: referenceCount=0（对齐 I5 §moveToLegacy raises: referenceCount > 0）
  // 判据对齐 C5 §deprecationTimeline.week14Condition: 无任何页面引用 components/
  if (referenceCount > 0) {
    throw new MigrationBlockedError(
      `moveToLegacy 校验失败: 组件 ${componentName} referenceCount=${referenceCount} > 0` +
        `（I5 §moveToLegacy raises: referenceCount > 0）。` +
        `对齐 C5 §deprecationTimeline.week14Condition: "${deprecationTimeline.week14Condition}"。` +
        '对齐 E1 §FE-MIG-001（moveToLegacy 路径）。',
    );
  }

  // 二次校验：通过 operator 实时统计引用计数（防止 config.referenceCount 与实际不符）
  const operator = getLegacyFileSystemOperator();
  const actualRefCount = operator.countReferences(componentName);
  if (actualRefCount > 0) {
    throw new MigrationBlockedError(
      `moveToLegacy 二次校验失败: 组件 ${componentName} 实际引用计数=${actualRefCount} > 0` +
        '（config.referenceCount=0 但实际仍有引用，可能存在并发引用）。' +
        '对齐 E1 §FE-MIG-001（moveToLegacy 路径，路径移动前引用校验失败）。',
    );
  }

  // 执行移动到 _legacy/
  let newPath: string;
  try {
    newPath = operator.moveComponentToLegacy(componentName, legacyPath);
  } catch (e) {
    throw new MigrationBlockedError(
      `moveToLegacy 路径移动失败: 组件 ${componentName} 移动到 ${legacyPath} 异常。` +
        '对齐 I5 §moveToLegacy raises: 路径移动失败。' +
        `对齐 E1 §FE-MIG-001（moveToLegacy 路径）。原始错误: ${e instanceof Error ? e.message : String(e)}`,
    );
  }

  // 记录 movedAt（用于审计，实际写入由 operator 实现）
  void movedAt; // movedAt 由 operator 在 moveComponentToLegacy 中使用（默认实现未使用，此处避免 unused 警告）

  return newPath;
}

// =============================================================================
// deleteLegacy — 第16周末删除 _legacy/（严格匹配 I5 §deleteLegacy 签名）
// =============================================================================

/**
 * 第16周末删除 components/_legacy/，GN-004 确认零引用后删除（严格匹配 I5 §deleteLegacy 签名）。
 *
 * 对应 TS: `deleteLegacy(config: LegacyDeletionConfig): string`
 *
 * 触发判据（merged.md §4.6 + C5 §deprecationTimeline.week16Condition）：
 *   - 第16周末: GN-004 审查确认零引用（zeroReferenceVerified=true）
 *   - 删除 components/_legacy/ 目录
 *
 * 零引用校验（对齐 I5 §deleteLegacy + E1 §FE-MIG-004）：
 *   - GN-004 独立审查确认无任何代码引用 @/components/_legacy/
 *   - zeroReferenceVerified 必须为 true
 *   - gn004ReviewId 必须存在（GN-004 审查记录 ID）
 *
 * @param config 删除配置（componentName / deletedAt / zeroReferenceVerified / gn004ReviewId）
 * @returns string 已删除的路径（如 src/components/_legacy/Button.tsx，仅用于日志记录）
 * @throws LegacyDeletionError 当零引用校验失败 / GN-004 未确认零引用 / GN-004 审查记录缺失时抛出（FE-MIG-004）
 */
export function deleteLegacy(config: LegacyDeletionConfig): string {
  const { componentName, deletedAt, zeroReferenceVerified, gn004ReviewId } = config;
  const fullConfig = getMigrationConfig();
  const { deprecationTimeline } = fullConfig;

  // 配置驱动：检查 week16Action 是否为 delete-legacy（对齐 C5 §deprecationTimeline.week16Action）
  if (deprecationTimeline.week16Action !== 'delete-legacy') {
    throw new LegacyDeletionError(
      `deleteLegacy 跳过: C5 §deprecationTimeline.week16Action="${deprecationTimeline.week16Action}"，` +
        '当前配置不执行 delete-legacy 动作。',
    );
  }

  // 校验1: GN-004 已确认零引用（对齐 I5 §deleteLegacy raises: GN-004 未确认零引用）
  // 判据对齐 C5 §deprecationTimeline.week16Condition: GN-004 审查确认零引用
  if (!zeroReferenceVerified) {
    throw new LegacyDeletionError(
      `deleteLegacy 校验失败: 组件 ${componentName} zeroReferenceVerified=false` +
        `（I5 §deleteLegacy raises: GN-004 未确认零引用）。` +
        `对齐 C5 §deprecationTimeline.week16Condition: "${deprecationTimeline.week16Condition}"。` +
        '对齐 E1 §FE-MIG-004 trigger: 第16周 week16Action=delete-legacy 执行前 GN-004 零引用审查未通过。',
    );
  }

  // 校验2: GN-004 审查记录 ID 存在（对齐 I5 §deleteLegacy raises: GN-004 审查记录缺失）
  if (!gn004ReviewId) {
    throw new LegacyDeletionError(
      `deleteLegacy 校验失败: 组件 ${componentName} gn004ReviewId 缺失` +
        '（I5 §deleteLegacy raises: GN-004 审查记录缺失 gn004ReviewId=null）。' +
        '对齐 E1 §FE-MIG-004 trigger: 第16周 week16Action=delete-legacy 执行前 GN-004 零引用审查未通过。',
    );
  }

  // 校验3: _legacy/ 目录零引用校验（对齐 I5 §deleteLegacy raises: 零引用校验失败）
  // 注意：本校验是 _legacy/ 目录整体删除校验（FE-MIG-004），与单组件零引用校验（FE-COM-004）区分
  const operator = getLegacyFileSystemOperator();
  const legacyRefCount = operator.countLegacyReferences();
  if (legacyRefCount > 0) {
    throw new LegacyDeletionError(
      `deleteLegacy 零引用校验失败: components/_legacy/ 仍有 ${legacyRefCount} 处引用` +
        `（I5 §deleteLegacy raises: 零引用校验失败）。` +
        '对齐 E1 §FE-MIG-004 trigger: 第16周 week16Action=delete-legacy 执行前 GN-004 零引用审查检测到 components/_legacy/ 仍被引用。' +
        '注意：与 FE-COM-004 区分——本错误码是 _legacy/ 目录整体删除校验失败，FE-COM-004 是单组件层零引用校验失败。',
    );
  }

  // 执行删除
  let deletedPath: string;
  try {
    deletedPath = operator.deleteLegacyComponent(componentName);
  } catch (e) {
    throw new LegacyDeletionError(
      `deleteLegacy 删除失败: 组件 ${componentName} 删除异常。` +
        `原始错误: ${e instanceof Error ? e.message : String(e)}`,
    );
  }

  // 记录 deletedAt（用于审计日志）
  void deletedAt;

  return deletedPath;
}
