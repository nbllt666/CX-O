/**
 * @file validate-migration.ts — 模块0_迁移编排层 共存期校验
 *
 * 职责：
 *   校验迁移完整性（validateMigration，严格匹配 I5 §validateMigration 签名）。
 *
 * 校验项（对齐 merged.md §4.5 并存期管理 + C5 §coexistenceLint）：
 *   1. 页面无混用新旧组件（samePageMixProhibition）
 *      - 同一页面不能同时引用 @/components/（旧）和 @/components/ui-v2/（新）
 *   2. lint 规则（eslintImportPlugin）
 *      - eslint-plugin-import + 自定义规则，新代码引用 components/ 时告警
 *   3. 共享 token（sharedTokenLayer）
 *      - 新旧组件共享同一套 token，避免割裂
 *   4. data-glass 属性
 *      - 迁移后的组件必须挂载 data-glass 属性
 *   5. motion variants
 *      - 迁移后的组件必须用 Framer Motion variants 替换 shadcn 默认 transition
 *
 * 异常契约（对齐 AGENTS.md §3.8 + E1 MIG 段）：
 *   - lint 规则编排层冲突（eslintImportPlugin 与现有 .eslintrc 冲突 / samePageMixProhibition 误报）
 *     → LintRuleConflictError（FE-MIG-003）
 *   - 阻断式违规（关键组件缺失 data-glass 属性）
 *     → MigrationBlockedError（FE-MIG-001，validateMigration 路径）
 *
 * 跨模块异常归属（对齐 E1 §crossModuleDisambiguation 规则4）：
 *   - 单页面混用检测（组件层）→ FE-COM-003（COM 模块，eslint-plugin-import 规则抛出，模块0 不越界）
 *   - lint 规则编排层冲突 → FE-MIG-003（MIG 模块，本模块抛出）
 *   模块0 检测到单页面混用时，记录到 MigrationReport.violations（type='mix-old-new'）返回，
 *   不抛出 ComponentMixError（FE-COM-003），避免越界（E1 §throwConditionRules 规则1）。
 *
 * 配置驱动（对齐 C5 §coexistenceLint）：
 *   校验行为由 C5 §coexistenceLint 配置项驱动，禁止硬编码校验开关。
 */

import type {
  MigrationReport,
  MigrationViolation,
  MigrationViolationType,
  WaveKey,
} from './types';
import {
  MigrationBlockedError,
  LintRuleConflictError,
} from './errors';
import { getMigrationConfig } from './migrate-wave';

// =============================================================================
// 页面迁移扫描器接口（抽象文件系统/AST 扫描，支持测试注入）
// =============================================================================

/**
 * 页面组件引用扫描结果。
 */
export interface PageImportScanResult {
  /** 页面路径 */
  page: string;
  /** 旧组件引用清单（@/components/*） */
  oldComponents: string[];
  /** 新组件引用清单（@/components/ui-v2/*） */
  newComponents: string[];
}

/**
 * 单组件 Glass 属性校验结果。
 */
export interface ComponentGlassCheckResult {
  /** 组件名 */
  componentName: string;
  /** 是否挂载 data-glass 属性 */
  hasDataGlass: boolean;
  /** 是否使用 Framer Motion variants 替换 shadcn 默认 transition */
  hasMotionVariants: boolean;
  /** 是否消费共享 token（未硬编码颜色） */
  usesSharedToken: boolean;
}

/**
 * lint 配置冲突检测结果。
 */
export interface LintConflictCheckResult {
  /** eslint-plugin-import 是否与现有 .eslintrc 冲突 */
  hasEslintConfigConflict: boolean;
  /** samePageMixProhibition 规则是否误报合法引用 */
  hasFalsePositive: boolean;
  /** 冲突详情 */
  detail: string;
}

/**
 * 页面迁移扫描器接口（抽象文件系统/AST 扫描）。
 *
 * 模块0 不直接访问文件系统/AST，通过此接口抽象扫描逻辑。
 * 默认实现返回空数据（无违规），实际校验由外部注入（CI 脚本/模块8）。
 * 测试时可注入 mock 实现以验证校验逻辑。
 */
