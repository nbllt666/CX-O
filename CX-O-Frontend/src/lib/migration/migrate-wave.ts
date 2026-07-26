/**
 * @file migrate-wave.ts — 模块0_迁移编排层 四波迁移编排核心
 *
 * 职责：
 *   1. C5 配置契约加载（loadMigrationConfig 实现 autoFill 补齐，对齐 C5 §autoFill）
 *   2. shadcn 四波迁移编排（migrateWave，严格匹配 I5 §migrateWave 签名）
 *   3. 批次回退策略执行（fallbackStrategy，对齐 merged.md §4.4）
 *   4. 每波迁移前打 git tag pre-wave-N（回退锚点，对齐 merged.md §4.4 + C5 §batchRollback.gitTagStrategy）
 *   5. 着色器 MVP 依赖管理（wave1 启动前检查，对齐 merged.md §4.3 OBS-D + C5 §shaderMVPDependency）
 *
 * 配置驱动（对齐 AGENTS.md §3.6）：
 *   四波编排顺序由 C5 配置契约的 shadcnMigrationWaves 字段驱动，禁止硬编码波次顺序。
 *   每波的组件清单、起止周、页面覆盖范围均从配置对象读取。
 *
 * 回退锚点（对齐 AGENTS.md §3.5 + merged.md §4.4）：
 *   每波迁移前打 git tag pre-wave-N，单波失败回退该波到旧组件，不影响已迁移波次。
 *
 * 着色器 MVP 依赖（对齐 merged.md §4.3 OBS-D + C5 §shaderMVPDependency）：
 *   - 着色器 MVP 版本须在 wave1 迁移启动前完成（折射层 + 基础高光层）
 *   - 若着色器 MVP 延期且 tier3FallbackEnabled=true：wave1 组件先以 Tier 3 落地
 *   - 若着色器 MVP 延期且 tier3FallbackEnabled=false：抛出 MigrationBlockedError（FE-MIG-001）
 *
 * 异常契约（对齐 AGENTS.md §3.8 + E1 MIG 段）：
 *   - migrateWave: waveKey 无效 / componentNames 为空 / fallbackStrategy 无效 / git tag 创建失败
 *     / 着色器 MVP 未就绪且 tier3FallbackEnabled=false → MigrationBlockedError（FE-MIG-001）
 *   - fallbackStrategy: rollback-wave 执行回退失败 → RollbackFailureError（FE-MIG-002）
 *
 * 跨模块导入约束（对齐 AGENTS.md §3.3）：
 *   仅 import 自身模块内部实现（types/errors），不 import 模块1-9 的内部实现。
 */

import type {
  ComponentMigrationRecord,
  FallbackStrategy,
  GitTagOperator,
  MigrationConfig,
  MigrationConfigSchema,
  MigrationReport,
  MigrationViolation,
  ShaderMVPReadinessChecker,
  WaveKey,
  WaveScheduleConfig,
} from './types';
import {
  MigrationBlockedError,
  RollbackFailureError,
} from './errors';

// =============================================================================
// C5 配置契约默认值（对齐 C5 §properties 各字段 default 值，作为 autoFill 补齐源）
// =============================================================================

/**
 * C5 配置契约默认值（对齐 C5 §properties 各字段 default）。
 *
 * 此常量是 autoFill 补齐的唯一数据源，禁止在其他位置硬编码迁移参数。
 * loadMigrationConfig(partial) 会将 partial 与此默认值深度合并。
 */
