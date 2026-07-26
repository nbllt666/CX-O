/**
 * @file index.ts — 模块0_迁移编排层 入口导出
 *
 * 职责：
 *   统一导出 shadcn 四波迁移编排工具链的全部公开 API，供模块6/7/8 通过函数 import 消费。
 *
 * 导出清单（对齐 AGENTS.md §1.2 输出 API 清单）：
 *   核心编排函数：
 *     - migrateWave（migrate-wave.ts）：触发指定波次迁移，原子性提交
 *     - fallbackStrategy（migrate-wave.ts）：单波失败回退到旧组件
 *     - validateMigration（validate-migration.ts）：共存期 lint + 共享 token 校验
 *     - getMigrationStatus（migration-status.ts）：迁移看板状态查询
 *     - markDeprecated（legacy-lifecycle.ts）：第12周标记 @deprecated
 *     - moveToLegacy（legacy-lifecycle.ts）：第14周移到 _legacy/
 *     - deleteLegacy（legacy-lifecycle.ts）：第16周 GN-004 确认零引用后删除
 *
 *   配置管理：
 *     - loadMigrationConfig / getMigrationConfig / setMigrationConfig
 *     - DEFAULT_MIGRATION_CONFIG
 *
 *   依赖注入（测试与生产环境扩展点）：
 *     - setGitTagOperator / getGitTagOperator
 *     - setShaderMVPChecker / getShaderMVPChecker
 *     - setPageMigrationScanner / getPageMigrationScanner
 *     - setLegacyFileSystemOperator / getLegacyFileSystemOperator
 *
 *   看板状态管理（供模块8 页面应用层注册与更新）：
 *     - registerPage / markComponentMigrated / markComponentBlocked / markComponentPending
 *     - getMigrationBoardInfo / clearMigrationStatus
 *
 *   异常类（4 个 MIG 异常 + 基类 + 守卫）：
 *     - MigrationViolationError（基类）
 *     - MigrationBlockedError（FE-MIG-001）
 *     - RollbackFailureError（FE-MIG-002）
 *     - LintRuleConflictError（FE-MIG-003）
 *     - LegacyDeletionError（FE-MIG-004）
 *     - MIG_ERROR_CODES / isMigrationError / getErrorCode
 *
 *   类型定义（对齐 I5 .pyi + C5 配置契约 + E1 错误码契约）：
 *     - WaveKey / MigrationStatusValue / FallbackStrategy / GlassTier
 *     - MigrationConfig / MigrationReport / MigrationViolation / MigrationStatus
 *     - DeprecatedConfig / LegacyConfig / LegacyDeletionConfig
 *     - MigrationConfigSchema 及其子结构
 *     - MigErrorCode / ErrorCodeDefinition / ErrorSeverity
 *     - GitTagOperator / ShaderMVPReadinessChecker 等接口
 *
 * 消费方（对齐 AGENTS.md §3.7）：
 *   - 模块6（基础组件层）：四波迁移被 migrateWave 编排
 *   - 模块7（业务组件重组）：业务组件迁移被 migrateWave 编排
 *   - 模块8（页面应用）：通过 getMigrationStatus 查询下游可消费的组件版本，
 *     通过 registerPage / markComponentMigrated 更新看板状态
 *
 * 约束：
 *   - public/ 零触碰：本模块不修改 public/ 目录下任何内容
 *   - 跨模块导入：仅导出自身实现，不 import 模块1-9 的内部实现
 *   - 配置驱动：四波编排顺序由 C5 配置契约驱动，禁止硬编码波次顺序
 */

// =============================================================================
// 核心编排函数（对齐 AGENTS.md §1.2 输出 API 清单）
// =============================================================================

export { migrateWave, fallbackStrategy } from './migrate-wave';
export { validateMigration } from './validate-migration';
export { getMigrationStatus } from './migration-status';
export { markDeprecated, moveToLegacy, deleteLegacy } from './legacy-lifecycle';

// =============================================================================
// 配置管理（对齐 C5 §autoFill，配置驱动禁止硬编码）
// =============================================================================

export {
  loadMigrationConfig,
  getMigrationConfig,
  setMigrationConfig,
  DEFAULT_MIGRATION_CONFIG,
} from './migrate-wave';

// =============================================================================
// 依赖注入（测试 mock 与生产环境扩展点）
// =============================================================================

export {
  getGitTagOperator,
  setGitTagOperator,
  getShaderMVPChecker,
  setShaderMVPChecker,
  getWaveComponentRecords,
} from './migrate-wave';

export {
  getPageMigrationScanner,
  setPageMigrationScanner,
} from './validate-migration';
export type {
  PageMigrationScanner,
  PageImportScanResult,
  ComponentGlassCheckResult,
  LintConflictCheckResult,
} from './validate-migration';

export {
  getLegacyFileSystemOperator,
  setLegacyFileSystemOperator,
} from './legacy-lifecycle';
export type { LegacyFileSystemOperator } from './legacy-lifecycle';

// =============================================================================
// 看板状态管理（供模块8 页面应用层注册与更新）
// =============================================================================

export {
  registerPage,
  markComponentMigrated,
  markComponentBlocked,
  markComponentPending,
  clearMigrationStatus,
  getMigrationBoardInfo,
} from './migration-status';

// =============================================================================
// 异常类与错误码（对齐 E1 MIG 段 4 错误码 + I5 §异常类）
// =============================================================================

export {
  MigrationViolationError,
  MigrationBlockedError,
  RollbackFailureError,
  LintRuleConflictError,
  LegacyDeletionError,
  MIG_ERROR_CODES,
  isMigrationError,
  getErrorCode,
} from './errors';

// =============================================================================
// 类型定义（对齐 I5 .pyi + C5 配置契约 + E1 错误码契约）
// =============================================================================

export type {
  // 字面量联合类型（对齐 I5 §WaveKey / MigrationStatusValue / FallbackStrategy）
  WaveKey,
  MigrationStatusValue,
  FallbackStrategy,
  GlassTier,
  Variants,
  // 迁移违规类型（对齐 I5 §MigrationViolation / MigrationReport）
  MigrationViolationType,
  MigrationViolation,
  MigrationReport,
  // 迁移配置类型（对齐 I5 §MigrationConfig）
  MigrationConfig,
  // 迁移看板状态类型（对齐 I5 §MigrationStatus）
  MigrationStatus,
  // 废弃时间表配置类型（对齐 I5 §DeprecatedConfig / LegacyConfig / LegacyDeletionConfig）
  DeprecatedConfig,
  LegacyConfig,
  LegacyDeletionConfig,
  // C5 配置契约类型（对齐 C5 §properties）
  WaveScheduleConfig,
  ShaderMVPDependency,
  BatchRollbackConfig,
  CoexistenceLintConfig,
  DeprecationTimelineConfig,
  MigrationBoardConfig,
  AutoFillConfig,
  ExceptionContractEntry,
  ExceptionContractConfig,
  MigrationConfigSchema,
  // E1 错误码契约类型（对齐 E1 §errorCodes MIG 段）
  MigErrorCode,
  ErrorSeverity,
  ErrorCodeDefinition,
  // 依赖注入接口
  GitTagOperator,
  ShaderMVPReadinessChecker,
  // 迁移进度状态（内部状态类型）
  ComponentMigrationRecord,
  PageMigrationRecord,
} from './types';
