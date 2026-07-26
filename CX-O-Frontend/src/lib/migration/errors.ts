/**
 * @file errors.ts — 模块0_迁移编排层 异常类定义
 *
 * 职责：
 *   定义 MIG 段 4 个异常类，严格对齐：
 *     - 错误码契约 E1 `frontend_error_codes.schema.json` MIG 段（FE-MIG-001/002/003/004）
 *     - 接口契约 I5 `frontend_components_uiv2.pyi` §异常类（MigrationViolationError / LegacyDeletionError）
 *     - 配置契约 C5 `frontend_migration_config.schema.json` §exceptionContract（4 异常的 throwCondition/callerHandling/retryStrategy/degradeBehavior）
 *
 * 异常归属（对齐 E1 §moduleRegistry MIG 段 ownedExceptions）：
 *   - FE-MIG-001 迁移阻塞（波次编排层）    → MigrationBlockedError
 *   - FE-MIG-002 回退失败（git tag 层）     → RollbackFailureError
 *   - FE-MIG-003 lint 规则冲突              → LintRuleConflictError
 *   - FE-MIG-004 废弃删除失败（零引用校验层）→ LegacyDeletionError
 *
 * 跨模块异常归属规则（对齐 E1 §exceptionContract crossModuleDisambiguationRules）：
 *   - 单组件执行层违规 → FE-COM-001（COM 模块，模块6 抛出，模块0 不越界）
 *   - 单页面混用检测   → FE-COM-003（COM 模块，eslint-plugin-import 规则抛出，模块0 不越界）
 *   - 单组件零引用校验 → FE-COM-004（COM 模块，模块0 不越界）
 *   模块0 检测到上述场景时，记录到 MigrationReport.violations 中返回（passed=false），
 *   不抛出 COM 模块异常，避免越界（E1 §throwConditionRules 规则1）。
 *
 * 继承关系：
 *   - MigrationViolationError（基类，对应 I5 §MigrationViolationError，携带 errorCode 字段）
 *     ├── MigrationBlockedError     (FE-MIG-001)
 *     ├── RollbackFailureError      (FE-MIG-002)
 *     ├── LintRuleConflictError     (FE-MIG-003)
 *     └── LegacyDeletionError       (FE-MIG-004)
 *
 *   migrateWave / markDeprecated / moveToLegacy 抛出 MigrationViolationError 或其子类
 *   （匹配 I5 签名 raises MigrationViolationError）。
 *   deleteLegacy 抛出 LegacyDeletionError（匹配 I5 签名 raises LegacyDeletionError）。
 */

import type {
  ErrorSeverity,
  ErrorCodeDefinition,
  MigErrorCode,
  MigrationViolation,
} from './types';

// =============================================================================
// E1 MIG 段错误码定义（对齐 E1 §errorCodes MIG 段 4 个错误码的完整元数据）
// =============================================================================

/**
 * E1 MIG 段错误码注册表（对齐 E1 §errorCodes MIG 段 + C5 §exceptionContract）。
 *
 * 此常量是模块0 抛出异常时的错误码元数据唯一来源，禁止在其他位置硬编码错误码描述。
 */
