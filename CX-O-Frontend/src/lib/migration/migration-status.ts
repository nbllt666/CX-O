/**
 * @file migration-status.ts — 模块0_迁移编排层 迁移看板状态查询
 *
 * 职责：
 *   迁移看板状态查询（getMigrationStatus，严格匹配 I5 §getMigrationStatus 签名）。
 *
 * 三值状态（对齐 I5 §MigrationStatusValue + C5 §migrationBoard.migrationStatuses）：
 *   - 'migrated'（已迁移）
 *   - 'pending'（待迁移）
 *   - 'blocked'（阻塞）
 *
 *   严格三值标记，不得二值化（rules-5 §二 强制三值标记）。
 *   C5 §migrationBoard.migrationStatuses 中文枚举 ['已迁移','待迁移','阻塞'] 与本英文枚举一一对应。
 *
 * 看板更新（对齐 merged.md §4.5 + C5 §migrationBoard）：
 *   - 每页面标注"已迁移/待迁移/阻塞"，每周更新（migrationBoardUpdateFrequency=weekly）
 *   - 阻塞页面需显示阻塞原因
 *
 * 状态来源：
 *   - 模块0 内部维护页面级迁移状态（pageMigrationRecords）
 *   - migrateWave 迁移成功后调用 markComponentMigrated 更新状态
 *   - validateMigration 检测到阻塞时调用 markComponentBlocked 更新状态
 *   - 模块8（页面应用层）通过 registerPage 注册页面及其组件清单
 *
 * 异常契约（对齐 I5 §getMigrationStatus）：
 *   无异常抛出——看板状态查询是只读操作。
 */

import type {
  ComponentMigrationRecord,
  MigrationStatus,
  MigrationStatusValue,
  PageMigrationRecord,
  WaveKey,
} from './types';
import { getMigrationConfig } from './migrate-wave';

// =============================================================================
// 模块级页面迁移状态存储
// =============================================================================

/**
 * 页面迁移状态存储（模块级 Map）。
 *
 * key: 页面路径
 * value: 页面迁移记录（含各组件迁移状态）
 *
 * 状态更新来源：
 *   - registerPage: 注册页面及其组件清单（初始状态为 pending）
 *   - markComponentMigrated: 标记组件已迁移（migrateWave 成功后调用）
 *   - markComponentBlocked: 标记组件阻塞（validateMigration 检测到阻塞时调用）
 *   - markComponentPending: 重置组件为待迁移（fallbackStrategy rollback-wave 后调用）
 */
const _pageMigrationRecords: Map<string, PageMigrationRecord> = new Map();

// =============================================================================
// 状态注册与更新 API（供 migrate-wave.ts / validate-migration.ts / 模块8 调用）
// =============================================================================

/**
 * 注册页面及其组件清单（对齐 merged.md §4.5 迁移看板）。
 *
 * 注册后各组件初始状态为 'pending'（待迁移）。
 * 模块8（页面应用层）在页面挂载时调用此 API 注册页面组件清单。
 *
 * @param page 页面路径
 * @param componentNames 页面使用的组件清单
 * @param waveKey 可选，组件所属波次（用于关联波次迁移记录）
 */
export function registerPage(
  page: string,
  componentNames: string[],
  waveKey?: WaveKey,
): void {
  const components: ComponentMigrationRecord[] = componentNames.map((componentName) => ({
    componentName,
    waveKey: waveKey ?? 'wave1',
    status: 'pending' as MigrationStatusValue,
  }));
  _pageMigrationRecords.set(page, { page, components });
}

/**
 * 标记组件已迁移（migrateWave 成功后调用）。
 *
 * @param page 页面路径
 * @param componentName 组件名
 * @param migratedAt 迁移时间（ISO 8601）
 */
export function markComponentMigrated(
  page: string,
  componentName: string,
  migratedAt?: string,
): void {
  const record = _pageMigrationRecords.get(page);
  if (!record) {
    return;
  }
  const idx = record.components.findIndex((c) => c.componentName === componentName);
  if (idx >= 0) {
    record.components[idx] = {
      ...record.components[idx],
      status: 'migrated',
      migratedAt: migratedAt ?? new Date().toISOString(),
      blockedReason: undefined,
    };
  }
}

/**
 * 标记组件阻塞（validateMigration 检测到阻塞时调用）。
 *
 * @param page 页面路径
 * @param componentName 组件名
 * @param blockedReason 阻塞原因
 */
export function markComponentBlocked(
  page: string,
  componentName: string,
  blockedReason: string,
): void {
  const record = _pageMigrationRecords.get(page);
  if (!record) {
    return;
  }
  const idx = record.components.findIndex((c) => c.componentName === componentName);
  if (idx >= 0) {
    record.components[idx] = {
      ...record.components[idx],
      status: 'blocked',
      blockedReason,
      migratedAt: undefined,
    };
  }
}

