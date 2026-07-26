/**
 * @file Lighthouse CI 配置与触发模块
 *
 * 职责：生成 Lighthouse CI 守门配置，评估 Lighthouse 评分是否达标，
 * 在 PR 流程中触发阻断（评分低于阈值时对应 FE-PER-004 Lighthouse CI 阻断）。
 *
 * 契约对齐：
 * - D7 performance_budget.schema.json §lighthouseCI（performanceScoreBlock.threshold=80，PR 不达标阻断）
 * - C4 frontend_performance_config.schema.json §lighthouseCIGate（lighthouseMinScore=80，lighthouseBlockingEnabled=true）
 * - E1 frontend_error_codes.schema.json §FE-PER-004（Lighthouse CI 阻断：PR 首屏性能分数 < lighthouseMinScore）
 *
 * 任务描述的 4 维阈值（performance ≥ 0.9 / accessibility ≥ 0.95 / best-practices ≥ 0.9 / SEO ≥ 0.9）
 * 作为默认配置；D7/C4 的 80 分底线作为次级守门，两者均配置驱动。
 *
 * 跨模块导入约束：仅 import 第三方库（Lighthouse CI 运行时由 Node 侧执行，本模块仅产出配置）。
 */

/**
 * Lighthouse 4 维评分阈值（0-1 范围）。
 * 任务描述默认：performance ≥ 0.9 / accessibility ≥ 0.95 / best-practices ≥ 0.9 / SEO ≥ 0.9。
 */
export interface LighthouseThresholds {
  /** 性能分数阈值（0-1），默认 0.9 */
  readonly performance: number;
  /** 可访问性分数阈值（0-1），默认 0.95 */
  readonly accessibility: number;
  /** 最佳实践分数阈值（0-1），默认 0.9 */
  readonly bestPractices: number;
  /** SEO 分数阈值（0-1），默认 0.9 */
  readonly seo: number;
}

/**
 * Lighthouse 最低性能分数底线（D7/C4 的 80 分守门）。
 * 这是 PR 阻断的硬性底线，低于此值直接阻断合并。
 */
export interface LighthouseFloorScore {
  /** 最低性能分数（0-100 分制），默认 80，对齐 D7/C4 */
  readonly minScore: number;
  /** 是否启用 Lighthouse CI 阻断，默认 true，对齐 C4 lighthouseBlockingEnabled */
  readonly blockingEnabled: boolean;
}

/**
 * Lighthouse CI 配置（合并 4 维阈值 + D7/C4 底线）。
 */
export interface LighthouseCIConfig {
  /** 4 维评分阈值 */
  readonly thresholds: LighthouseThresholds;
  /** D7/C4 底线分数（80 分守门） */
  readonly floorScore: LighthouseFloorScore;
  /** 待检测 URL 列表 */
  readonly urls: readonly string[];
  /** Lighthouse 运行模式（desktop/mobile），默认 desktop（桌面端为主战场，spec §四已裁决） */
  readonly preset: 'desktop' | 'mobile';
}

/**
 * Lighthouse 默认 4 维阈值（任务描述要求）。
 */
export const DEFAULT_LIGHTHOUSE_THRESHOLDS: LighthouseThresholds = {
  performance: 0.9,
  accessibility: 0.95,
  bestPractices: 0.9,
  seo: 0.9,
};

/**
 * D7/C4 默认底线分数（80 分，PR 不达标阻断）。
 */
export const DEFAULT_LIGHTHOUSE_FLOOR_SCORE: LighthouseFloorScore = {
  minScore: 80,
  blockingEnabled: true,
};

/**
 * Lighthouse CI 默认配置。
 */
export const DEFAULT_LIGHTHOUSE_CI_CONFIG: LighthouseCIConfig = {
  thresholds: DEFAULT_LIGHTHOUSE_THRESHOLDS,
  floorScore: DEFAULT_LIGHTHOUSE_FLOOR_SCORE,
  urls: ['http://localhost:4173'], // vite preview 默认端口
  preset: 'desktop',
};

/**
 * Lighthouse 实际采集结果（4 维分数 + 性能分数百分制）。
 */
export interface LighthouseResult {
  /** 性能分数（0-1） */
  readonly performance: number;
  /** 可访问性分数（0-1） */
  readonly accessibility: number;
  /** 最佳实践分数（0-1） */
  readonly bestPractices: number;
  /** SEO 分数（0-1） */
  readonly seo: number;
  /** 采集时间戳（epoch ms） */
  readonly timestamp: number;
}

/**
 * Lighthouse 评分未达标项。
 */
export interface LighthouseAssertionFailure {
  /** 未达标维度 */
  readonly category: keyof LighthouseThresholds;
  /** 实际分数（0-1） */
  readonly actual: number;
  /** 阈值（0-1） */
  readonly expected: number;
  /** 是否触发 PR 阻断（性能分数 < floorScore.minScore 时为 true） */
  readonly blocksPR: boolean;
  /** 错误码（E1 §FE-PER-004） */
  readonly errorCode: 'FE-PER-004';
}

/**
 * Lighthouse 评估结果。
 */