export const MIG_ERROR_CODES: Record<MigErrorCode, ErrorCodeDefinition> = {
  'FE-MIG-001': {
    code: 'FE-MIG-001',
    name: '迁移阻塞（波次编排层）',
    severity: 'error',
    description:
      '某波迁移出现 P0/P1 阻塞缺陷且无法立即修复，或着色器 MVP 未就绪且 tier3FallbackEnabled=false。' +
      '注意：与 FE-COM-001 区分——本错误码是波次编排层阻塞，FE-COM-001 是单组件执行层违规。',
    trigger:
      '某波迁移出现 P0/P1 阻塞缺陷，或 shaderMVPRequiredBeforeWave1=true 但着色器 MVP 未就绪且 tier3FallbackEnabled=false。' +
      '仅由迁移编排器抛出。',
    recoveryStrategy:
      '触发 [V] 节点（AskUserQuestion + GN-004 审查）决定是否回退；' +
      '若 tier3FallbackEnabled=true 则该波组件先以 Tier 3 落地。',
    relatedContract: [
      'C5 frontend_migration_config.schema.json',
      'I5 frontend_components_uiv2.pyi',
    ],
  },
  'FE-MIG-002': {
    code: 'FE-MIG-002',
    name: '回退失败（git tag 层）',
    severity: 'error',
    description:
      'batchRollbackEnabled=true 但回退到 pre-wave-N tag 失败（git tag 缺失 / 旧组件已被部分修改 / 合并冲突）。',
    trigger:
      'git checkout pre-wave-N 失败，或 git tag 不存在，或合并冲突无法自动解决。仅由迁移编排器抛出。',
    recoveryStrategy: '不重试，停止迁移流水线，通知人工介入解决 git 冲突。',
    relatedContract: ['C5 frontend_migration_config.schema.json'],
  },
  'FE-MIG-003': {
    code: 'FE-MIG-003',
    name: 'lint 规则冲突',
    severity: 'warning',
    description:
      'eslint-plugin-import 与现有 lint 配置冲突，或 samePageMixProhibition 规则误报。' +
      '注意：与 FE-COM-003 区分——本错误码是 lint 规则编排层冲突，FE-COM-003 是单页面混用检测（组件层）。',
    trigger:
      'eslintImportPlugin=true 但与现有 .eslintrc 冲突，或 samePageMixProhibition 规则误报合法引用。' +
      '仅由迁移编排器抛出。',
    recoveryStrategy:
      'CI 拦截 PR 合并，标记为 lint-violation；开发者修复 lint 违规或调整规则配置后重新提交。',
    relatedContract: ['C5 frontend_migration_config.schema.json'],
  },
  'FE-MIG-004': {
    code: 'FE-MIG-004',
    name: '废弃删除失败（零引用校验层）',
    severity: 'error',
    description:
      '第16周 week16Action=delete-legacy 执行前 GN-004 零引用审查未通过。' +
      '注意：与 FE-COM-004 区分——本错误码是 _legacy/ 目录整体删除校验失败，FE-COM-004 是单组件层零引用校验失败。',
    trigger:
      '第16周 week16Action=delete-legacy 执行前 GN-004 零引用审查检测到 components/_legacy/ 仍被引用。' +
      '仅由迁移编排器抛出。',
    recoveryStrategy:
      '阻断删除操作，标记为 deprecation-check-failed；开发者清理残留引用后重新触发 GN-004 零引用审查；' +
      '不删除 _legacy/ 目录，延后到下一个里程碑。',
    relatedContract: ['C5 frontend_migration_config.schema.json'],
  },
};

// =============================================================================
// 异常基类（对应 I5 §MigrationViolationError）
// =============================================================================

/**
 * 迁移违规异常基类（对应 I5 §MigrationViolationError）。
 *
 * 抛出条件（对齐 I5 §MigrationViolationError 抛出条件）：
 *   - migrateWave: waveKey 不在 1-4 范围
 *   - migrateWave: componentNames 为空
 *   - migrateWave: fallbackStrategy 无效
 *   - migrateWave: git tag 创建失败
 *   - validateMigration: 发现阻断式违规（如关键组件缺失 data-glass 属性）
 *   - markDeprecated: componentName 不存在 / 仍有页面引用该旧组件
 *   - moveToLegacy: referenceCount > 0 / 路径移动失败
 *
 * 错误码路由（对齐 E1 §callerHandlingRules 规则1）：
 *   调用方捕获后必须读取 errorCode 字段，按 errorCode 查找 recoveryStrategy 执行恢复，
 *   不得按异常类型（Error class）拦截。
 *
 * 4 个 MIG 子类异常均继承此基类，携带具体 errorCode（FE-MIG-001/002/003/004）。
 */
