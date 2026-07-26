/**
 * @file types.ts — 模块0_迁移编排层 类型定义
 *
 * 职责：
 *   定义 shadcn 四波迁移编排工具链的全部公开类型，严格对齐：
 *     - 接口契约 I5 `frontend_components_uiv2.pyi`（WaveKey / MigrationStatusValue /
 *       FallbackStrategy / MigrationConfig / MigrationReport / MigrationStatus /
 *       DeprecatedConfig / LegacyConfig / LegacyDeletionConfig / MigrationViolation）
 *     - 配置契约 C5 `frontend_migration_config.schema.json`（shadcnMigrationWaves /
 *       shaderMVPDependency / batchRollback / coexistenceLint / deprecationTimeline /
 *       migrationBoard / autoFill / exceptionContract）
 *     - 错误码契约 E1 `frontend_error_codes.schema.json`（MIG 段 4 错误码 errorCode 字段类型）
 *
 * 约束：
 *   - 不硬编码配置参数：四波编排顺序、组件清单、废弃时间表等均由 C5 配置契约类型承载，
 *     运行时从配置对象读取（见 migrate-wave.ts 的 loadMigrationConfig）。
 *   - 跨模块导入：本文件仅定义类型，不 import 任何模块1-9 的内部实现。
 *   - TypeScript 严格模式：所有类型显式标注，禁用 any（framer-motion Variants 等三方类型除外）。
 *
 * 来源对齐：
 *   - I5 §WaveKey / MigrationStatusValue / FallbackStrategy 字面量联合类型
 *   - I5 §TypedDict（MigrationConfig / MigrationViolation / MigrationReport / MigrationStatus /
 *     DeprecatedConfig / LegacyConfig / LegacyDeletionConfig）
 *   - C5 §properties（shadcnMigrationWaves / shaderMVPDependency / batchRollback /
 *     coexistenceLint / deprecationTimeline / migrationBoard / autoFill / exceptionContract）
 *   - E1 §errorCodes（MIG 段 FE-MIG-001/002/003/004）
 */

// =============================================================================
// 字面量联合类型（对齐 I5 §WaveKey / MigrationStatusValue / FallbackStrategy）
// =============================================================================

/**
 * 迁移波次枚举（对齐 I5 §WaveKey + C5 §shadcnMigrationWaves 字符串 key）。
 *
 * - 'wave1': 基础（Button/Input/Card/Dialog/Tooltip，第1-3周）
 * - 'wave2': 表单（Form/Select/Checkbox/RadioGroup，第4-6周）
 * - 'wave3': 数据展示（Table/Tabs/Badge/Avatar，第7-9周）
 * - 'wave4': 业务封装（ChatPanel/AudioTrack 等，第10-12周）
 *
 * 波次 key 是类型约束（WaveKey），波次内部的 components/startWeek/endWeek 等
 * 由 C5 配置契约驱动，不在代码中硬编码。
 */
export type WaveKey = 'wave1' | 'wave2' | 'wave3' | 'wave4';

/**
 * 迁移看板状态枚举（对齐 I5 §MigrationStatusValue + C5 §migrationBoard.migrationStatuses）。
 *
 * 三值状态，不得二值化（rules-5 §二 强制三值标记）：
 * - 'migrated': 已迁移
 * - 'pending':  待迁移
 * - 'blocked':  阻塞
 *
 * C5 §migrationBoard.migrationStatuses 的中文枚举 ['已迁移','待迁移','阻塞'] 与本英文枚举一一对应。
 */
export type MigrationStatusValue = 'migrated' | 'pending' | 'blocked';

/**
 * 回退策略枚举（对齐 I5 §FallbackStrategy + merged.md §4.4）。
 *
 * - 'rollback-wave': 回退该波到旧组件（git checkout pre-wave-N）
 * - 'tier3-css':     降级到 Tier 3 CSS backdrop-filter（merged.md §4.3 OBS-D）
 * - 'skip':          跳过该组件，后续补迁
 */
export type FallbackStrategy = 'rollback-wave' | 'tier3-css' | 'skip';

