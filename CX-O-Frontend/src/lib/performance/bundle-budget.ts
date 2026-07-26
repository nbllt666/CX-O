/**
 * @file Bundle Budget 监控模块
 *
 * 职责：监控 Vite build 产出的 chunk 体积，校验是否超出 bundle budget 阈值，
 * 超预算时触发 FE-PER-001（性能预算超标范畴）。
 *
 * 契约对齐：
 * - D7 performance_budget.schema.json §bundleSize（首屏 JS ≤ 180KB / 总 JS ≤ 650KB / CSS ≤ 60KB gzip）
 * - C4 frontend_performance_config.schema.json §bundleSizeLimits（firstScreenJsLimit=180 / totalJsLimit=650 /
 *   cssLimit=60 / webglChunkSize=50 / motionChunkSize=80）
 * - E1 frontend_error_codes.schema.json §FE-PER-001（性能阈值超标）
 *
 * 任务描述的 chunk 级阈值（main ≤ 200KB / lazy chunk ≤ 50KB / glass shader ≤ 30KB）作为默认值；
 * C4 的 firstScreenJsLimit 作为更严格的可选覆盖。
 *
 * 跨模块导入约束：仅 import Node fs/path（chunk 体积读取），禁止 import 模块1-8 内部实现。
 * 运行时环境：主要在构建后（Node 侧）执行，浏览器环境通过注入的 manifest 数据校验。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, extname, basename } from 'node:path';

/**
 * Bundle Budget 阈值配置。
 * 默认值融合任务描述（main/lazy/glass-shader）与 C4/D7（total/css）。
 */
export interface BundleBudgetLimits {
  /** main bundle 体积上限（KB gzip），默认 200，对齐任务描述 */
  readonly mainBundle: number;
  /** lazy chunk 体积上限（KB gzip），默认 50，对齐任务描述 */
  readonly lazyChunk: number;
  /** glass shader chunk 体积上限（KB gzip），默认 30，对齐任务描述 */
  readonly glassShaderChunk: number;
  /** 总 JS 体积上限（KB gzip），默认 650，对齐 C4 totalJsLimit / D7 bundleSize.totalJs */
  readonly totalJs: number;
  /** CSS 体积上限（KB gzip），默认 60，对齐 C4 cssLimit / D7 bundleSize.css */
  readonly css: number;
}

/**
 * 默认 Bundle Budget 阈值。
 * main/lazy/glass-shader 来源任务描述；total/css 来源 C4/D7 契约默认值。
 */
export const DEFAULT_BUNDLE_BUDGET_LIMITS: BundleBudgetLimits = {
  mainBundle: 200,
  lazyChunk: 50,
  glassShaderChunk: 30,
  totalJs: 650,
  css: 60,
};

/**
 * 单个 chunk 的体积测量结果。
 */
export interface BundleChunkMetric {
  /** chunk 文件名（如 index-abc123.js） */
  readonly filename: string;
  /** chunk 类型分类 */
  readonly category: 'main' | 'lazy' | 'glass-shader' | 'motion' | 'css' | 'other';
  /** 原始体积（bytes） */
  readonly rawBytes: number;
  /** gzip 体积（bytes） */
  readonly gzipBytes: number;
}

/**
 * 整体 bundle 体积报告。
 */
export interface BundleBudgetReport {
  /** 所有 chunk 的测量结果 */
  readonly chunks: readonly BundleChunkMetric[];
  /** main bundle 总体积（KB gzip） */
  readonly mainBundleSize: number;
  /** 最大 lazy chunk 体积（KB gzip） */
  readonly maxLazyChunkSize: number;
  /** glass shader chunk 体积（KB gzip） */
  readonly glassShaderChunkSize: number;
  /** 总 JS 体积（KB gzip） */
  readonly totalJsSize: number;
  /** 总 CSS 体积（KB gzip） */
  readonly totalCssSize: number;
  /** 测量时间戳（epoch ms） */
  readonly timestamp: number;
}

/**
 * 单个 bundle 超预算项。
 */
export interface BundleBudgetExceeded {
  /** 超预算的维度 */
  readonly dimension: 'mainBundle' | 'lazyChunk' | 'glassShaderChunk' | 'totalJs' | 'css';
  /** 实际体积（KB gzip） */
  readonly actual: number;
  /** 阈值（KB gzip） */
  readonly limit: number;
  /** 涉及的 chunk 文件名（total/css 维度为空数组） */
  readonly offenders: readonly string[];
  /** 错误码（E1 §FE-PER-001 性能阈值超标范畴） */
  readonly errorCode: 'FE-PER-001';
  /** 辅助标识（遵循 D7 §errorCodes PB_ 前缀 pattern） */
  readonly budgetCode: 'PB_BUNDLE_OVER_BUDGET';
}

/**
 * Bundle 预算超标错误。对应 E1 §FE-PER-001。
 *
 * 注意：任务描述将 bundle 超预算映射到 FE-PER-004，但 E1 中 FE-PER-004 是 Lighthouse CI 阻断。
 * 以 E1 冻结契约为准：bundle 超预算归入 FE-PER-001（性能阈值超标）。
 */