export class MigrationViolationError extends Error {
  /** 错误码（FE-MIG-001/002/003/004 之一，子类赋值） */
  public readonly errorCode: MigErrorCode;
  /** 严重级别（对齐 E1 §errorCodes.severity） */
  public readonly severity: ErrorSeverity;
  /** 违规详情（用于 note 记录与 GN-004 审查回溯） */
  public readonly violations: MigrationViolation[];

  constructor(
    message: string,
    errorCode: MigErrorCode,
    severity: ErrorSeverity,
    violations: MigrationViolation[] = [],
  ) {
    super(message);
    this.name = 'MigrationViolationError';
    this.errorCode = errorCode;
    this.severity = severity;
    this.violations = violations;
    // 维持原型链（TS 编译到 ES5 后 extends Error 的已知问题修复）
    Object.setPrototypeOf(this, MigrationViolationError.prototype);
  }

  /**
   * 获取错误码元数据（对齐 E1 §errorCodes 完整字段）。
   */
  getErrorDefinition(): ErrorCodeDefinition {
    return MIG_ERROR_CODES[this.errorCode];
  }
}

// =============================================================================
// 4 个 MIG 异常子类（对齐 E1 MIG 段 + C5 §exceptionContract）
// =============================================================================

/**
 * 迁移阻塞异常（FE-MIG-001，波次编排层）。
 *
 * 抛出条件（对齐 C5 §exceptionContract.migrationBlocked.throwCondition + E1 §FE-MIG-001.trigger）：
 *   - migrateWave: waveKey 不在 1-4 范围
 *   - migrateWave: componentNames 为空
 *   - migrateWave: fallbackStrategy 无效
 *   - migrateWave: git tag 创建失败
 *   - migrateWave: shaderMVPRequiredBeforeWave1=true 但着色器 MVP 未就绪且 tier3FallbackEnabled=false
 *   - validateMigration: 发现阻断式违规（关键组件缺失 data-glass 属性）
 *
 * 调用方处理（对齐 C5 §exceptionContract.migrationBlocked.callerHandling）：
 *   调用方捕获后触发 [V] 节点（AskUserQuestion + GN-004 审查）决定是否回退。
 *
 * 降级行为（对齐 C5 §exceptionContract.migrationBlocked.degradeBehavior）：
 *   若 tier3FallbackEnabled=true 则该波组件先以 Tier 3 落地；否则阻塞该波迁移。
 */
export class MigrationBlockedError extends MigrationViolationError {
  constructor(
    message: string,
    violations: MigrationViolation[] = [],
  ) {
    super(message, 'FE-MIG-001', 'error', violations);
    this.name = 'MigrationBlockedError';
    Object.setPrototypeOf(this, MigrationBlockedError.prototype);
  }
}

/**
 * 回退失败异常（FE-MIG-002，git tag 层）。
 *
 * 抛出条件（对齐 C5 §exceptionContract.rollbackFailure.throwCondition + E1 §FE-MIG-002.trigger）：
 *   - fallbackStrategy='rollback-wave' 执行时 batchRollbackEnabled=true 但回退到 pre-wave-N tag 失败
 *   - git tag 缺失 / 旧组件已被部分修改 / 合并冲突无法解决
 *
 * 调用方处理（对齐 C5 §exceptionContract.rollbackFailure.callerHandling）：
 *   调用方必须捕获并停止迁移流水线，通知人工介入解决 git 冲突。
 *
 * 降级行为（对齐 C5 §exceptionContract.rollbackFailure.degradeBehavior）：
 *   暂停整个迁移流水线，直到人工介入。
 */
export class RollbackFailureError extends MigrationViolationError {
  constructor(
    message: string,
    violations: MigrationViolation[] = [],
  ) {
    super(message, 'FE-MIG-002', 'error', violations);
    this.name = 'RollbackFailureError';
    Object.setPrototypeOf(this, RollbackFailureError.prototype);
  }
}