export const DEFAULT_MIGRATION_CONFIG: MigrationConfigSchema = {
  shadcnMigrationWaves: {
    wave1: {
      name: '基础',
      components: ['Button', 'Input', 'Card', 'Dialog', 'Tooltip'],
      startWeek: 1,
      endWeek: 3,
      pageCoverage: '全部页面通用',
    },
    wave2: {
      name: '表单',
      components: ['Form', 'Select', 'Checkbox', 'RadioGroup'],
      startWeek: 4,
      endWeek: 6,
      pageCoverage: 'Settings/Agents/Acp',
    },
    wave3: {
      name: '数据展示',
      components: ['Table', 'Tabs', 'Badge', 'Avatar'],
      startWeek: 7,
      endWeek: 9,
      pageCoverage: 'Dashboard/Chat/Live',
    },
    wave4: {
      name: '业务封装',
      components: ['业务组件层'],
      startWeek: 10,
      endWeek: 12,
      pageCoverage: 'AudioWorkstation/Pet',
    },
  },
  shaderMVPDependency: {
    shaderMVPRequiredBeforeWave1: true,
    shaderMVPComponents: ['折射层', '基础高光层'],
    shaderFullVersionParallelWithWave2To4: true,
    shaderFullVersionComponents: ['色散层', 'Fresnel 高光层'],
    tier3FallbackEnabled: true,
  },
  batchRollback: {
    batchRollbackEnabled: true,
    rollbackTrigger: 'P0/P1 阻塞缺陷',
    gitTagStrategy: 'pre-wave-N',
    rollbackDecisionTrigger: '[V] 节点（AskUserQuestion + GN-004 审查）',
  },
  coexistenceLint: {
    eslintImportPlugin: true,
    newCodeLegacyImportWarning: true,
    samePageMixProhibition: true,
    sharedTokenLayer: true,
  },
  deprecationTimeline: {
    week12Action: 'mark-deprecated',
    week12Condition: '全部页面已切换到 ui-v2/',
    week14Action: 'move-to-legacy',
    week14Condition: '无任何页面引用 components/',
    week16Action: 'delete-legacy',
    week16Condition: 'GN-004 审查确认零引用',
  },
  migrationBoard: {
    migrationBoardEnabled: true,
    migrationBoardUpdateFrequency: 'weekly',
    migrationStatuses: ['已迁移', '待迁移', '阻塞'],
  },
  autoFill: {
    enabled: true,
    strategy: 'default-value',
    scope: [
      'shadcnMigrationWaves',
      'shaderMVPDependency',
      'batchRollback',
      'coexistenceLint',
      'deprecationTimeline',
      'migrationBoard',
    ],
    strictMode: true,
  },
  exceptionContract: {
    migrationBlocked: {
      code: 'FE-MIG-001',
      throwCondition:
        '某波迁移出现 P0/P1 阻塞缺陷且无法立即修复，或 shaderMVPRequiredBeforeWave1=true 但着色器 MVP 未就绪且 tier3FallbackEnabled=false。',
      callerHandling: '调用方捕获后触发 [V] 节点（AskUserQuestion + GN-004 审查）决定是否回退。',
      retryStrategy: '不自动重试，等待人类裁决后由 batchRollback 回退或修复后继续。',
      degradeBehavior: '若 tier3FallbackEnabled=true 则该波组件先以 Tier 3 落地；否则阻塞该波迁移。',
    },
    rollbackFailure: {
      code: 'FE-MIG-002',
      throwCondition:
        'batchRollbackEnabled=true 但回退到 pre-wave-N tag 失败（如 git tag 缺失 / 旧组件已被部分修改 / 合并冲突无法解决）。',
      callerHandling: '调用方必须捕获并停止迁移流水线，通知人工介入解决 git 冲突。',
      retryStrategy: '不重试，人工解决冲突后手动恢复迁移。',
      degradeBehavior: '暂停整个迁移流水线，直到人工介入。',
    },
    lintRuleConflict: {
      code: 'FE-MIG-003',
      throwCondition:
        'samePageMixProhibition=true 但检测到同一页面同时引用 ui-v2/ 与 components/ 组件，或 eslintImportPlugin 与现有 lint 配置冲突。',
      callerHandling: 'CI 拦截 PR 合并，标记为 lint-violation，要求开发者修复。',
      retryStrategy: '开发者修复 lint 违规后重新提交 PR 触发 CI。',
      degradeBehavior: '不降级，阻断合并直到 lint 通过。',
    },
    deprecationDeleteZeroReferenceCheckFailed: {
      code: 'FE-MIG-004',
      throwCondition:
        '第16周 week16Action=delete-legacy 执行前 GN-004 零引用审查未通过（仍存在 components/_legacy/ 的引用）。',
      callerHandling: '阻断删除操作，标记为 deprecation-check-failed，要求开发者清理残留引用。',
      retryStrategy: '开发者清理残留引用后重新触发 GN-004 零引用审查。',
      degradeBehavior: '不删除 _legacy/ 目录，延后到下一个里程碑再审查。',
    },
  },
};