export interface LighthouseEvaluation {
  /** 是否通过所有阈值 */
  readonly passed: boolean;
  /** 未达标项列表（空数组表示全部通过） */
  readonly failures: readonly LighthouseAssertionFailure[];
  /** 是否触发 PR 阻断 */
  readonly prBlocked: boolean;
  /** 原始采集结果 */
  readonly result: LighthouseResult;
}

/**
 * Lighthouse CI 阻断错误。对应 E1 §FE-PER-004。
 * 触发条件：lighthouseBlockingEnabled=true 且 PR 首屏性能分数 < lighthouseMinScore。
 */
export class LighthouseCIBlockedError extends Error {
  public readonly errorCode = 'FE-PER-004' as const;
  public readonly failures: readonly LighthouseAssertionFailure[];

  constructor(failures: readonly LighthouseAssertionFailure[]) {
    const detail = failures.map(f => `${f.category}=${f.actual.toFixed(2)}<${f.expected.toFixed(2)}`).join(', ');
    super(`[FE-PER-004] Lighthouse CI 阻断：评分未达标 - ${detail}`);
    this.name = 'LighthouseCIBlockedError';
    this.failures = failures;
  }
}

/**
 * 评估 Lighthouse 采集结果是否通过配置阈值。
 *
 * @param result Lighthouse 采集结果
 * @param config Lighthouse CI 配置（默认 DEFAULT_LIGHTHOUSE_CI_CONFIG）
 * @returns 评估结果（含未达标项与是否阻断 PR）
 */
export function evaluateLighthouseResult(
  result: LighthouseResult,
  config: LighthouseCIConfig = DEFAULT_LIGHTHOUSE_CI_CONFIG,
): LighthouseEvaluation {
  const failures: LighthouseAssertionFailure[] = [];

  const checks: Array<{ category: keyof LighthouseThresholds; actual: number; expected: number }> = [
    { category: 'performance', actual: result.performance, expected: config.thresholds.performance },
    { category: 'accessibility', actual: result.accessibility, expected: config.thresholds.accessibility },
    { category: 'bestPractices', actual: result.bestPractices, expected: config.thresholds.bestPractices },
    { category: 'seo', actual: result.seo, expected: config.thresholds.seo },
  ];

  for (const check of checks) {
    if (check.actual < check.expected) {
      // 性能分数 < floorScore 时触发 PR 阻断；其他维度未达标仅告警不阻断
      const blocksPR =
        check.category === 'performance' &&
        config.floorScore.blockingEnabled &&
        result.performance * 100 < config.floorScore.minScore;

      failures.push({
        category: check.category,
        actual: check.actual,
        expected: check.expected,
        blocksPR,
        errorCode: 'FE-PER-004',
      });
    }
  }

  const prBlocked =
    config.floorScore.blockingEnabled &&
    result.performance * 100 < config.floorScore.minScore;

  return {
    passed: failures.length === 0,
    failures,
    prBlocked,
    result,
  };
}

/**
 * 生成 Lighthouse CI 配置对象（lighthouserc.json 格式）。
 *
 * 输出格式对齐 @lhci/cli 的配置规范，可写入 lighthouserc.json 或 lighthouse-ci.config.js。
 * 本函数仅生成配置对象，不执行文件写入（写入需经 s0401 安全文件写入 Skill 判定）。
 *
 * @param config Lighthouse CI 配置（默认 DEFAULT_LIGHTHOUSE_CI_CONFIG）
 * @returns lighthouserc 配置对象
 */
export function generateLighthouseConfig(
  config: LighthouseCIConfig = DEFAULT_LIGHTHOUSE_CI_CONFIG,
): Record<string, unknown> {
  const assertions: Record<string, { minScore: number }> = {
    'categories:performance': { minScore: config.thresholds.performance },
    'categories:accessibility': { minScore: config.thresholds.accessibility },
    'categories:best-practices': { minScore: config.thresholds.bestPractices },
    'categories:seo': { minScore: config.thresholds.seo },
  };

  return {
    ci: {
      collect: {
        url: [...config.urls],
        settings: {
          preset: config.preset,
        },
      },
      assert: {
        assertions,
        preset: 'lighthouse:no-pwa',
      },
      upload: {
        target: 'filesystem',
        outputDir: '.lighthouse-ci',
        reportFilenamePattern: '%%-%%-%%-%%-%%.json',
      },
    },
  };
}

/**
 * 将 Lighthouse 评估结果序列化为可上报的告警负载。
 * 用于性能 dashboard 阈值告警展示（D7 §runtimeMonitoring RM-04）。
 */
export function serializeLighthouseAlert(evaluation: LighthouseEvaluation): {
  readonly blocked: boolean;
  readonly prBlocked: boolean;
  readonly failures: ReadonlyArray<{
    readonly category: string;
    readonly actual: number;
    readonly expected: number;
    readonly errorCode: string;
  }>;
} {
  return {
    blocked: !evaluation.passed,
    prBlocked: evaluation.prBlocked,
    failures: evaluation.failures.map(f => ({
      category: f.category,
      actual: f.actual,
      expected: f.expected,
      errorCode: f.errorCode,
    })),
  };
}
