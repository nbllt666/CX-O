/**
 * @file 统一性能监控器
 *
 * 职责：聚合 Web Vitals 采集 + Lighthouse CI 评估 + Bundle Budget 校验三类性能数据，
 * 提供统一告警上报接口与 WebGL 帧率监控（连续 30 帧超预算触发自动降级）。
 *
 * 契约对齐：
 * - D7 performance_budget.schema.json §runtimeMonitoring（RM-01~04 + autoDowngrade）
 * - C4 frontend_performance_config.schema.json §runtimeMonitoring（autoDegradeEnabled/frameDropThreshold）
 * - C4 §webglPerformanceBudget（desktopFrameBudget=12 / mobileFrameBudget=20）
 * - E1 §FE-PER-001（性能阈值超标）/ FE-PER-002（WebGL 性能塌陷）/ FE-PER-003（自动降级失败）
 *
 * 跨模块导入约束：仅 import 本模块内部（web-vitals.ts / lighthouse-ci.ts / bundle-budget.ts）+ react，
 * 禁止 import 模块1-8 内部实现（性能监控独立）。
 */

import {
  initWebVitalsCollection,
  captureWebVitalsSnapshot,
  WEB_VITALS_DEFAULT_THRESHOLDS,
  type WebVitalsThresholds,
  type WebVitalsReport,
  type WebVitalsThresholdExceeded,
} from './web-vitals';
import {
  DEFAULT_LIGHTHOUSE_CI_CONFIG,
  evaluateLighthouseResult,
  type LighthouseCIConfig,
  type LighthouseResult,
  type LighthouseEvaluation,
} from './lighthouse-ci';
import {
  DEFAULT_BUNDLE_BUDGET_LIMITS,
  summarizeBundleReport,
  evaluateBundleBudget,
  type BundleBudgetLimits,
  type BundleBudgetReport,
  type BundleBudgetExceeded,
} from './bundle-budget';

/**
 * WebGL 性能预算（与 C4 §webglPerformanceBudget / D7 §webglPerformance 对齐）。
 */
export interface WebGLPerformanceBudget {
  /** 桌面端单帧预算（ms），默认 12 */
  readonly desktopFrameBudget: number;
  /** 移动端单帧预算（ms），默认 20 */
  readonly mobileFrameBudget: number;
  /** 桌面端 draw call 上限，默认 20 */
  readonly desktopDrawCallLimit: number;
  /** 移动端 draw call 上限，默认 8 */
  readonly mobileDrawCallLimit: number;
  /** GPU 显存上限（MB），默认 48 */
  readonly gpuMemoryLimit: number;
}

/**
 * 自动降级配置（与 C4 §runtimeMonitoring / D7 §runtimeMonitoring.autoDowngrade 对齐）。
 */
export interface AutoDegradeConfig {
  /** 是否启用自动降级，默认 true */
  readonly enabled: boolean;
  /** 连续帧数阈值，默认 30 */
  readonly consecutiveFrames: number;
  /** 帧 drop 阈值（ms），默认 10 */
  readonly frameDropThreshold: number;
}

/**
 * 运行时监控配置（与 C4 §runtimeMonitoring 对齐）。
 */
export interface RuntimeMonitoringConfig {
  /** Web Vitals 上报，默认 true */
  readonly webVitalsReporting: boolean;
  /** WebGL tier 切换埋点，默认 true */
  readonly webglTierSwitchTracking: boolean;
  /** GPU 上下文丢失埋点，默认 true */
  readonly gpuContextLossTracking: boolean;
  /** 性能 dashboard 启用，默认 true */
  readonly performanceDashboardEnabled: boolean;
  /** 自动降级配置 */
  readonly autoDegrade: AutoDegradeConfig;
}

/**
 * 统一性能监控配置（聚合三类监控 + WebGL + 运行时）。
 */
export interface PerformanceMonitorConfig {
  readonly webVitalsThresholds: WebVitalsThresholds;
  readonly lighthouse: LighthouseCIConfig;
  readonly bundleBudget: BundleBudgetLimits;
  readonly webglBudget: WebGLPerformanceBudget;
  readonly runtime: RuntimeMonitoringConfig;
}

/**
 * 默认 WebGL 性能预算（C4/D7 默认值）。
 */
export const DEFAULT_WEBGL_BUDGET: WebGLPerformanceBudget = {
  desktopFrameBudget: 12,
  mobileFrameBudget: 20,
  desktopDrawCallLimit: 20,
  mobileDrawCallLimit: 8,
  gpuMemoryLimit: 48,
};