// =============================================================================
// autoFill 深度合并实现（对齐 C5 §autoFill.strategy=default-value）
// =============================================================================

/**
 * 深度合并两个对象（autoFill default-value 策略实现）。
 *
 * - 对象类型递归合并
 * - 数组类型直接覆盖（不合并数组元素）
 * - undefined 字段不覆盖基础值
 */
function deepMerge<T>(base: T, override: Partial<T> | undefined | null): T {
  if (override === undefined || override === null) {
    return base;
  }
  if (typeof base !== 'object' || base === null) {
    return override as T;
  }
  if (Array.isArray(base)) {
    return (override as unknown as T) ?? base;
  }
  const result: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  const overrideRecord = override as Record<string, unknown>;
  for (const key of Object.keys(overrideRecord)) {
    const baseVal = (base as Record<string, unknown>)[key];
    const overrideVal = overrideRecord[key];
    if (
      typeof baseVal === 'object' &&
      baseVal !== null &&
      !Array.isArray(baseVal) &&
      typeof overrideVal === 'object' &&
      overrideVal !== null &&
      !Array.isArray(overrideVal)
    ) {
      result[key] = deepMerge(
        baseVal as Record<string, unknown>,
        overrideVal as Record<string, unknown>,
      );
    } else if (overrideVal !== undefined) {
      result[key] = overrideVal;
    }
  }
  return result as T;
}

/**
 * 加载迁移配置（对齐 C5 §autoFill，实现 default-value 补齐策略）。
 *
 * - 若 partial 为空，返回完整默认配置
 * - 若 partial 提供部分字段，深度合并到默认配置（缺失字段补齐为 default 值）
 * - 对齐 C5 §autoFill.strategy=default-value + C5 §autoFill.strictMode=true
 *
 * @param partial 部分配置（从外部注入，如 fetch/import 的 JSON）
 * @returns 完整配置（autoFill 补齐后）
 */
export function loadMigrationConfig(
  partial?: Partial<MigrationConfigSchema>,
): MigrationConfigSchema {
  if (!partial) {
    return DEFAULT_MIGRATION_CONFIG;
  }
  return deepMerge(DEFAULT_MIGRATION_CONFIG, partial);
}

// =============================================================================
// 模块级配置与依赖注入（支持测试 mock 与外部覆盖）
// =============================================================================

let _migrationConfig: MigrationConfigSchema = DEFAULT_MIGRATION_CONFIG;
let _gitTagOperator: GitTagOperator | null = null;
let _shaderMVPChecker: ShaderMVPReadinessChecker | null = null;

/**
 * 获取当前迁移配置（模块级单例）。
 */
export function getMigrationConfig(): MigrationConfigSchema {
  return _migrationConfig;
}

/**
 * 设置迁移配置（供外部注入覆盖默认配置）。
 *
 * 调用此函数后，migrateWave / fallbackStrategy 等函数将使用新配置。
 * 对齐 C5 §autoFill：调用方可先 loadMigrationConfig(partial) 补齐，再 setMigrationConfig。
 */
export function setMigrationConfig(config: MigrationConfigSchema): void {
  _migrationConfig = config;
}

/**
 * 获取 git tag 操作器（惰性初始化默认实现）。
 *
 * 默认实现通过 Node.js child_process 执行 git 命令（仅在 Node.js 环境可用）。
 * 测试时可通过 setGitTagOperator 注入 mock。
 */
export function getGitTagOperator(): GitTagOperator {
  if (_gitTagOperator) {
    return _gitTagOperator;
  }
  _gitTagOperator = createDefaultGitTagOperator();
  return _gitTagOperator;
}

/**
 * 设置 git tag 操作器（测试注入 mock 或自定义实现）。
 */
export function setGitTagOperator(operator: GitTagOperator | null): void {
  _gitTagOperator = operator;
}

/**
 * 获取着色器 MVP 就绪检查器（惰性初始化默认实现）。
 *
 * 默认实现返回 true（假设着色器 MVP 已就绪）。
 * 生产环境可通过 setShaderMVPChecker 注入真实检查器（如检查模块4 GlassRenderer 状态）。
 */