export interface PageMigrationScanner {
  /** 扫描指定页面的组件引用（返回旧组件和新组件的引用列表） */
  scanPageImports(pagePath: string): PageImportScanResult;
  /** 校验组件的 Glass 属性（data-glass / motion variants / 共享 token） */
  checkComponentGlass(componentName: string): ComponentGlassCheckResult;
  /** 检测 lint 配置冲突 */
  checkLintConflict(): LintConflictCheckResult;
  /** 列出所有页面路径（pagePath 未提供时校验全部页面） */
  listAllPages(): string[];
}

/**
 * 默认扫描器实现（无违规，实际校验由外部注入）。
 *
 * 默认实现返回空数据，validateMigration 在无扫描器注入时返回 passed=true。
 * 生产环境应通过 setPageMigrationScanner 注入真实扫描器。
 */
function createDefaultScanner(): PageMigrationScanner {
  return {
    scanPageImports(pagePath: string): PageImportScanResult {
      return { page: pagePath, oldComponents: [], newComponents: [] };
    },
    checkComponentGlass(componentName: string): ComponentGlassCheckResult {
      return {
        componentName,
        hasDataGlass: true,
        hasMotionVariants: true,
        usesSharedToken: true,
      };
    },
    checkLintConflict(): LintConflictCheckResult {
      return {
        hasEslintConfigConflict: false,
        hasFalsePositive: false,
        detail: '',
      };
    },
    listAllPages(): string[] {
      return [];
    },
  };
}

// =============================================================================
// 模块级扫描器注入
// =============================================================================

let _scanner: PageMigrationScanner | null = null;

/**
 * 获取页面迁移扫描器（惰性初始化默认实现）。
 */
export function getPageMigrationScanner(): PageMigrationScanner {
  if (_scanner) {
    return _scanner;
  }
  _scanner = createDefaultScanner();
  return _scanner;
}

/**
 * 设置页面迁移扫描器（测试注入 mock 或注入 CI 脚本真实扫描器）。
 */
export function setPageMigrationScanner(scanner: PageMigrationScanner | null): void {
  _scanner = scanner;
}

// =============================================================================
// 合法 WaveKey 集合（用于校验）
// =============================================================================

const VALID_WAVE_KEYS: ReadonlySet<string> = new Set(['wave1', 'wave2', 'wave3', 'wave4']);

// =============================================================================
// 内部校验函数
// =============================================================================

/**
 * 构造 MigrationViolation 工厂函数。
 */
function createViolation(
  type: MigrationViolationType,
  page: string,
  component: string,
  detail: string,
): MigrationViolation {
  return { type, page, component, detail };
}

/**
 * 校验单页面混用（对齐 C5 §coexistenceLint.samePageMixProhibition）。
 *
 * 注意：单页面混用检测的异常归属是 FE-COM-003（COM 模块，eslint-plugin-import 规则抛出）。
 * 模块0 不越界抛出 ComponentMixError，而是记录到 MigrationReport.violations 返回。
 * 仅当检测到 lint 规则编排层冲突时，才抛出 LintRuleConflictError（FE-MIG-003）。
 */
function validatePageNoMix(
  scanResult: PageImportScanResult,
  samePageMixProhibition: boolean,
): MigrationViolation[] {
  const violations: MigrationViolation[] = [];
  if (!samePageMixProhibition) {
    return violations;
  }
  if (scanResult.oldComponents.length > 0 && scanResult.newComponents.length > 0) {
    for (const oldComp of scanResult.oldComponents) {
      violations.push(
        createViolation(
          'mix-old-new',
          scanResult.page,
          oldComp,
          `页面 ${scanResult.page} 同时引用旧组件 ${oldComp}（@/components/）与新组件 [${scanResult.newComponents.join(', ')}]（@/components/ui-v2/），` +
            '违反 samePageMixProhibition（merged.md §4.5：不允许在同一页面混用新旧组件）',
        ),
      );
    }
  }
  return violations;
}