/**
 * Liquid Glass 四级 tier（引用 I1 frontend_glass.pyi 的 GlassTier IntEnum）。
 *
 * 枚举值 1-4 对应 CSS data-glass-tier 属性值：
 * - 1: tier1-webgl2
 * - 2: tier2-webgl1
 * - 3: tier3-css
 * - 4: tier4-solid
 *
 * 类型与 I1 GlassTier(IntEnum) 对齐——D2 glass_tier_config.schema.json tierId: integer 1-4 为唯一真相源。
 */
export type GlassTier = 1 | 2 | 3 | 4;

/**
 * Framer Motion variants 类型别名（对齐 I5 §Variants）。
 * 由 I3 createMotionVariants 生成，本模块仅校验其存在性，不深入其内部结构。
 */
export type Variants = Record<string, unknown>;

// =============================================================================
// 迁移违规类型（对齐 I5 §MigrationViolation / MigrationReport）
// =============================================================================

/**
 * 迁移违规类型枚举（对齐 I5 §MigrationViolation.type）。
 *
 * - 'mix-old-new':       同页面混用新旧组件
 * - 'lint-violation':    lint 规则违规
 * - 'token-mismatch':    共享 token 校验失败
 * - 'missing-glass-attr': 关键组件缺失 data-glass 属性
 * - 'missing-motion-variants': 关键组件缺失 motion variants
 */
export type MigrationViolationType =
  | 'mix-old-new'
  | 'lint-violation'
  | 'token-mismatch'
  | 'missing-glass-attr'
  | 'missing-motion-variants';

/**
 * 迁移违规项（对齐 I5 §MigrationViolation TypedDict）。
 *
 * TS: `{ type: string; page: string; component: string; detail: string }`
 */
export interface MigrationViolation {
  /** 违规类型（mix-old-new / lint-violation / token-mismatch / missing-glass-attr / missing-motion-variants） */
  type: MigrationViolationType;
  /** 违规发生的页面路径 */
  page: string;
  /** 违规涉及的组件名 */
  component: string;
  /** 违规详情 */
  detail: string;
}

/**
 * 迁移完整性校验报告（对齐 I5 §MigrationReport TypedDict）。
 *
 * migrateWave 与 validateMigration 均返回此结构。
 */
export interface MigrationReport {
  /** 是否通过校验（true=全部通过，false=存在违规） */
  passed: boolean;
  /** 违规项清单（passed=false 时非空） */
  violations: MigrationViolation[];
  /** 报告摘要（人类可读） */
  summary: string;
  /** 对应的波次 */
  waveKey: WaveKey;
}

// =============================================================================
// 迁移配置类型（对齐 I5 §MigrationConfig）
// =============================================================================

/**
 * 迁移波次编排配置（对齐 I5 §MigrationConfig TypedDict）。
 *
 * 对应 merged.md §4.3 迁移顺序 + §4.4 批次回退。
 * migrateWave(config) 的入参。
 */
export interface MigrationConfig {
  /** 波次 key（wave1-wave4） */
  waveKey: WaveKey;
  /** 该波要迁移的组件名列表（若为空则从 C5 配置契约的 shadcnMigrationWaves[waveKey].components 加载） */
  componentNames: string[];
  /** 回退策略（rollback-wave / tier3-css / skip） */
  fallbackStrategy: FallbackStrategy;
  /** 迁移前 git tag（pre-wave-N，merged.md §4.4）。若未提供则由 migrateWave 自动生成。 */
  gitTag?: string;
}

// =============================================================================
// 迁移看板状态类型（对齐 I5 §MigrationStatus）
// =============================================================================

/**
 * 迁移看板状态（对齐 I5 §MigrationStatus TypedDict）。
 *
 * 对应 merged.md §4.5: 每页面标注"已迁移/待迁移/阻塞"，每周更新。
 */