export function getShaderMVPChecker(): ShaderMVPReadinessChecker {
  if (_shaderMVPChecker) {
    return _shaderMVPChecker;
  }
  _shaderMVPChecker = {
    isShaderMVPReady: () => true,
  };
  return _shaderMVPChecker;
}

/**
 * 设置着色器 MVP 就绪检查器（测试注入 mock 或注入模块4 真实检查器）。
 */
export function setShaderMVPChecker(checker: ShaderMVPReadinessChecker | null): void {
  _shaderMVPChecker = checker;
}

// =============================================================================
// 默认 GitTagOperator 实现（Node.js child_process，浏览器环境明确报错）
// =============================================================================

/**
 * Node.js child_process 模块类型（避免引入 @types/node）。
 */
interface NodeChildProcess {
  execSync: (command: string, options?: { stdio?: string }) => Buffer;
}

/**
 * 惰性加载 Node.js child_process 模块。
 *
 * 通过 globalThis.require 动态访问，避免 Vite 静态分析报错。
 * 浏览器环境返回 null。
 */
let _nodeChildProcess: NodeChildProcess | null | undefined;
function loadNodeChildProcess(): NodeChildProcess | null {
  if (_nodeChildProcess !== undefined) {
    return _nodeChildProcess;
  }
  try {
    const g = globalThis as unknown as { require?: (module: string) => unknown };
    if (typeof g.require === 'function') {
      const cp = g.require('child_process');
      if (cp && typeof (cp as NodeChildProcess).execSync === 'function') {
        _nodeChildProcess = cp as NodeChildProcess;
        return _nodeChildProcess;
      }
    }
  } catch {
    // 浏览器环境或 require 失败
  }
  _nodeChildProcess = null;
  return _nodeChildProcess;
}

/**
 * 创建默认 GitTagOperator（Node.js child_process 实现）。
 *
 * 浏览器环境下 createTag/checkoutTag 会抛出明确错误，提示通过 setGitTagOperator 注入。
 */
function createDefaultGitTagOperator(): GitTagOperator {
  return {
    createTag(tagName: string, message?: string): void {
      const cp = loadNodeChildProcess();
      if (!cp) {
        throw new Error(
          `git tag 操作仅在 Node.js 环境可用（尝试创建 tag: ${tagName}）。` +
            '浏览器环境请通过 setGitTagOperator 注入自定义实现。',
        );
      }
      const cmd = message
        ? `git tag -a ${tagName} -m ${JSON.stringify(message)}`
        : `git tag ${tagName}`;
      cp.execSync(cmd, { stdio: 'pipe' });
    },
    tagExists(tagName: string): boolean {
      const cp = loadNodeChildProcess();
      if (!cp) {
        return false;
      }
      try {
        cp.execSync(`git rev-parse --verify refs/tags/${tagName}`, { stdio: 'pipe' });
        return true;
      } catch {
        return false;
      }
    },
    checkoutTag(tagName: string): void {
      const cp = loadNodeChildProcess();
      if (!cp) {
        throw new Error(
          `git checkout 操作仅在 Node.js 环境可用（尝试 checkout tag: ${tagName}）。` +
            '浏览器环境请通过 setGitTagOperator 注入自定义实现。',
        );
      }
      cp.execSync(`git checkout ${tagName}`, { stdio: 'pipe' });
    },
  };
}

// =============================================================================
// 波次号映射（WaveKey → 数字，用于生成 pre-wave-N tag 名）
// =============================================================================

/**
 * WaveKey 到波次号的映射（类型约束，非硬编码编排顺序）。
 *
 * 编排顺序由 C5 §shadcnMigrationWaves 的 key 顺序驱动（Object.keys 读取），
 * 此映射仅用于生成 git tag 名 pre-wave-N 的数字部分。
 */
const WAVE_NUMBER: Record<WaveKey, number> = {
  wave1: 1,
  wave2: 2,
  wave3: 3,
  wave4: 4,
};

/**
 * 合法的 WaveKey 集合（用于校验）。
 */
const VALID_WAVE_KEYS: ReadonlySet<string> = new Set(['wave1', 'wave2', 'wave3', 'wave4']);

/**
 * 合法的 FallbackStrategy 集合（用于校验）。
 */