/**
 * 默认自动降级配置（D7 §runtimeMonitoring.autoDowngrade）。
 */
export const DEFAULT_AUTO_DEGRADE_CONFIG: AutoDegradeConfig = {
  enabled: true,
  consecutiveFrames: 30,
  frameDropThreshold: 10,
};

/**
 * 默认运行时监控配置（C4 §runtimeMonitoring）。
 */
export const DEFAULT_RUNTIME_MONITORING: RuntimeMonitoringConfig = {
  webVitalsReporting: true,
  webglTierSwitchTracking: true,
  gpuContextLossTracking: true,
  performanceDashboardEnabled: true,
  autoDegrade: DEFAULT_AUTO_DEGRADE_CONFIG,
};

/**
 * 默认性能监控配置。
 */
export const DEFAULT_PERFORMANCE_CONFIG: PerformanceMonitorConfig = {
  webVitalsThresholds: WEB_VITALS_DEFAULT_THRESHOLDS,
  lighthouse: DEFAULT_LIGHTHOUSE_CI_CONFIG,
  bundleBudget: DEFAULT_BUNDLE_BUDGET_LIMITS,
  webglBudget: DEFAULT_WEBGL_BUDGET,
  runtime: DEFAULT_RUNTIME_MONITORING,
};

/**
 * 统一性能告警事件。
 */
export type PerformanceAlert =
  | { readonly kind: 'web-vitals-threshold'; readonly data: WebVitalsThresholdExceeded }
  | { readonly kind: 'lighthouse-failed'; readonly data: LighthouseEvaluation }
  | { readonly kind: 'bundle-budget-exceeded'; readonly data: readonly BundleBudgetExceeded[] }
  | { readonly kind: 'webgl-performance-collapse'; readonly data: WebGLCollapseEvent }
  | { readonly kind: 'auto-degrade-failed'; readonly data: AutoDegradeFailureEvent };

/**
 * WebGL 性能塌陷事件（对应 E1 §FE-PER-002）。
 */
export interface WebGLCollapseEvent {
  /** 连续超预算帧数 */
  readonly consecutiveFrames: number;
  /** 单帧最大耗时（ms） */
  readonly maxFrameDuration: number;
  /** 预算阈值（ms） */
  readonly budgetThreshold: number;
  /** 是否移动端 */
  readonly isMobile: boolean;
  readonly errorCode: 'FE-PER-002';
}

/**
 * 自动降级失败事件（对应 E1 §FE-PER-003）。
 */
export interface AutoDegradeFailureEvent {
  /** 失败原因 */
  readonly reason: string;
  /** 原始异常 */
  readonly cause?: unknown;
  readonly errorCode: 'FE-PER-003';
}

/**
 * 性能快照（聚合三类数据）。
 */
export interface PerformanceSnapshot {
  readonly webVitals: WebVitalsReport;
  readonly lighthouse: LighthouseEvaluation | null;
  readonly bundle: BundleBudgetReport | null;
  readonly timestamp: number;
}

/**
 * WebGL 性能塌陷错误。对应 E1 §FE-PER-002。
 */
export class WebGLPerformanceCollapseError extends Error {
  public readonly errorCode = 'FE-PER-002' as const;
  public readonly event: WebGLCollapseEvent;

  constructor(event: WebGLCollapseEvent) {
    super(
      `[FE-PER-002] WebGL 性能塌陷：连续 ${event.consecutiveFrames} 帧超预算 ` +
        `(max=${event.maxFrameDuration}ms > ${event.budgetThreshold}ms, mobile=${event.isMobile})`,
    );
    this.name = 'WebGLPerformanceCollapseError';
    this.event = event;
  }
}

/**
 * 自动降级失败错误。对应 E1 §FE-PER-003。
 */
export class AutoDegradeFailureError extends Error {
  public readonly errorCode = 'FE-PER-003' as const;
  public readonly event: AutoDegradeFailureEvent;

  constructor(event: AutoDegradeFailureEvent) {
    super(`[FE-PER-003] 自动降级失败（监控触发层）- ${event.reason}`);
    this.name = 'AutoDegradeFailureError';
    this.event = event;
  }
}

/**
 * 帧率采样记录。
 */
interface FrameSample {
  readonly duration: number;
  readonly timestamp: number;
}

/**
 * 统一性能监控器。
 *
 * 设计要点：
 * - 单例模式（getInstance），全局唯一监控实例
 * - 配置驱动（init 时注入 PerformanceMonitorConfig）
 * - 事件驱动（通过 onAlert 订阅告警，不阻塞主线程）
 * - WebGL 帧率监控通过 requestAnimationFrame 循环
 * - 连续 N 帧超预算 -> FE-PER-002，触发降级回调
 */