export class BundleBudgetExceededError extends Error {
  public readonly errorCode = 'FE-PER-001' as const;
  public readonly exceeded: readonly BundleBudgetExceeded[];

  constructor(exceeded: readonly BundleBudgetExceeded[]) {
    const detail = exceeded
      .map(e => `${e.dimension}=${e.actual.toFixed(1)}KB>${e.limit}KB`)
      .join(', ');
    super(`[FE-PER-001] Bundle 体积超预算 - ${detail}`);
    this.name = 'BundleBudgetExceededError';
    this.exceeded = exceeded;
  }
}

/**
 * bytes 转 KB。
 */
function bytesToKB(bytes: number): number {
  return Math.round((bytes / 1024) * 100) / 100;
}

/**
 * 估算 gzip 体积（无 zlib 可用时退化为 raw * 0.3 系数）。
 * 生产构建应使用 vite-plugin-compression 的实际产物。
 */
function estimateGzipBytes(rawBytes: number, gzipBytes?: number): number {
  if (gzipBytes !== undefined && gzipBytes > 0) {
    return gzipBytes;
  }
  // 典型 JS gzip 压缩比约 0.3，CSS 约 0.4，取保守 0.35
  return Math.round(rawBytes * 0.35);
}

/**
 * 根据 chunk 文件名分类。
 */
function categorizeChunk(filename: string): BundleChunkMetric['category'] {
  const lower = filename.toLowerCase();
  if (extname(lower) === '.css') {
    return 'css';
  }
  if (lower.includes('glass') || lower.includes('shader') || lower.includes('webgl')) {
    return 'glass-shader';
  }
  if (lower.includes('motion') || lower.includes('gsap') || lower.includes('framer')) {
    return 'motion';
  }
  // main bundle 通常是 index-*.js 或直接 index.js
  if (lower.startsWith('index') || lower === 'main.js' || lower.includes('main-')) {
    return 'main';
  }
  return 'lazy';
}

/**
 * 读取单个 chunk 文件的体积。
 */
function measureChunk(filePath: string): BundleChunkMetric {
  const filename = basename(filePath);
  const category = categorizeChunk(filename);
  const rawBytes = statSync(filePath).size;

  // 尝试读取同名 .gz 文件获取真实 gzip 体积
  let gzipBytes: number | undefined;
  try {
    const gzPath = `${filePath}.gz`;
    gzipBytes = statSync(gzPath).size;
  } catch {
    gzipBytes = undefined;
  }

  return {
    filename,
    category,
    rawBytes,
    gzipBytes: estimateGzipBytes(rawBytes, gzipBytes),
  };
}

/**
 * 递归扫描 dist 目录，收集所有 chunk 体积。
 *
 * @param distDir dist 目录绝对路径（如 CX-O-Frontend/dist）
 * @returns 所有 chunk 的测量结果
 */
export function scanDistChunks(distDir: string): readonly BundleChunkMetric[] {
  const results: BundleChunkMetric[] = [];

  function walk(dir: string): void {
    let entries: readonly string[];
    try {
      entries = readdirSync(dir);
    } catch {
      return;
    }

    for (const entry of entries) {
      const fullPath = join(dir, entry);
      let stat;
      try {
        stat = statSync(fullPath);
      } catch {
        continue;
      }

      if (stat.isDirectory()) {
        walk(fullPath);
      } else {
        const ext = extname(entry);
        if (ext === '.js' || ext === '.css' || ext === '.mjs') {
          results.push(measureChunk(fullPath));
        }
      }
    }
  }

  walk(distDir);
  return results;
}

/**
 * 从 chunk 列表汇总为 bundle budget 报告。
 */
export function summarizeBundleReport(
  chunks: readonly BundleChunkMetric[],
): BundleBudgetReport {
  const jsChunks = chunks.filter(c => c.category !== 'css');
  const cssChunks = chunks.filter(c => c.category === 'css');

  const mainChunks = jsChunks.filter(c => c.category === 'main');
  const lazyChunks = jsChunks.filter(c => c.category === 'lazy');
  const glassShaderChunks = jsChunks.filter(c => c.category === 'glass-shader');

  const mainBundleSize = bytesToKB(mainChunks.reduce((sum, c) => sum + c.gzipBytes, 0));
  const maxLazyChunkSize = lazyChunks.length > 0
    ? bytesToKB(Math.max(...lazyChunks.map(c => c.gzipBytes)))
    : 0;
  const glassShaderChunkSize = bytesToKB(glassShaderChunks.reduce((sum, c) => sum + c.gzipBytes, 0));
  const totalJsSize = bytesToKB(jsChunks.reduce((sum, c) => sum + c.gzipBytes, 0));
  const totalCssSize = bytesToKB(cssChunks.reduce((sum, c) => sum + c.gzipBytes, 0));

  return {
    chunks,
    mainBundleSize,
    maxLazyChunkSize,
    glassShaderChunkSize,
    totalJsSize,
    totalCssSize,
    timestamp: Date.now(),
  };
}