/**
 * 校验组件 Glass 属性（data-glass / motion variants / 共享 token）。
 *
 * - 缺失 data-glass 属性的"关键组件"视为阻断式违规，抛出 MigrationBlockedError（FE-MIG-001）
 * - 缺失 motion variants 记录为非阻断式违规
 * - token 不一致记录为非阻断式违规
 */
function validateComponentGlass(
  componentName: string,
  page: string,
  checkResult: ComponentGlassCheckResult,
  sharedTokenLayer: boolean,
): MigrationViolation[] {
  const violations: MigrationViolation[] = [];

  // data-glass 属性校验（阻断式，对齐 I5 §validateMigration raises: 关键组件缺失 data-glass 属性）
  if (!checkResult.hasDataGlass) {
    // 关键组件缺失 data-glass 属性 → 阻断式违规，抛出 MigrationBlockedError（FE-MIG-001）
    throw new MigrationBlockedError(
      `validateMigration 阻断式违规: 关键组件 ${componentName} 缺失 data-glass 属性（页面: ${page}）。` +
        '对齐 I5 §validateMigration raises: 关键组件缺失 data-glass 属性。' +
        '对齐 E1 §FE-MIG-001（validateMigration 路径，单组件执行层违规由 FE-COM-001 处理，本异常是编排层阻断）。',
      [createViolation('missing-glass-attr', page, componentName, `组件 ${componentName} 缺失 data-glass 属性`)],
    );
  }

  // motion variants 校验（非阻断式）
  if (!checkResult.hasMotionVariants) {
    violations.push(
      createViolation(
        'missing-motion-variants',
        page,
        componentName,
        `组件 ${componentName} 未用 Framer Motion variants 替换 shadcn 默认 Tailwind transition（merged.md §4.2 定制策略）`,
      ),
    );
  }

  // 共享 token 校验（非阻断式，对齐 C5 §coexistenceLint.sharedTokenLayer）
  if (sharedTokenLayer && !checkResult.usesSharedToken) {
    violations.push(
      createViolation(
        'token-mismatch',
        page,
        componentName,
        `组件 ${componentName} 未消费共享 token（可能硬编码颜色），违反 sharedTokenLayer（merged.md §4.5 视觉一致性）`,
      ),
    );
  }

  return violations;
}

// =============================================================================
// validateMigration — 校验迁移完整性（严格匹配 I5 §validateMigration 签名）
// =============================================================================

/**
 * 校验迁移完整性（严格匹配 I5 §validateMigration 签名）。
 *
 * 对应 TS: `validateMigration(waveKey: WaveKey, pagePath?: string): MigrationReport`
 *
 * 校验项（merged.md §4.5 并存期管理 + C5 §coexistenceLint）：
 *   1. 页面无混用新旧组件（samePageMixProhibition）
 *   2. lint 规则（eslintImportPlugin）
 *   3. 共享 token（sharedTokenLayer）
 *   4. data-glass 属性（迁移后的组件必须挂载）
 *   5. motion variants（迁移后的组件必须用 Framer Motion variants 替换 shadcn 默认 transition）
 *
 * @param waveKey 校验的波次（'wave1'-'wave4'）
 * @param pagePath 可选，限定校验的页面路径。不提供则校验全部页面。
 * @returns MigrationReport 校验报告（passed / violations / summary / waveKey）
 *   - passed=true: 所有校验通过
 *   - passed=false: 存在违规，violations 列出详情
 * @throws LintRuleConflictError 当检测到 lint 规则编排层冲突时抛出（FE-MIG-003）
 *   - eslintImportPlugin=true 但与现有 .eslintrc 冲突
 *   - samePageMixProhibition 规则误报合法引用
 * @throws MigrationBlockedError 当发现阻断式违规（关键组件缺失 data-glass 属性）时抛出（FE-MIG-001）
 *   - 注意：单组件执行层违规由 FE-COM-001 处理（COM 模块），本异常是编排层阻断
 */