const VALID_FALLBACK_STRATEGIES: ReadonlySet<string> = new Set([
  'rollback-wave',
  'tier3-css',
  'skip',
]);

// =============================================================================
// 模块级迁移记录（内部状态，供 migration-status.ts 聚合读取）
// =============================================================================

/**
 * 波次级组件迁移记录（按波次存储）。
 *
 * migrateWave 成功迁移后追加记录；fallbackStrategy 回退后更新状态。
 * migration-status.ts 的 getMigrationStatus 通过 getWaveComponentRecords() 读取。
 */
const _waveComponentRecords: Map<WaveKey, ComponentMigrationRecord[]> = new Map();

/**
 * 获取波次级组件迁移记录（内部 API，供 migration-status.ts 读取）。
 */
export function getWaveComponentRecords(): Map<WaveKey, ComponentMigrationRecord[]> {
  return _waveComponentRecords;
}

/**
 * 记录组件迁移状态（内部函数）。
 */
function recordComponentMigration(record: ComponentMigrationRecord): void {
  const list = _waveComponentRecords.get(record.waveKey) ?? [];
  const idx = list.findIndex((r) => r.componentName === record.componentName);
  if (idx >= 0) {
    list[idx] = record;
  } else {
    list.push(record);
  }
  _waveComponentRecords.set(record.waveKey, list);
}

// =============================================================================
// git tag 创建逻辑（对齐 merged.md §4.4 + C5 §batchRollback.gitTagStrategy）
// =============================================================================

/**
 * 创建 pre-wave-N git tag（回退锚点，对齐 merged.md §4.4）。
 *
 * 每波迁移前打 git tag pre-wave-N，保留完整旧组件快照。
 * 单波失败时可通过 fallbackStrategy('rollback-wave', waveKey) 回退到该 tag。
 *
 * @param waveKey 波次 key
 * @param customTag 可选自定义 tag 名（若未提供则生成 pre-wave-{N}）
 * @returns 实际创建的 tag 名
 * @throws MigrationBlockedError 当 git tag 创建失败时抛出（FE-MIG-001，对齐 I5 §migrateWave raises）
 */
function createPreWaveTag(waveKey: WaveKey, customTag?: string): string {
  const waveNumber = WAVE_NUMBER[waveKey];
  const tagName = customTag ?? `pre-wave-${waveNumber}`;
  const operator = getGitTagOperator();
  try {
    operator.createTag(
      tagName,
      `迁移回退锚点: ${waveKey} (wave ${waveNumber}) — merged.md §4.4`,
    );
    return tagName;
  } catch (e) {
    throw new MigrationBlockedError(
      `git tag 创建失败: ${tagName}（waveKey=${waveKey}）。` +
        `回退锚点未建立，迁移阻塞。原始错误: ${e instanceof Error ? e.message : String(e)}`,
    );
  }
}

// =============================================================================
// 着色器 MVP 依赖检查（对齐 merged.md §4.3 OBS-D + C5 §shaderMVPDependency）
// =============================================================================

/**
 * 着色器 MVP 依赖检查结果。
 */
interface ShaderMVPCheckResult {
  /** 是否通过（true=可继续迁移，false=需降级或阻塞） */
  passed: boolean;
  /** 是否降级到 Tier 3（passed=true 但着色器未就绪且 tier3FallbackEnabled=true 时为 true） */
  degradedToTier3: boolean;
  /** 阻塞原因（passed=false 时有值） */
  blockedReason?: string;
}

/**
 * 检查着色器 MVP 依赖（仅 wave1 启动前检查，对齐 merged.md §4.3 OBS-D）。
 *
 * - 若 shaderMVPRequiredBeforeWave1=false：直接通过
 * - 若 shaderMVPRequiredBeforeWave1=true 且着色器 MVP 已就绪：通过
 * - 若 shaderMVPRequiredBeforeWave1=true 且着色器 MVP 未就绪：
 *   - tier3FallbackEnabled=true：降级到 Tier 3，通过（记录降级）
 *   - tier3FallbackEnabled=false：阻塞（返回 passed=false）
 */