/**
 * 评估 bundle 报告是否超出预算阈值。
 *
 * @param report bundle 体积报告
 * @param limits 预算阈值（默认 DEFAULT_BUNDLE_BUDGET_LIMITS）
 * @returns 超预算项列表（空数组表示全部通过）
 */
export function evaluateBundleBudget(
  report: BundleBudgetReport,
  limits: BundleBudgetLimits = DEFAULT_BUNDLE_BUDGET_LIMITS,
): readonly BundleBudgetExceeded[] {
  const exceeded: BundleBudgetExceeded[] = [];

  if (report.mainBundleSize > limits.mainBundle) {
    exceeded.push({
      dimension: 'mainBundle',
      actual: report.mainBundleSize,
      limit: limits.mainBundle,
      offenders: report.chunks.filter(c => c.category === 'main').map(c => c.filename),
      errorCode: 'FE-PER-001',
      budgetCode: 'PB_BUNDLE_OVER_BUDGET',
    });
  }

  if (report.maxLazyChunkSize > limits.lazyChunk) {
    exceeded.push({
      dimension: 'lazyChunk',
      actual: report.maxLazyChunkSize,
      limit: limits.lazyChunk,
      offenders: report.chunks.filter(c => c.category === 'lazy').map(c => c.filename),
      errorCode: 'FE-PER-001',
      budgetCode: 'PB_BUNDLE_OVER_BUDGET',
    });
  }

  if (report.glassShaderChunkSize > limits.glassShaderChunk) {
    exceeded.push({
      dimension: 'glassShaderChunk',
      actual: report.glassShaderChunkSize,
      limit: limits.glassShaderChunk,
      offenders: report.chunks.filter(c => c.category === 'glass-shader').map(c => c.filename),
      errorCode: 'FE-PER-001',
      budgetCode: 'PB_BUNDLE_OVER_BUDGET',
    });
  }

  if (report.totalJsSize > limits.totalJs) {
    exceeded.push({
      dimension: 'totalJs',
      actual: report.totalJsSize,
      limit: limits.totalJs,
      offenders: [],
      errorCode: 'FE-PER-001',
      budgetCode: 'PB_BUNDLE_OVER_BUDGET',
    });
  }

  if (report.totalCssSize > limits.css) {
    exceeded.push({
      dimension: 'css',
      actual: report.totalCssSize,
      limit: limits.css,
      offenders: [],
      errorCode: 'FE-PER-001',
      budgetCode: 'PB_BUNDLE_OVER_BUDGET',
    });
  }

  return exceeded;
}

/**
 * 从 Vite manifest 文件（manifest.json）读取 chunk 体积信息。
 *
 * Vite build 产物中 assets 目录下通常包含 manifest.json，
 * 记录每个 chunk 的文件名与依赖关系。本函数解析 manifest 并结合文件体积校验。
 *
 * @param distDir dist 目录路径
 * @returns chunk 测量结果
 */
export function readFromViteManifest(distDir: string): readonly BundleChunkMetric[] {
  let manifestContent: string;
  try {
    manifestContent = readFileSync(join(distDir, 'manifest.json'), 'utf-8');
  } catch {
    // manifest 不存在时退化为目录扫描
    return scanDistChunks(distDir);
  }

  let manifest: Record<string, { file?: string; src?: string }>;
  try {
    manifest = JSON.parse(manifestContent) as Record<string, { file?: string; src?: string }>;
  } catch {
    return scanDistChunks(distDir);
  }

  const chunks: BundleChunkMetric[] = [];
  for (const entry of Object.values(manifest)) {
    if (entry.file === undefined) {
      continue;
    }
    const filePath = join(distDir, entry.file);
    try {
      const filename = entry.file;
      const category = categorizeChunk(filename);
      const rawBytes = statSync(filePath).size;
      chunks.push({
        filename,
        category,
        rawBytes,
        gzipBytes: estimateGzipBytes(rawBytes),
      });
    } catch {
      // 文件不存在，跳过
    }
  }

  return chunks;
}

/**
 * 完整的 bundle budget 校验流程：扫描 dist -> 汇总 -> 评估 -> 超预算抛错。
 *
 * @param distDir dist 目录路径（默认 'dist'）
 * @param limits 预算阈值（默认 DEFAULT_BUNDLE_BUDGET_LIMITS）
 * @param throwOnExceed 是否在超预算时抛出异常（默认 true）
 * @returns bundle 报告与超预算项
 *
 * @throws BundleBudgetExceededError 当 throwOnExceed=true 且存在超预算项时
 */
export function runBundleBudgetCheck(
  distDir: string,
  limits: BundleBudgetLimits = DEFAULT_BUNDLE_BUDGET_LIMITS,
  throwOnExceed: boolean = true,
): { readonly report: BundleBudgetReport; readonly exceeded: readonly BundleBudgetExceeded[] } {
  const chunks = readFromViteManifest(distDir);
  const report = summarizeBundleReport(chunks);
  const exceeded = evaluateBundleBudget(report, limits);

  if (throwOnExceed && exceeded.length > 0) {
    throw new BundleBudgetExceededError(exceeded);
  }

  return { report, exceeded };
}