/**
 * 重置组件为待迁移（fallbackStrategy rollback-wave 后调用）。
 *
 * @param page 页面路径
 * @param componentName 组件名
 */
export function markComponentPending(page: string, componentName: string): void {
  const record = _pageMigrationRecords.get(page);
  if (!record) {
    return;
  }
  const idx = record.components.findIndex((c) => c.componentName === componentName);
  if (idx >= 0) {
    record.components[idx] = {
      ...record.components[idx],
      status: 'pending',
      migratedAt: undefined,
      blockedReason: undefined,
    };
  }
}

/**
 * 清空所有页面迁移状态（测试用，生产环境慎用）。
 */
export function clearMigrationStatus(): void {
  _pageMigrationRecords.clear();
}

// =============================================================================
// 三值状态聚合逻辑（对齐 rules-5 §二 三值标记，不得二值化）
// =============================================================================

/**
 * 页面级聚合状态（对齐 merged.md §4.5 每页面标注"已迁移/待迁移/阻塞"）。
 *
 * 聚合规则（严格三值，不得二值化）：
 *   - 全部组件 migrated → 'migrated'
 *   - 任一组件 blocked → 'blocked'（阻塞优先级最高，需显示阻塞原因）
 *   - 其他 → 'pending'
 */
function aggregatePageStatus(record: PageMigrationRecord): {
  status: MigrationStatusValue;
  blockedReason?: string;
} {
  if (record.components.length === 0) {
    return { status: 'pending' };
  }

  const hasBlocked = record.components.some((c) => c.status === 'blocked');
  if (hasBlocked) {
    const blockedComponents = record.components.filter((c) => c.status === 'blocked');
    const reasons = blockedComponents
      .map((c) => `${c.componentName}: ${c.blockedReason ?? '未知原因'}`)
      .join('; ');
    return {
      status: 'blocked',
      blockedReason: `阻塞组件 ${blockedComponents.length} 个 — ${reasons}`,
    };
  }

  const allMigrated = record.components.every((c) => c.status === 'migrated');
  if (allMigrated) {
    return { status: 'migrated' };
  }

  return { status: 'pending' };
}

// =============================================================================
// getMigrationStatus — 迁移看板状态查询（严格匹配 I5 §getMigrationStatus 签名）
// =============================================================================

/**
 * 返回迁移看板状态（严格匹配 I5 §getMigrationStatus 签名）。
 *
 * 对应 TS: `getMigrationStatus(): MigrationStatus[]`
 *
 * 实现细节（merged.md §4.5）：
 *   - 每页面标注"已迁移/待迁移/阻塞"（migrated/pending/blocked）
 *   - 每周更新看板状态（migrationBoardUpdateFrequency=weekly）
 *   - 阻塞页面需显示阻塞原因
 *
 * 三值状态（对齐 C5 §migrationBoard.migrationStatuses + I5 §MigrationStatusValue）：
 *   - 'migrated'（已迁移）：页面全部组件已迁移
 *   - 'pending'（待迁移）：页面存在待迁移组件，无阻塞
 *   - 'blocked'（阻塞）：页面存在阻塞组件（阻塞优先级最高）
 *
 * @returns MigrationStatus[] 所有页面的迁移状态列表
 *   每项含: page / status / migratedComponents / pendingComponents / blockedReason
 *
 * @throws 无异常抛出——看板状态查询是只读操作（对齐 I5 §getMigrationStatus raises）
 */
export function getMigrationStatus(): MigrationStatus[] {
  // 加载配置（配置驱动，对齐 C5 §migrationBoard）
  const config = getMigrationConfig();
  const { migrationBoard } = config;

  // 看板未启用时返回空数组（对齐 C5 §migrationBoard.migrationBoardEnabled）
  if (!migrationBoard.migrationBoardEnabled) {
    return [];
  }

  // 聚合每页面状态
  const statuses: MigrationStatus[] = [];
  for (const record of _pageMigrationRecords.values()) {
    const aggregated = aggregatePageStatus(record);
    statuses.push({
      page: record.page,
      status: aggregated.status,
      migratedComponents: record.components
        .filter((c) => c.status === 'migrated')
        .map((c) => c.componentName),
      pendingComponents: record.components
        .filter((c) => c.status === 'pending')
        .map((c) => c.componentName),
      blockedReason: aggregated.blockedReason,
    });
  }

  return statuses;
}

/**
 * 获取迁移看板配置信息（供 UI 展示，对齐 C5 §migrationBoard）。
 *
 * 返回看板更新频率与状态枚举（中文），供迁移看板组件展示。
 */
export function getMigrationBoardInfo(): {
  enabled: boolean;
  updateFrequency: string;
  statuses: string[];
} {
  const { migrationBoard } = getMigrationConfig();
  return {
    enabled: migrationBoard.migrationBoardEnabled,
    updateFrequency: migrationBoard.migrationBoardUpdateFrequency,
    statuses: migrationBoard.migrationStatuses,
  };
}
