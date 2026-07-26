/**
 * @file Web Vitals 采集模块
 *
 * 职责：封装 web-vitals 库采集 LCP/CLS/INP/TTFB/FCP 五项核心指标，
 * 并通过原生 PerformanceObserver 补采 FID（web-vitals v6 已废弃 onFID）。
 *
 * 契约对齐：
 * - D7 performance_budget.schema.json §webVitals（LCP 2500ms / FCP 1800ms / TTI 3800ms / CLS 0.1 / INP 200ms）
 * - C4 frontend_performance_config.schema.json §webVitalsThresholds（默认值与 D7 一致）
 * - E1 frontend_error_codes.schema.json §FE-PER-001（性能阈值超标 / 采集失败归入此码）
 *
 * 跨模块导入约束：仅 import web-vitals 第三方库，禁止 import 模块1-8 内部实现。
 */

import { onCLS, onFCP, onINP, onLCP, onTTFB, type Metric } from 'web-vitals';

/**
 * Web Vitals 阈值配置（与 C4 §webVitalsThresholds / D7 §webVitals 对齐）。
 * 所有阈值均从配置注入，不硬编码于业务逻辑。
 */
export interface WebVitalsThresholds {
  /** LCP 阈值（ms），默认 2500 对齐 D7/C4 */
  readonly lcp: number;
  /** FCP 阈值（ms），默认 1800 */
  readonly fcp: number;
  /** TTI 阈值（ms），默认 3800 */
  readonly tti: number;
  /** CLS 阈值（无量纲），默认 0.1 */
  readonly cls: number;
  /** INP 阈值（ms），默认 200 */
  readonly inp: number;
}

/**
 * Web Vitals 默认阈值（与 C4 frontend_performance_config.schema.json 默认值严格对齐）。
 * 来源：D7 performance_budget.schema.json §webVitals.*.threshold.default。
 */
export const DEFAULT_WEB_VITALS_THRESHOLDS: WebVitalsThresholds = {
  lcp: 2500,
  fcp: 1800,
  tti: 3800,
  cls: 0.1,
  inp: 200,
};

/**
 * 单次 Web Vitals 采集报告。
 * 每项指标在浏览器实际触发时填充，未触发的指标为 undefined。
 */
export interface WebVitalsReport {
  /** Largest Contentful Paint 最大内容绘制（ms） */
  readonly lcp?: number;
  /** First Contentful Paint 首次内容绘制（ms） */
  readonly fcp?: number;
  /** Cumulative Layout Shift 累积布局偏移（无量纲） */
  readonly cls?: number;
  /** Interaction to Next Paint 交互到下一次绘制（ms） */
  readonly inp?: number;
  /** Time to First Byte 首字节时间（ms） */
  readonly ttfb?: number;
  /** First Input Delay 首次输入延迟（ms，web-vitals v6 废弃，改用原生 PerformanceObserver） */
  readonly fid?: number;
  /** 采集时间戳（epoch ms） */
  readonly timestamp: number;
}

/**
 * Web Vitals 回调函数类型。每次指标更新时触发。
 */
export type WebVitalsCallback = (report: WebVitalsReport) => void;

/**
 * Web Vitals 阈值超标事件。
 */
export interface WebVitalsThresholdExceeded {
  readonly metric: keyof Pick<WebVitalsReport, 'lcp' | 'fcp' | 'cls' | 'inp' | 'ttfb' | 'fid'>;
  readonly value: number;
  readonly threshold: number;
  readonly errorCode: 'FE-PER-001';
}

/**
 * Web Vitals 采集失败错误。对应 E1 §FE-PER-001（性能阈值超标范畴）。
 * 采集失败时无法判定阈值是否超标，归入此码并标记为采集失败。
 */
export class WebVitalsCollectionError extends Error {
  public readonly errorCode = 'FE-PER-001' as const;
  public readonly metric: string;

  constructor(metric: string, originalError?: unknown) {
    const detail = originalError instanceof Error ? originalError.message : String(originalError);
    super(`[FE-PER-001] Web Vitals 采集失败：指标 ${metric} 采集异常 - ${detail}`);
    this.name = 'WebVitalsCollectionError';
    this.metric = metric;
  }
}

/**
 * 内部状态：当前已采集的指标缓存，供回调增量更新。
 */
interface InternalReport {
  lcp?: number;
  fcp?: number;
  cls?: number;
  inp?: number;
  ttfb?: number;
  fid?: number;
  timestamp: number;
}

/**
 * 创建内部报告的快照（不可变）。
 */
function snapshot(internal: InternalReport): WebVitalsReport {
  return {
    lcp: internal.lcp,
    fcp: internal.fcp,
    cls: internal.cls,
    inp: internal.inp,
    ttfb: internal.ttfb,
    fid: internal.fid,
    timestamp: internal.timestamp,
  };
}

/**
 * 采集 FID（First Input Delay）。
 *
 * web-vitals v6 已废弃 onFID（FID 被 INP 取代），但本模块按任务要求保留 FID 采集，
 * 使用原生 PerformanceObserver 观察 'first-input' 条目。
 * FID = 第一帧渲染延迟 = performance.now() - entry.processingStart（在 entry.startTime 时）。
 *
 * @param onFid FID 采集回调
 * @returns 清理函数（取消观察）
 */