export class PerformanceMonitor {
  private static instance: PerformanceMonitor | null = null;

  private config: PerformanceMonitorConfig;
  private webVitalsCleaner: (() => void) | null = null;
  private rafId: number | null = null;
  private frameSamples: FrameSample[] = [];
  private lastFrameTime: number | null = null;
  private collapseTriggered = false;
  private alertListeners: Array<(alert: PerformanceAlert) => void> = [];
  private latestWebVitals: WebVitalsReport;
  private latestLighthouse: LighthouseEvaluation | null = null;
  private latestBundle: BundleBudgetReport | null = null;
  private degradeCallback: (() => void) | null = null;

  private constructor(config: PerformanceMonitorConfig) {
    this.config = config;
    this.latestWebVitals = captureWebVitalsSnapshot();
  }

  /**
   * 获取单例实例。
   */
  static getInstance(config: PerformanceMonitorConfig = DEFAULT_PERFORMANCE_CONFIG): PerformanceMonitor {
    if (PerformanceMonitor.instance === null) {
      PerformanceMonitor.instance = new PerformanceMonitor(config);
    }
    return PerformanceMonitor.instance;
  }

  /**
   * 重置单例（仅用于测试）。
   */
  static resetInstance(): void {
    if (PerformanceMonitor.instance !== null) {
      PerformanceMonitor.instance.destroy();
      PerformanceMonitor.instance = null;
    }
  }

  /**
   * 初始化监控（启动 Web Vitals 采集 + WebGL 帧率监控）。
   *
   * @param onAlert 性能告警回调
   */
  init(onAlert?: (alert: PerformanceAlert) => void): void {
    if (onAlert !== undefined) {
      this.alertListeners.push(onAlert);
    }

    // 启动 Web Vitals 采集
    if (this.config.runtime.webVitalsReporting) {
      this.webVitalsCleaner = initWebVitalsCollection(
        report => {
          this.latestWebVitals = report;
        },
        this.config.webVitalsThresholds,
        exceeded => {
          this.emitAlert({ kind: 'web-vitals-threshold', data: exceeded });
        },
      );
    }

    // 启动 WebGL 帧率监控（仅浏览器环境）
    if (
      this.config.runtime.autoDegrade.enabled &&
      typeof window !== 'undefined' &&
      typeof requestAnimationFrame === 'function'
    ) {
      this.startFrameMonitoring();
    }
  }

  /**
   * 启动 WebGL 帧率监控循环。
   */
  private startFrameMonitoring(): void {
    this.lastFrameTime = performance.now();

    const loop = (): void => {
      const now = performance.now();
      const duration = now - (this.lastFrameTime ?? now);
      this.lastFrameTime = now;

      if (duration > 0) {
        this.frameSamples.push({ duration, timestamp: now });

        // 保留最近 consecutiveFrames 帧
        const maxSamples = this.config.runtime.autoDegrade.consecutiveFrames;
        if (this.frameSamples.length > maxSamples) {
          this.frameSamples.shift();
        }

        this.checkWebGLCollapse();
      }

      this.rafId = requestAnimationFrame(loop);
    };

    this.rafId = requestAnimationFrame(loop);
  }

  /**
   * 检查是否触发 WebGL 性能塌陷（连续 N 帧超预算）。
   */
  private checkWebGLCollapse(): void {
    if (this.collapseTriggered) {
      return;
    }

    const samples = this.frameSamples;
    const required = this.config.runtime.autoDegrade.consecutiveFrames;

    if (samples.length < required) {
      return;
    }

    const isMobile = this.detectMobile();
    const budget = isMobile
      ? this.config.webglBudget.mobileFrameBudget
      : this.config.webglBudget.desktopFrameBudget;
    const threshold = budget + this.config.runtime.autoDegrade.frameDropThreshold;

    const recentFrames = samples.slice(-required);
    const allExceeded = recentFrames.every(s => s.duration > threshold);

    if (allExceeded) {
      this.collapseTriggered = true;
      const maxDuration = Math.max(...recentFrames.map(s => s.duration));

      const event: WebGLCollapseEvent = {
        consecutiveFrames: required,
        maxFrameDuration: Math.round(maxDuration * 100) / 100,
        budgetThreshold: threshold,
        isMobile,
        errorCode: 'FE-PER-002',
      };

      this.emitAlert({ kind: 'webgl-performance-collapse', data: event });
      this.triggerAutoDegrade();
    }
  }