function checkShaderMVPDependency(waveKey: WaveKey): ShaderMVPCheckResult {
  const config = getMigrationConfig();
  const { shaderMVPDependency } = config;

  // 仅 wave1 启动前需要着色器 MVP（merged.md §4.3 OBS-D）
  if (waveKey !== 'wave1') {
    return { passed: true, degradedToTier3: false };
  }

  // shaderMVPRequiredBeforeWave1=false 时不检查
  if (!shaderMVPDependency.shaderMVPRequiredBeforeWave1) {
    return { passed: true, degradedToTier3: false };
  }

  const checker = getShaderMVPChecker();
  const isReady = checker.isShaderMVPReady();

  if (isReady) {
    return { passed: true, degradedToTier3: false };
  }

  // 着色器 MVP 未就绪
  if (shaderMVPDependency.tier3FallbackEnabled) {
    return {
      passed: true,
      degradedToTier3: true,
      blockedReason: undefined,
    };
  }

  return {
    passed: false,
    degradedToTier3: false,
    blockedReason:
      'shaderMVPRequiredBeforeWave1=true 但着色器 MVP 未就绪且 tier3FallbackEnabled=false（merged.md §4.3 OBS-D）',
  };
}

// =============================================================================
// migrateWave — 四波迁移编排（严格匹配 I5 §migrateWave 签名）
// =============================================================================

/**
 * 迁移四波编排接口（严格匹配 I5 §migrateWave 签名）。
 *
 * 对应 TS: `migrateWave(config: MigrationConfig): MigrationReport`
 *
 * 实现细节（merged.md §4.3 迁移顺序 + §4.4 批次回退）：
 *   - 按 waveKey 编排对应波次的组件迁移
 *   - 迁移前打 git tag pre-wave-N（merged.md §4.4），保留完整旧组件快照
 *   - 每波迁移独立可回退：若出现 P0/P1 阻塞缺陷，回退该波到旧组件
 *   - 回退决策由 [V] 节点触发（AskUserQuestion + GN-004 审查，merged.md §4.4）
 *   - fallbackStrategy 决定回退策略（rollback-wave / tier3-css / skip）
 *
 * 着色器 MVP 依赖（OBS-D 处置）：
 *   - 着色器 MVP 版本须在 wave1 迁移启动前完成（折射层 + 基础高光层）
 *   - 若着色器 MVP 延期且 tier3FallbackEnabled=true：wave1 组件先以 Tier 3 落地
 *   - 若着色器 MVP 延期且 tier3FallbackEnabled=false：抛出 MigrationBlockedError
 *
 * 配置驱动（对齐 AGENTS.md §3.6）：
 *   - 四波编排顺序由 C5 §shadcnMigrationWaves 字段驱动，禁止硬编码波次顺序
 *   - 每波组件清单从 shadcnMigrationWaves[waveKey].components 读取
 *
 * @param config 迁移配置（waveKey 1-4 / componentNames / fallbackStrategy / gitTag）
 * @returns MigrationReport 迁移报告（passed / violations / summary / waveKey）
 * @throws MigrationBlockedError 当 waveKey 无效 / componentNames 为空 / fallbackStrategy 无效
 *   / git tag 创建失败 / 着色器 MVP 未就绪且 tier3FallbackEnabled=false 时抛出（FE-MIG-001）
 */