export interface MigrationStatus {
  /** 页面路径 */
  page: string;
  /** 状态（migrated / pending / blocked），三值标记 */
  status: MigrationStatusValue;
  /** 已迁移的组件清单 */
  migratedComponents: string[];
  /** 待迁移的组件清单 */
  pendingComponents: string[];
  /** 阻塞原因（status='blocked' 时必填） */
  blockedReason?: string;
}

// =============================================================================
// 废弃时间表配置类型（对齐 I5 §DeprecatedConfig / LegacyConfig / LegacyDeletionConfig）
// =============================================================================

/**
 * 废弃标记配置（第12周末，对齐 I5 §DeprecatedConfig + C5 §deprecationTimeline.week12Action）。
 */
export interface DeprecatedConfig {
  /** 组件名 */
  componentName: string;
  /** 废弃日期（ISO 8601） */
  deprecatedAt: string;
  /** 替代组件路径（@/components/ui-v2/...） */
  replacementPath: string;
  /** 废弃原因 */
  reason: string;
}

/**
 * 移到 _legacy/ 配置（第14周末，对齐 I5 §LegacyConfig + C5 §deprecationTimeline.week14Action）。
 */
export interface LegacyConfig {
  /** 组件名 */
  componentName: string;
  /** 移动日期（ISO 8601） */
  movedAt: string;
  /** _legacy/ 目录路径 */
  legacyPath: string;
  /** 当前引用计数（须为 0 才可移动） */
  referenceCount: number;
}

/**
 * 删除 _legacy/ 配置（第16周末，对齐 I5 §LegacyDeletionConfig + C5 §deprecationTimeline.week16Action）。
 */
export interface LegacyDeletionConfig {
  /** 组件名 */
  componentName: string;
  /** 删除日期（ISO 8601） */
  deletedAt: string;
  /** GN-004 是否已确认零引用（必须为 true 才可删除） */
  zeroReferenceVerified: boolean;
  /** GN-004 审查记录 ID（必须存在） */
  gn004ReviewId?: string;
}

// =============================================================================
// C5 配置契约类型（对齐 C5 §properties，用于配置驱动加载）
// =============================================================================

/**
 * 单波迁移配置（对齐 C5 §shadcnMigrationWaves.waveN）。
 */
export interface WaveScheduleConfig {
  /** 波次名称（基础/表单/数据展示/业务封装） */
  name: string;
  /** 本波迁移组件清单 */
  components: string[];
  /** 起始周（1-16） */
  startWeek: number;
  /** 结束周（1-16） */
  endWeek: number;
  /** 页面覆盖范围 */
  pageCoverage: string;
}

/**
 * 着色器 MVP 依赖配置（对齐 C5 §shaderMVPDependency，OBS-D 处置）。
 */
export interface ShaderMVPDependency {
  /** 着色器 MVP 版本须在第1波迁移启动前完成 */
  shaderMVPRequiredBeforeWave1: boolean;
  /** 着色器 MVP 版本包含的层（不含色散层） */
  shaderMVPComponents: string[];
  /** 着色器完整版本与第2-4波并行开发 */
  shaderFullVersionParallelWithWave2To4: boolean;
  /** 着色器完整版本包含的层（在 MVP 基础上新增） */
  shaderFullVersionComponents: string[];
  /** 着色器 MVP 延期时第1波迁移先以 Tier 3 落地 */
  tier3FallbackEnabled: boolean;
}

/**
 * 批次回退规则配置（对齐 C5 §batchRollback，merged.md §4.4）。
 */
export interface BatchRollbackConfig {
  /** 每波迁移独立可回退 */
  batchRollbackEnabled: boolean;
  /** 回退触发条件（P0/P1 阻塞缺陷） */
  rollbackTrigger: string;
  /** Git tag 策略（pre-wave-N，匹配 ^pre-wave-\d+$） */
  gitTagStrategy: string;
  /** 回退决策触发节点（[V] 节点 AskUserQuestion + GN-004 审查） */
  rollbackDecisionTrigger: string;
}

/**
 * 并存期 lint 规则配置（对齐 C5 §coexistenceLint，merged.md §4.5）。
 */