function collectFID(onFid: (fid: number) => void): () => void {
  if (typeof PerformanceObserver === 'undefined') {
    return () => {
      /* no-op：当前环境不支持 PerformanceObserver */
    };
  }

  let observer: PerformanceObserver | undefined;
  try {
    observer = new PerformanceObserver(entryList => {
      const entries = entryList.getEntries();
      const firstInput = entries[0];
      if (firstInput !== undefined && 'processingStart' in firstInput) {
        const fid = (firstInput as PerformanceEventTiming).processingStart - firstInput.startTime;
        if (Number.isFinite(fid) && fid >= 0) {
          onFid(Math.round(fid * 100) / 100);
        }
      }
    });
    observer.observe({ type: 'first-input', buffered: true });
  } catch {
    // 某些环境（如旧版 Safari）不支持 'first-input' 类型，静默降级
    return () => {
      /* no-op */
    };
  }

  return () => {
    observer?.disconnect();
  };
}

/**
 * 检查指标是否超过阈值，返回超标信息（未超标返回 null）。
 */
function checkThreshold(
  metric: 'lcp' | 'fcp' | 'cls' | 'inp' | 'ttfb' | 'fid',
  value: number,
  thresholds: WebVitalsThresholds,
): WebVitalsThresholdExceeded | null {
  switch (metric) {
    case 'lcp':
      return value > thresholds.lcp ? { metric, value, threshold: thresholds.lcp, errorCode: 'FE-PER-001' } : null;
    case 'fcp':
      return value > thresholds.fcp ? { metric, value, threshold: thresholds.fcp, errorCode: 'FE-PER-001' } : null;
    case 'cls':
      return value > thresholds.cls ? { metric, value, threshold: thresholds.cls, errorCode: 'FE-PER-001' } : null;
    case 'inp':
      return value > thresholds.inp ? { metric, value, threshold: thresholds.inp, errorCode: 'FE-PER-001' } : null;
    case 'ttfb':
      // TTFB 无独立阈值，使用 LCP 阈值的宽松倍数（TTI 对齐）
      return value > thresholds.tti ? { metric, value, threshold: thresholds.tti, errorCode: 'FE-PER-001' } : null;
    case 'fid':
      // FID 使用 INP 阈值（同属交互延迟指标）
      return value > thresholds.inp ? { metric, value, threshold: thresholds.inp, errorCode: 'FE-PER-001' } : null;
    default:
      return null;
  }
}

/**
 * 初始化 Web Vitals 采集。
 *
 * @param onReport 每次指标更新时的回调
 * @param thresholds 阈值配置（默认使用 DEFAULT_WEB_VITALS_THRESHOLDS）
 * @param onThresholdExceeded 阈值超标回调（可选，触发 FE-PER-001 上报）
 * @returns 清理函数（卸载所有观察者）
 *
 * @throws WebVitalsCollectionError 当 web-vitals 库内部抛异常时（对应 FE-PER-001 采集失败）
 */
export function initWebVitalsCollection(
  onReport: WebVitalsCallback,
  thresholds: WebVitalsThresholds = DEFAULT_WEB_VITALS_THRESHOLDS,
  onThresholdExceeded?: (exceeded: WebVitalsThresholdExceeded) => void,
): () => void {
  const internal: InternalReport = {
    timestamp: Date.now(),
  };

  const notify = (): void => {
    internal.timestamp = Date.now();
    onReport(snapshot(internal));
  };

  const handleMetric = (metric: 'lcp' | 'fcp' | 'cls' | 'inp' | 'ttfb', value: number): void => {
    internal[metric] = value;
    const exceeded = checkThreshold(metric, value, thresholds);
    if (exceeded !== null && onThresholdExceeded !== undefined) {
      onThresholdExceeded(exceeded);
    }
    notify();
  };

  const cleaners: Array<() => void> = [];

  try {
    const metricHandler = (key: 'lcp' | 'fcp' | 'cls' | 'inp' | 'ttfb') => (metric: Metric): void => {
      handleMetric(key, metric.value);
    };

    onLCP(metricHandler('lcp'));
    onCLS(metricHandler('cls'));
    onFCP(metricHandler('fcp'));
    onINP(metricHandler('inp'));
    onTTFB(metricHandler('ttfb'));
  } catch (error) {
    throw new WebVitalsCollectionError('web-vitals-init', error);
  }

  // FID 通过原生 PerformanceObserver 补采
  cleaners.push(
    collectFID(fid => {
      internal.fid = fid;
      const exceeded = checkThreshold('fid', fid, thresholds);
      if (exceeded !== null && onThresholdExceeded !== undefined) {
        onThresholdExceeded(exceeded);
      }
      notify();
    }),
  );

  return () => {
    for (const clean of cleaners) {
      clean();
    }
  };
}

/**
 * 同步采集一次当前页面性能快照（不含 INP/CLS 等需交互的指标）。
 * 用于性能 dashboard 初始化展示。
 */
export function captureWebVitalsSnapshot(): WebVitalsReport {
  const report: InternalReport = {
    timestamp: Date.now(),
  };

  if (typeof performance !== 'undefined' && typeof performance.getEntriesByType === 'function') {
    // 尝试从 navigation entries 读取 TTFB
    const navEntries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
    const nav = navEntries[0];
    if (nav !== undefined) {
      report.ttfb = Math.round(nav.responseStart - nav.requestStart);
      if (Number.isNaN(report.ttfb) || report.ttfb < 0) {
        report.ttfb = undefined;
      }
    }
  }

  return snapshot(report);
}

export { DEFAULT_WEB_VITALS_THRESHOLDS as WEB_VITALS_DEFAULT_THRESHOLDS };