export function migrateWave(config: MigrationConfig): MigrationReport {
  const { waveKey, componentNames, fallbackStrategy, gitTag } = config;
  const violations: MigrationViolation[] = [];
  const migratedComponents: string[] = [];

  // ---- 校验1: waveKey 有效（对齐 I5 §migrateWave raises: waveKey 不在 1-4 范围）----
  if (!VALID_WAVE_KEYS.has(waveKey)) {
    throw new MigrationBlockedError(
      `migrateWave 校验失败: waveKey "${waveKey}" 不在 wave1-wave4 范围内（I5 §migrateWave raises: waveKey 不在 1-4 范围）`,
    );
  }

  // ---- 校验2: fallbackStrategy 有效（对齐 I5 §migrateWave raises: fallbackStrategy 无效）----
  if (!VALID_FALLBACK_STRATEGIES.has(fallbackStrategy)) {
    throw new MigrationBlockedError(
      `migrateWave 校验失败: fallbackStrategy "${fallbackStrategy}" 无效，` +
        '合法值为 rollback-wave / tier3-css / skip（I5 §migrateWave raises: fallbackStrategy 无效）',
    );
  }

  // ---- 加载该波组件清单（配置驱动，对齐 C5 §shadcnMigrationWaves）----
  const waveConfig: WaveScheduleConfig = getMigrationConfig().shadcnMigrationWaves[waveKey];
  const effectiveComponentNames: string[] =
    componentNames.length > 0 ? componentNames : [...waveConfig.components];

  // ---- 校验3: componentNames 非空（对齐 I5 §migrateWave raises: componentNames 为空）----
  if (effectiveComponentNames.length === 0) {
    throw new MigrationBlockedError(
      `migrateWave 校验失败: componentNames 为空（waveKey=${waveKey}，` +
        'I5 §migrateWave raises: componentNames 为空）',
    );
  }

  // ---- 着色器 MVP 依赖检查（仅 wave1，对齐 merged.md §4.3 OBS-D）----
  const shaderCheck = checkShaderMVPDependency(waveKey);
  if (!shaderCheck.passed) {
    throw new MigrationBlockedError(
      `migrateWave 阻塞: 着色器 MVP 依赖未满足（waveKey=${waveKey}）。` +
        `原因: ${shaderCheck.blockedReason ?? '未知'}。` +
        '对齐 E1 §FE-MIG-001 trigger: shaderMVPRequiredBeforeWave1=true 但着色器 MVP 未就绪且 tier3FallbackEnabled=false。',
    );
  }

  // ---- 创建 git tag pre-wave-N（回退锚点，对齐 merged.md §4.4）----
  const createdTag = createPreWaveTag(waveKey, gitTag);

  // ---- 编排组件迁移（遍历 effectiveComponentNames，记录迁移状态）----
  const now = new Date().toISOString();
  for (const componentName of effectiveComponentNames) {
    // 实际组件迁移由模块6 通过 npx shadcn-ui add + injectGlassStyle 完成
    // 模块0 仅负责编排：打 tag、记录状态、返回 report
    const record: ComponentMigrationRecord = {
      componentName,
      waveKey,
      status: 'migrated',
      migratedAt: now,
    };
    recordComponentMigration(record);
    migratedComponents.push(componentName);
  }

  // ---- 生成 MigrationReport ----
  const summaryParts: string[] = [
    `${waveKey} 迁移完成: ${migratedComponents.length} 个组件`,
    `波次名称: ${waveConfig.name}`,
    `周期: 第${waveConfig.startWeek}-${waveConfig.endWeek}周`,
    `页面覆盖: ${waveConfig.pageCoverage}`,
    `回退锚点: ${createdTag}`,
    `回退策略: ${fallbackStrategy}`,
  ];
  if (shaderCheck.degradedToTier3) {
    summaryParts.push('降级提示: 着色器 MVP 未就绪，wave1 组件先以 Tier 3 CSS backdrop-filter 落地（OBS-D）');
  }

  return {
    passed: violations.length === 0,
    violations,
    summary: summaryParts.join(' | '),
    waveKey,
  };
}

// =============================================================================
// fallbackStrategy — 批次回退策略执行（对齐 merged.md §4.4 + I5 §FallbackStrategy）
// =============================================================================

/**
 * 单波失败回退策略执行（对齐 AGENTS.md §1.2 + merged.md §4.4）。
 *
 * 对应 I5 §FallbackStrategy 三种策略：
 *   - rollback-wave: 回退该波到旧组件（git checkout pre-wave-N）
 *   - tier3-css:     降级到 Tier 3 CSS backdrop-filter（merged.md §4.3 OBS-D）
 *   - skip:          跳过该组件，后续补迁
 *
 * @param strategy 回退策略
 * @param waveKey 回退的波次
 * @param componentNames 可选，回退的组件清单（若未提供则从配置加载该波全部组件）
 * @returns MigrationReport 回退操作报告
 * @throws RollbackFailureError 当 rollback-wave 执行回退失败时抛出（FE-MIG-002）
 * @throws MigrationBlockedError 当 waveKey 无效时抛出（FE-MIG-001）
 */