export interface CoexistenceLintConfig {
  /** 启用 eslint-plugin-import + 自定义规则 */
  eslintImportPlugin: boolean;
  /** 新代码引用 components/（旧目录）时告警 */
  newCodeLegacyImportWarning: boolean;
  /** 禁止同一页面混用新旧组件 */
  samePageMixProhibition: boolean;
  /** 新旧组件共享同一套 token */
  sharedTokenLayer: boolean;
}

/**
 * 废弃时间表配置（对齐 C5 §deprecationTimeline，merged.md §4.6）。
 */
export interface DeprecationTimelineConfig {
  /** 第12周末动作（mark-deprecated / no-action） */
  week12Action: 'mark-deprecated' | 'no-action';
  /** 第12周末动作触发条件 */
  week12Condition: string;
  /** 第14周末动作（move-to-legacy / no-action） */
  week14Action: 'move-to-legacy' | 'no-action';
  /** 第14周末动作触发条件 */
  week14Condition: string;
  /** 第16周末动作（delete-legacy / no-action） */
  week16Action: 'delete-legacy' | 'no-action';
  /** 第16周末动作触发条件 */
  week16Condition: string;
}

/**
 * 迁移看板配置（对齐 C5 §migrationBoard，merged.md §4.5）。
 */
export interface MigrationBoardConfig {
  /** 启用迁移看板 */
  migrationBoardEnabled: boolean;
  /** 迁移看板更新频率（daily/weekly/biweekly） */
  migrationBoardUpdateFrequency: 'daily' | 'weekly' | 'biweekly';
  /** 迁移状态枚举（中文，3 项唯一：已迁移/待迁移/阻塞） */
  migrationStatuses: string[];
}

/**
 * auto_fill 规则配置（对齐 C5 §autoFill，rules-3 §三强制）。
 */
export interface AutoFillConfig {
  /** 是否启用 auto_fill */
  enabled: boolean;
  /** 补齐策略（default-value / throw-on-missing） */
  strategy: 'default-value' | 'throw-on-missing';
  /** auto_fill 作用域 */
  scope: string[];
  /** 严格模式（auto_fill 后再校验一次 schema） */
  strictMode: boolean;
}

/**
 * 单个异常契约配置（对齐 C5 §exceptionContract.* 单项）。
 */
export interface ExceptionContractEntry {
  /** 错误码（FE-MIG-001/002/003/004） */
  code: string;
  /** 抛出条件 */
  throwCondition: string;
  /** 调用方处理约定 */
  callerHandling: string;
  /** 重试策略 */
  retryStrategy: string;
  /** 降级行为 */
  degradeBehavior: string;
}

/**
 * 异常契约配置（对齐 C5 §exceptionContract）。
 */
export interface ExceptionContractConfig {
  /** 迁移阻塞异常 FE-MIG-001 */
  migrationBlocked: ExceptionContractEntry;
  /** 回退失败异常 FE-MIG-002 */
  rollbackFailure: ExceptionContractEntry;
  /** lint 规则冲突异常 FE-MIG-003 */
  lintRuleConflict: ExceptionContractEntry;
  /** 废弃删除零引用校验失败异常 FE-MIG-004 */
  deprecationDeleteZeroReferenceCheckFailed: ExceptionContractEntry;
}

/**
 * C5 迁移配置契约完整结构（对齐 C5 §properties 顶层）。
 *
 * 所有迁移编排参数必须经此类型加载，禁止业务代码硬编码（C5 §autoFill.description）。
 * loadMigrationConfig() 函数实现 autoFill 补齐逻辑（见 migrate-wave.ts）。
 */