export function validateMigration(
  waveKey: WaveKey,
  pagePath?: string,
): MigrationReport {
  // 校验 waveKey
  if (!VALID_WAVE_KEYS.has(waveKey)) {
    throw new MigrationBlockedError(
      `validateMigration 校验失败: waveKey "${waveKey}" 不在 wave1-wave4 范围内`,
    );
  }

  const config = getMigrationConfig();
  const { coexistenceLint } = config;
  const scanner = getPageMigrationScanner();
  const violations: MigrationViolation[] = [];

  // ---- lint 规则编排层冲突检测（对齐 C5 §coexistenceLint.eslintImportPlugin）----
  // 对齐 E1 §FE-MIG-003 trigger: eslintImportPlugin=true 但与现有 .eslintrc 冲突，或 samePageMixProhibition 误报
  if (coexistenceLint.eslintImportPlugin) {
    const lintConflict = scanner.checkLintConflict();
    if (lintConflict.hasEslintConfigConflict || lintConflict.hasFalsePositive) {
      throw new LintRuleConflictError(
        `validateMigration 检测到 lint 规则编排层冲突: ${lintConflict.detail}。` +
          '对齐 E1 §FE-MIG-003 trigger: eslintImportPlugin=true 但与现有 .eslintrc 冲突，或 samePageMixProhibition 规则误报。' +
          '注意：与 FE-COM-003 区分——本错误码是 lint 规则编排层冲突，FE-COM-003 是单页面混用检测（组件层）。',
      );
    }
  }

  // ---- 确定校验页面清单 ----
  const pagesToValidate: string[] = pagePath ? [pagePath] : scanner.listAllPages();

  // ---- 逐页面校验 ----
  for (const page of pagesToValidate) {
    // 1. 页面无混用新旧组件（对齐 C5 §coexistenceLint.samePageMixProhibition）
    const scanResult = scanner.scanPageImports(page);
    violations.push(
      ...validatePageNoMix(scanResult, coexistenceLint.samePageMixProhibition),
    );

    // 2. lint 规则校验（对齐 C5 §coexistenceLint.newCodeLegacyImportWarning）
    // 新代码引用 components/（旧目录）时告警
    if (coexistenceLint.newCodeLegacyImportWarning && scanResult.newComponents.length > 0) {
      // 新组件页面不应再引用旧组件（newCodeLegacyImportWarning 配置下）
      for (const oldComp of scanResult.oldComponents) {
        violations.push(
          createViolation(
            'lint-violation',
            page,
            oldComp,
            `页面 ${page} 引用了新组件 [${scanResult.newComponents.join(', ')}] 但仍引用旧组件 ${oldComp}，` +
              '违反 newCodeLegacyImportWarning（新代码引用 components/ 时告警，merged.md §4.5）',
          ),
        );
      }
    }

    // 3-5. 校验新组件的 Glass 属性（data-glass / motion variants / 共享 token）
    for (const newComp of scanResult.newComponents) {
      const glassCheck = scanner.checkComponentGlass(newComp);
      // validateComponentGlass 内部可能抛出 MigrationBlockedError（阻断式）
      violations.push(
        ...validateComponentGlass(
          newComp,
          page,
          glassCheck,
          coexistenceLint.sharedTokenLayer,
        ),
      );
    }
  }

  // ---- 生成 MigrationReport ----
  const passed = violations.length === 0;
  const summary = passed
    ? `${waveKey} 校验通过: ${pagesToValidate.length} 个页面，无违规`
    : `${waveKey} 校验失败: ${pagesToValidate.length} 个页面，${violations.length} 项违规` +
      `（混用 ${violations.filter((v) => v.type === 'mix-old-new').length} / ` +
      `lint ${violations.filter((v) => v.type === 'lint-violation').length} / ` +
      `token ${violations.filter((v) => v.type === 'token-mismatch').length} / ` +
      `data-glass ${violations.filter((v) => v.type === 'missing-glass-attr').length} / ` +
      `motion ${violations.filter((v) => v.type === 'missing-motion-variants').length}）`;

  return {
    passed,
    violations,
    summary,
    waveKey,
  };
}