/**
 * lint 规则冲突异常（FE-MIG-003，编排层）。
 *
 * 抛出条件（对齐 C5 §exceptionContract.lintRuleConflict.throwCondition + E1 §FE-MIG-003.trigger）：
 *   - eslintImportPlugin=true 但与现有 .eslintrc 冲突
 *   - samePageMixProhibition 规则误报合法引用
 *
 * 注意：与 FE-COM-003 区分（对齐 E1 §crossModuleDisambiguation 规则4）：
 *   - FE-MIG-003 是 lint 规则编排层冲突（本异常，模块0 抛出）
 *   - FE-COM-003 是单页面混用检测（组件层，eslint-plugin-import 自定义规则抛出，模块0 不越界）
 *
 * 调用方处理（对齐 C5 §exceptionContract.lintRuleConflict.callerHandling）：
 *   CI 拦截 PR 合并，标记为 lint-violation，要求开发者修复。
 *
 * 降级行为（对齐 C5 §exceptionContract.lintRuleConflict.degradeBehavior）：
 *   不降级，阻断合并直到 lint 通过。
 */
export class LintRuleConflictError extends MigrationViolationError {
  constructor(
    message: string,
    violations: MigrationViolation[] = [],
  ) {
    super(message, 'FE-MIG-003', 'warning', violations);
    this.name = 'LintRuleConflictError';
    Object.setPrototypeOf(this, LintRuleConflictError.prototype);
  }
}

/**
 * _legacy/ 删除异常（FE-MIG-004，零引用校验层）。
 *
 * 对应 I5 §LegacyDeletionError + E1 §FE-MIG-004 + C5 §exceptionContract.deprecationDeleteZeroReferenceCheckFailed。
 *
 * 抛出条件（对齐 I5 §LegacyDeletionError + E1 §FE-MIG-004.trigger + C5 throwCondition）：
 *   - deleteLegacy: 零引用校验失败（仍有页面引用 @/components/_legacy/ 组件）
 *   - deleteLegacy: GN-004 未确认零引用（zeroReferenceVerified=false）
 *   - deleteLegacy: GN-004 审查记录缺失（gn004ReviewId=null/undefined）
 *
 * 注意：与 FE-COM-004 区分（对齐 E1 §crossModuleDisambiguation 规则5）：
 *   - FE-MIG-004 是 _legacy/ 目录整体删除校验失败（本异常，模块0 抛出）
 *   - FE-COM-004 是单组件级零引用扫描失败（组件层，模块6 抛出，模块0 不越界）
 *
 * 调用方处理（对齐 C5 §exceptionContract.deprecationDeleteZeroReferenceCheckFailed.callerHandling）：
 *   阻断删除操作，标记为 deprecation-check-failed，要求开发者清理残留引用。
 *
 * 降级行为（对齐 C5 §exceptionContract.deprecationDeleteZeroReferenceCheckFailed.degradeBehavior）：
 *   不删除 _legacy/ 目录，延后到下一个里程碑再审查。
 */
export class LegacyDeletionError extends MigrationViolationError {
  constructor(
    message: string,
    violations: MigrationViolation[] = [],
  ) {
    super(message, 'FE-MIG-004', 'error', violations);
    this.name = 'LegacyDeletionError';
    Object.setPrototypeOf(this, LegacyDeletionError.prototype);
  }
}

// =============================================================================
// 异常类型守卫（对齐 E1 §callerHandlingRules 规则1：按 errorCode 路由）
// =============================================================================

/**
 * 判断异常是否为 MIG 模块异常（对齐 E1 §callerHandlingRules 规则1）。
 *
 * 调用方应使用此守卫配合 errorCode 字段路由处理，而非按异常类型 catch。
 */
export function isMigrationError(error: unknown): error is MigrationViolationError {
  return error instanceof MigrationViolationError;
}

/**
 * 按 errorCode 路由异常处理（对齐 E1 §callerHandlingRules 规则1）。
 *
 * 调用方捕获异常后应使用此函数获取 errorCode，再按 errorCode 查找 recoveryStrategy。
 */
export function getErrorCode(error: unknown): MigErrorCode | null {
  if (isMigrationError(error)) {
    return error.errorCode;
  }
  return null;
}