export interface MigrationConfigSchema {
  /** shadcn 迁移四波时间表 */
  shadcnMigrationWaves: Record<WaveKey, WaveScheduleConfig>;
  /** 着色器 MVP 依赖（OBS-D 处置） */
  shaderMVPDependency: ShaderMVPDependency;
  /** 批次回退规则 */
  batchRollback: BatchRollbackConfig;
  /** 并存期 lint 规则 */
  coexistenceLint: CoexistenceLintConfig;
  /** 废弃时间表（第12/14/16 周） */
  deprecationTimeline: DeprecationTimelineConfig;
  /** 迁移看板 */
  migrationBoard: MigrationBoardConfig;
  /** auto_fill 规则 */
  autoFill: AutoFillConfig;
  /** 异常契约（4 个 MIG 异常） */
  exceptionContract: ExceptionContractConfig;
}

// =============================================================================
// E1 错误码契约类型（对齐 E1 §errorCodes MIG 段）
// =============================================================================

/**
 * MIG 段错误码字面量联合（对齐 E1 §errorCodes MIG 段 4 个错误码）。
 */
export type MigErrorCode = 'FE-MIG-001' | 'FE-MIG-002' | 'FE-MIG-003' | 'FE-MIG-004';

/**
 * 错误严重级别枚举（对齐 E1 §severityEnum）。
 */
export type ErrorSeverity = 'fatal' | 'error' | 'warning' | 'info';

/**
 * 单个错误码定义（对齐 E1 §errorCodes 数组项结构）。
 */
export interface ErrorCodeDefinition {
  /** 错误码（匹配 ^FE-[A-Z]{3}-\d{3}$） */
  code: MigErrorCode;
  /** 错误名（中文） */
  name: string;
  /** 严重级别 */
  severity: ErrorSeverity;
  /** 错误描述 */
  description: string;
  /** 触发条件 */
  trigger: string;
  /** 恢复策略 */
  recoveryStrategy: string;
  /** 关联契约文件清单 */
  relatedContract: string[];
}

// =============================================================================
// git tag 操作接口（用于 migrateWave 创建 pre-wave-N tag，支持测试注入）
// =============================================================================

/**
 * Git tag 操作接口（抽象 git 操作，支持测试注入 mock）。
 *
 * 模块0 是迁移编排层，migrateWave 在构建脚本/CI 中调用，需要执行 git 命令。
 * 默认实现通过动态 import('node:child_process') 执行 git（仅 Node.js 环境）。
 * 测试时可注入 mock 实现以避免真实 git 操作。
 */
export interface GitTagOperator {
  /** 创建 git tag（如 pre-wave-1） */
  createTag(tagName: string, message?: string): void;
  /** 检查 git tag 是否存在 */
  tagExists(tagName: string): boolean;
  /** 回退到指定 git tag（git checkout <tag>） */
  checkoutTag(tagName: string): void;
}

// =============================================================================
// 着色器 MVP 就绪状态检查接口（用于 wave1 启动前的 OBS-D 处置）
// =============================================================================

/**
 * 着色器 MVP 就绪状态检查接口（抽象着色器依赖检查）。
 *
 * 模块0 不直接依赖模块4（玻璃层）的内部实现，仅通过此接口感知着色器 MVP 就绪状态。
 * 默认实现返回 true（假设着色器 MVP 已就绪），生产环境可注入真实检查器。
 */
export interface ShaderMVPReadinessChecker {
  /** 着色器 MVP 是否就绪（折射层 + 基础高光层） */
  isShaderMVPReady(): boolean;
}

// =============================================================================
// 迁移进度状态（用于 getMigrationStatus 内部状态存储）
// =============================================================================

/**
 * 单组件迁移状态记录（内部状态，不对外暴露）。
 */
export interface ComponentMigrationRecord {
  /** 组件名 */
  componentName: string;
  /** 所属波次 */
  waveKey: WaveKey;
  /** 迁移状态 */
  status: MigrationStatusValue;
  /** 迁移时间（ISO 8601，status='migrated' 时有值） */
  migratedAt?: string;
  /** 阻塞原因（status='blocked' 时有值） */
  blockedReason?: string;
}

/**
 * 单页面迁移状态记录（内部状态，用于 getMigrationStatus 聚合）。
 */
export interface PageMigrationRecord {
  /** 页面路径 */
  page: string;
  /** 页面下各组件的迁移状态 */
  components: ComponentMigrationRecord[];
}