  /**
   * 检测当前是否移动端（简化实现，基于 matchMedia）。
   */
  private detectMobile(): boolean {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return false;
    }
    return window.matchMedia('(max-width: 767px)').matches;
  }

  /**
   * 触发自动降级。
   * 降级回调失败时抛出 FE-PER-003。
   */
  private triggerAutoDegrade(): void {
    if (this.degradeCallback === null) {
      // 未注册降级回调，属于自动降级失败
      const event: AutoDegradeFailureEvent = {
        reason: '降级回调未注册（useGlassTier tier 切换回调未设置）',
        errorCode: 'FE-PER-003',
      };
      this.emitAlert({ kind: 'auto-degrade-failed', data: event });
      return;
    }

    try {
      this.degradeCallback();
    } catch (error) {
      const event: AutoDegradeFailureEvent = {
        reason: '降级回调执行抛异常',
        cause: error,
        errorCode: 'FE-PER-003',
      };
      this.emitAlert({ kind: 'auto-degrade-failed', data: event });
    }
  }

  /**
   * 注册降级回调（由模块4 GlassRenderer 注入 tier 切换函数）。
   */
  registerDegradeCallback(callback: () => void): void {
    this.degradeCallback = callback;
  }

  /**
   * 订阅性能告警。
   *
   * @returns 取消订阅函数
   */
  onAlert(listener: (alert: PerformanceAlert) => void): () => void {
    this.alertListeners.push(listener);
    return () => {
      const idx = this.alertListeners.indexOf(listener);
      if (idx >= 0) {
        this.alertListeners.splice(idx, 1);
      }
    };
  }

  /**
   * 派发告警事件。
   */
  private emitAlert(alert: PerformanceAlert): void {
    for (const listener of [...this.alertListeners]) {
      try {
        listener(alert);
      } catch {
        // 告警监听器异常不应影响监控主循环
      }
    }
  }

  /**
   * 注入 Lighthouse 采集结果并评估。
   */
  reportLighthouse(result: LighthouseResult): LighthouseEvaluation {
    const evaluation = evaluateLighthouseResult(result, this.config.lighthouse);
    this.latestLighthouse = evaluation;

    if (!evaluation.passed) {
      this.emitAlert({ kind: 'lighthouse-failed', data: evaluation });
    }

    return evaluation;
  }

  /**
   * 注入 bundle 体积报告并评估。
   */
  reportBundle(chunks: ReadonlyArray<{ filename: string; category: 'main' | 'lazy' | 'glass-shader' | 'motion' | 'css' | 'other'; rawBytes: number; gzipBytes: number }>): readonly BundleBudgetExceeded[] {
    const report = summarizeBundleReport(chunks);
    this.latestBundle = report;
    const exceeded = evaluateBundleBudget(report, this.config.bundleBudget);

    if (exceeded.length > 0) {
      this.emitAlert({ kind: 'bundle-budget-exceeded', data: exceeded });
    }

    return exceeded;
  }

  /**
   * 获取当前性能快照。
   */
  getSnapshot(): PerformanceSnapshot {
    return {
      webVitals: this.latestWebVitals,
      lighthouse: this.latestLighthouse,
      bundle: this.latestBundle,
      timestamp: Date.now(),
    };
  }

  /**
   * 获取当前配置。
   */
  getConfig(): PerformanceMonitorConfig {
    return this.config;
  }

  /**
   * 更新配置（运行时热更新阈值）。
   */
  updateConfig(config: Partial<PerformanceMonitorConfig>): void {
    this.config = { ...this.config, ...config };
  }

  /**
   * 重置 WebGL 塌陷状态（降级恢复后调用）。
   */
  resetCollapseState(): void {
    this.collapseTriggered = false;
    this.frameSamples = [];
  }

  /**
   * 销毁监控器（清理所有观察者与定时器）。
   */
  destroy(): void {
    if (this.webVitalsCleaner !== null) {
      this.webVitalsCleaner();
      this.webVitalsCleaner = null;
    }

    if (this.rafId !== null && typeof cancelAnimationFrame === 'function') {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }

    this.alertListeners = [];
    this.frameSamples = [];
    this.degradeCallback = null;
  }
}

/**
 * 创建性能监控器单例（便捷工厂）。
 */
export function createPerformanceMonitor(
  config: PerformanceMonitorConfig = DEFAULT_PERFORMANCE_CONFIG,
): PerformanceMonitor {
  return PerformanceMonitor.getInstance(config);
}