export function fallbackStrategy(
  strategy: FallbackStrategy,
  waveKey: WaveKey,
  componentNames?: string[],
): MigrationReport {
  // 校验 waveKey
  if (!VALID_WAVE_KEYS.has(waveKey)) {
    throw new MigrationBlockedError(
      `fallbackStrategy 校验失败: waveKey "${waveKey}" 不在 wave1-wave4 范围内`,
    );
  }

  // 校验 strategy
  if (!VALID_FALLBACK_STRATEGIES.has(strategy)) {
    throw new MigrationBlockedError(
      `fallbackStrategy 校验失败: strategy "${strategy}" 无效，合法值为 rollback-wave / tier3-css / skip`,
    );
  }

  const config = getMigrationConfig();
  const waveConfig = config.shadcnMigrationWaves[waveKey];
  const effectiveComponentNames: string[] =
    componentNames && componentNames.length > 0
      ? componentNames
      : [...waveConfig.components];

  const violations: MigrationViolation[] = [];
  const now = new Date().toISOString();

  switch (strategy) {
    case 'rollback-wave': {
      // 回退该波到旧组件（git checkout pre-wave-N）
      // 对齐 C5 §batchRollback.batchRollbackEnabled
      if (!config.batchRollback.batchRollbackEnabled) {
        return {
          passed: false,
          violations: [],
          summary: `fallbackStrategy('rollback-wave', ${waveKey}) 跳过: batchRollbackEnabled=false`,
          waveKey,
        };
      }

      const tagName = `pre-wave-${WAVE_NUMBER[waveKey]}`;
      const operator = getGitTagOperator();

      // 检查 tag 是否存在
      if (!operator.tagExists(tagName)) {
        throw new RollbackFailureError(
          `fallbackStrategy('rollback-wave', ${waveKey}) 失败: git tag ${tagName} 不存在。` +
            '对齐 E1 §FE-MIG-002 trigger: git tag 缺失。',
        );
      }

      // 执行回退
      try {
        operator.checkoutTag(tagName);
      } catch (e) {
        throw new RollbackFailureError(
          `fallbackStrategy('rollback-wave', ${waveKey}) 失败: git checkout ${tagName} 异常。` +
            '对齐 E1 §FE-MIG-002 trigger: 旧组件已被部分修改 / 合并冲突无法解决。' +
            `原始错误: ${e instanceof Error ? e.message : String(e)}`,
        );
      }

      // 更新组件迁移记录为待迁移（回退后重新待迁移）
      for (const componentName of effectiveComponentNames) {
        recordComponentMigration({
          componentName,
          waveKey,
          status: 'pending',
        });
      }

      return {
        passed: true,
        violations,
        summary: `fallbackStrategy('rollback-wave', ${waveKey}) 完成: 回退 ${effectiveComponentNames.length} 个组件到 ${tagName}`,
        waveKey,
      };
    }

    case 'tier3-css': {
      // 降级到 Tier 3 CSS backdrop-filter（merged.md §4.3 OBS-D）
      // 不执行 git 回退，仅标记组件为已迁移（Tier 3 降级落地）
      for (const componentName of effectiveComponentNames) {
        recordComponentMigration({
          componentName,
          waveKey,
          status: 'migrated',
          migratedAt: now,
          blockedReason: `Tier 3 CSS backdrop-filter 降级落地（OBS-D）`,
        });
      }

      return {
        passed: true,
        violations,
        summary: `fallbackStrategy('tier3-css', ${waveKey}) 完成: ${effectiveComponentNames.length} 个组件降级到 Tier 3 CSS backdrop-filter（merged.md §4.3 OBS-D）`,
        waveKey,
      };
    }

    case 'skip': {
      // 跳过该组件，后续补迁
      // 标记组件为待迁移（跳过，后续补迁）
      for (const componentName of effectiveComponentNames) {
        recordComponentMigration({
          componentName,
          waveKey,
          status: 'pending',
        });
      }

      return {
        passed: true,
        violations,
        summary: `fallbackStrategy('skip', ${waveKey}) 完成: 跳过 ${effectiveComponentNames.length} 个组件，后续补迁`,
        waveKey,
      };
    }

    default: {
      // noFallthroughCasesInSwitch 兜底（理论上不会到达）
      throw new MigrationBlockedError(
        `fallbackStrategy 未知策略: ${strategy as string}（合法值: rollback-wave / tier3-css / skip）`,
      );
    }
  }
}
