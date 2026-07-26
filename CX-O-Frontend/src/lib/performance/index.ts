/**
 * @file 性能监控模块统一导出
 *
 * 模块9c 响应式性能层 - 性能监控子模块
 *
 * 对外导出：
 * - Web Vitals 采集（web-vitals.ts）
 * - Lighthouse CI 配置（lighthouse-ci.ts）
 * - Bundle Budget 监控（bundle-budget.ts）
 * - 统一性能监控器（performance-monitor.ts）
 * - React Hook（use-performance.ts）
 * - PER 错误码常量（E1 §FE-PER-001~004）
 *
 * 契约对齐：
 * - D7 performance_budget.schema.json
 * - C4 frontend_performance_config.schema.json
 * - E1 frontend_error_codes.schema.json（PER 段 4 错误码）
 *
 * 跨模块导入约束：本模块独立，仅依赖 web-vitals 第三方库 + react，
 * 禁止 import 模块1-8 内部实现。
 */

// ===== Web Vitals 采集 =====
export {
  initWebVitalsCollection,
  captureWebVitalsSnapshot,
  WEB_VITALS_DEFAULT_THRESHOLDS,
  DEFAULT_WEB_VITALS_THRESHOLDS,
  WebVitalsCollectionError,
  type WebVitalsThresholds,
  type WebVitalsReport,
  type WebVitalsCallback,
  type WebVitalsThresholdExceeded,
} from './web-vitals';

// ===== Lighthouse CI =====
export {
  DEFAULT_LIGHTHOUSE_THRESHOLDS,
  DEFAULT_LIGHTHOUSE_FLOOR_SCORE,
  DEFAULT_LIGHTHOUSE_CI_CONFIG,
  evaluateLighthouseResult,
  generateLighthouseConfig,
  serializeLighthouseAlert,
  LighthouseCIBlockedError,
  type LighthouseThresholds,
  type LighthouseFloorScore,
  type LighthouseCIConfig,
  type LighthouseResult,
  type LighthouseEvaluation,
  type LighthouseAssertionFailure,
} from './lighthouse-ci';

// ===== Bundle Budget =====
export {
  DEFAULT_BUNDLE_BUDGET_LIMITS,
  scanDistChunks,
  summarizeBundleReport,
  evaluateBundleBudget,
  readFromViteManifest,
  runBundleBudgetCheck,
  BundleBudgetExceededError,
  type BundleBudgetLimits,
  type BundleChunkMetric,
  type BundleBudgetReport,
  type BundleBudgetExceeded,
} from './bundle-budget';

// ===== 统一性能监控器 =====
export {
  PerformanceMonitor,
  createPerformanceMonitor,
  DEFAULT_WEBGL_BUDGET,
  DEFAULT_AUTO_DEGRADE_CONFIG,
  DEFAULT_RUNTIME_MONITORING,
  DEFAULT_PERFORMANCE_CONFIG,
  WebGLPerformanceCollapseError,
  AutoDegradeFailureError,
  type WebGLPerformanceBudget,
  type AutoDegradeConfig,
  type RuntimeMonitoringConfig,
  type PerformanceMonitorConfig,
  type PerformanceSnapshot,
  type PerformanceAlert,
  type WebGLCollapseEvent,
  type AutoDegradeFailureEvent,
} from './performance-monitor';

// ===== React Hook =====
export {
  usePerformance,
  usePerformanceAlerts,
  usePerformanceSnapshot,
  usePerformanceLifecycle,
  type UsePerformanceResult,
  type UsePerformanceAlertsResult,
  type UsePerformanceSnapshotResult,
  type UsePerformanceLifecycleResult,
} from './use-performance';

/**
 * E1 §PER 模块错误码常量（4 个）。
 *
 * 错误码定义来源：E1 frontend_error_codes.schema.json §errorCodes（PER 段）。
 * 以下为冻结契约的只读镜像，业务代码禁止硬编码错误码字符串，必须引用此常量。
 *
 * 注意：任务描述与 E1 契约在错误码含义映射上存在差异（详见各错误码注释）。
 * 以 E1 冻结契约为准。若需调整映射，须走 s0601 契约变更流程。
 */
export const PERFORMANCE_ERROR_CODES = {
  /**
   * FE-PER-001：性能阈值超标。
   * E1 定义：Web Vitals 上报值超过 C4 webVitalsThresholds 阈值。
   * 本模块用法：Web Vitals 采集失败 + 阈值超标 + bundle 体积超预算均归入此码。
   * severity: warning（不阻断 UI，上报 dashboard）。
   */
  FE_PER_001: 'FE-PER-001',

  /**
   * FE-PER-002：WebGL 性能塌陷。
   * E1 定义：连续 30 帧单帧耗时 > desktopFrameBudget(12ms) + frameDropThreshold(10ms)
   *          或 mobileFrameBudget(20ms) + frameDropThreshold(10ms)。
   * 本模块用法：PerformanceMonitor 实时采集帧率，连续 30 帧超预算触发。
   * severity: error（立即触发 tier 降级）。
   * 与模块4 共享：GlassRenderer 执行降级，本模块负责全局上报。
   */
  FE_PER_002: 'FE-PER-002',

  /**
   * FE-PER-003：自动降级失败（监控触发层）。
   * E1 定义：autoDegradeEnabled=true 但 PerformanceMonitor 触发降级时
   *          useGlassTier() hook 抛异常或 tier 切换回调未注册。
   * 本模块用法：PerformanceMonitor.triggerAutoDegrade() 执行降级回调失败时抛出。
   * severity: error（强制降级到 Tier 4 兜底）。
   *
   * 注意：任务描述将此码映射为"Lighthouse 评分低于阈值"，但 E1 中此码为"自动降级失败"。
   * 以 E1 冻结契约为准。Lighthouse 评分低于阈值使用 FE-PER-004。
   */
  FE_PER_003: 'FE-PER-003',

  /**
   * FE-PER-004：Lighthouse CI 阻断。
   * E1 定义：lighthouseBlockingEnabled=true 且 PR 的 Lighthouse 首屏性能分数 < lighthouseMinScore(80)。
   * 本模块用法：Lighthouse CI 评估未达标时抛出。
   * severity: error（CI 阻断 PR 合并）。
   *
   * 注意：任务描述将此码映射为"bundle 体积超预算"，但 E1 中此码为"Lighthouse CI 阻断"。
   * 以 E1 冻结契约为准。bundle 体积超预算使用 FE-PER-001。
   */
  FE_PER_004: 'FE-PER-004',
} as const;

/**
 * 性能监控模块元信息。
 */
export const PERFORMANCE_MODULE_INFO = {
  /** 模块编号 */
  module: '模块9c',
  /** 模块中文名 */
  name: '性能监控',
  /** 契约版本 */
  contractVersion: '1.0.0',
  /** 对齐契约 */
  contracts: [
    'D7 performance_budget.schema.json',
    'C4 frontend_performance_config.schema.json',
    'E1 frontend_error_codes.schema.json',
  ],
  /** 错误码清单 */
  errorCodes: Object.values(PERFORMANCE_ERROR_CODES),
} as const;
