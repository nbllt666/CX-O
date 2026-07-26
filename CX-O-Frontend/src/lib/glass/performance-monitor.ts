/**
 * performance-monitor.ts — Liquid Glass 性能监控器
 * ============================================================================
 * 模块: 模块4 WebGL 玻璃层
 * 契约: D2 glass_tier_config.schema.json (performanceMonitor) +
 *        C1 frontend_glass_config.schema.json (gpuDegradeThresholds + performanceMonitor) +
 *        I1 frontend_glass.pyi (PerformanceMonitor class)
 * 用途: 实时采集帧率，连续 30 帧 drop > 10ms 时自动降级 tier
 *
 * 自动降级阈值（D2 performanceMonitor.autoDowngradeThreshold + C1 gpuDegradeThresholds）:
 *   - consecutiveFrames: 30（连续帧数阈值）
 *   - dropMs: 10（帧 drop 毫秒阈值）
 *   - gpuMemoryLimit: 48 MB（双 FBO 显存上限）
 *   - drawCallLimit: desktop 20 / mobile 8
 *
 * 降级路径（D2 exceptionContract degradeBehaviorRules 1, 强制顺序禁止跳级）:
 *   Tier 1 → Tier 2 → Tier 3 → Tier 4，每级停留至少 30s 再尝试升级
 *
 * 错误码归属（E1 crossModuleDisambiguationRules 2）:
 *   - FE-GLA-004: GlassRenderer 执行层降级失败（本模块不抛，由 GlassRenderer 抛）
 *   - FE-PER-002: WebGL 性能塌陷（PerformanceMonitor 检测到连续 30 帧超预算）
 *   - FE-PER-003: 自动降级失败（监控触发层，PerformanceMonitor 触发降级时 hook 抛异常）
 * ============================================================================
 */

// ============================================================================
// 类型定义（I1 TypedDict 对应）
// ============================================================================

/**
 * 性能监控指标（I1 PerformanceMetrics, merged.md §7.5）。
 */
export interface PerformanceMetrics {
  /** 当前帧率（fps） */
  fps: number;
  /** 单帧耗时（ms） */
  frameTimeMs: number;
  /** draw call 数 */
  drawCalls: number;
  /** 连续掉帧数 */
  droppedFrames: number;
  /** GPU 显存占用（MB） */
  gpuMemoryMB: number;
}

/**
 * 掉帧回调签名（I1 onFrameDrop callback）。
 * @param droppedFrames 连续掉帧数
 * @param frameTimeMs 单帧耗时（ms）
 */
export type FrameDropCallback = (droppedFrames: number, frameTimeMs: number) => void;

// ============================================================================
// 常量定义（C1 配置驱动，禁止硬编码 magic number）
// ============================================================================

/** 连续帧数阈值（C1 gpuDegradeThresholds.frameDropThreshold.consecutiveFrames = 30） */
const FRAME_DROP_CONSECUTIVE_THRESHOLD = 30;

/** 帧 drop 毫秒阈值（C1 gpuDegradeThresholds.frameDropThreshold.dropMs = 10） */
const FRAME_DROP_MS_THRESHOLD = 10;

/** GPU 显存上限 MB（C1 gpuDegradeThresholds.gpuMemoryLimit.desktop.mb = 48） */
const GPU_MEMORY_LIMIT_MB = 48;

/** 桌面端 draw call 上限（C1 gpuDegradeThresholds.drawCallLimit.desktop = 20） */
const DRAW_CALL_LIMIT_DESKTOP = 20;

/** 移动端 draw call 上限（C1 gpuDegradeThresholds.drawCallLimit.mobile = 8） */
const DRAW_CALL_LIMIT_MOBILE = 8;

/** 桌面端单帧预算（D2 glass.css --glass-frame-budget-desktop-ms = 12ms） */
const DESKTOP_FRAME_BUDGET_MS = 12;

/** 移动端单帧预算（D2 glass.css --glass-frame-budget-mobile-ms = 20ms） */
const MOBILE_FRAME_BUDGET_MS = 20;

/** 降级后停留时间（ms，D2 degradeBehaviorRules 1: 每级停留至少 30s） */
const DOWNGRADE_COOLDOWN_MS = 30_000;

// ============================================================================
// PerformanceMonitor 类（I1 签名匹配）
// ============================================================================

/**
 * 性能监控器（I1 PerformanceMonitor, merged.md §7.5 + §7.6）。
 *
 * 实时采集帧率，连续 30 帧 drop > 10ms 时自动降级 tier。
 * 生产环境接入 Web Vitals，WebGL tier 切换 / GPU 上下文丢失 / 降级事件全部埋点。
 */
export class PerformanceMonitor {
  /** 是否正在监控 */
  private running = false;

  /** requestAnimationFrame handle */
  private rafHandle: number | null = null;

  /** 上一帧时间戳（ms） */
  private lastFrameTime = 0;

  /** 连续掉帧计数 */
  private consecutiveDroppedFrames = 0;

  /** 当前 draw call 数（由 GlassRenderer 上报） */
  private currentDrawCalls = 0;

  /** 当前 GPU 显存占用 MB（由 GPUMemoryManager 上报） */
  private currentGpuMemoryMB = 0;

  /** 是否为移动端 */
  private isMobile: boolean;

  /** 掉帧回调列表 */
  private frameDropCallbacks: FrameDropCallback[] = [];

  /** 降级回调（触发降级时调用） */
  private degradeCallback: ((reason: string) => void) | null = null;

  /** 上次降级时间戳（ms，用于 cooldown） */
  private lastDegradeTime = 0;

  /** 最近一帧的指标缓存 */
  private lastMetrics: PerformanceMetrics = {
    fps: 60,
    frameTimeMs: 16.67,
    drawCalls: 0,
    droppedFrames: 0,
    gpuMemoryMB: 0,
  };

  constructor(isMobile = false) {
    this.isMobile = isMobile;
  }

  /**
   * 启动性能监控（I1 start）。
   *
   * 注册 requestAnimationFrame 回调，开始采集帧率与 draw call。
   *
   * @throws Error 监控已启动时重复调用抛出（防止重复注册 rAF）
   */
  start(): void {
    if (this.running) {
      throw new Error('PerformanceMonitor already started: duplicate start() call detected');
    }
    this.running = true;
    this.lastFrameTime = performance.now();
    this.consecutiveDroppedFrames = 0;
    this.rafHandle = requestAnimationFrame(this.tick);
  }

  /**
   * 停止性能监控（I1 stop）。
   *
   * 取消 requestAnimationFrame，释放采集资源。
   */
  stop(): void {
    this.running = false;
    if (this.rafHandle !== null) {
      cancelAnimationFrame(this.rafHandle);
      this.rafHandle = null;
    }
  }

  /**
   * 注册掉帧回调（I1 onFrameDrop）。
   *
   * @param callback 掉帧回调，签名 (droppedFrames, frameTimeMs) => void
   *   连续掉帧数达到阈值（默认 30）时触发
   */
  onFrameDrop(callback: FrameDropCallback): void {
    this.frameDropCallbacks.push(callback);
  }

  /**
   * 注册降级回调（供 useGlassTier 使用）。
   *
   * @param callback 降级回调，签名 (reason: string) => void
   */
  onDegrade(callback: (reason: string) => void): void {
    this.degradeCallback = callback;
  }

  /**
   * 上报当前 draw call 数（由 GlassRenderer 调用）。
   *
   * @param count draw call 数
   */
  reportDrawCalls(count: number): void {
    this.currentDrawCalls = count;
  }

  /**
   * 上报当前 GPU 显存占用（由 GPUMemoryManager 调用）。
   *
   * @param mb GPU 显存占用 MB
   */
  reportGpuMemory(mb: number): void {
    this.currentGpuMemoryMB = mb;
  }

  /**
   * 获取当前性能指标（I1 getMetrics）。
   *
   * @returns PerformanceMetrics 含 fps / frameTimeMs / drawCalls / droppedFrames / gpuMemoryMB
   */
  getMetrics(): PerformanceMetrics {
    return { ...this.lastMetrics };
  }

  /**
   * 判定是否应触发 tier 降级（I1 shouldDegrade）。
   *
   * 判定逻辑:
   *   - 连续 30 帧 drop > 10ms → 降级（FE-PER-002 WebGL 性能塌陷）
   *   - GPU 显存超 48MB → 降级
   *   - draw call > 20（桌面）/ 8（移动）→ 降级
   *   - 移动端（< md 断点）→ 强制 Tier 3（由 tier-detector 处理，此处不重复）
   *
   * @returns [shouldDegrade, reason] 元组
   */
  shouldDegrade(): [boolean, string] {
    const frameBudget = this.isMobile ? MOBILE_FRAME_BUDGET_MS : DESKTOP_FRAME_BUDGET_MS;
    const drawCallLimit = this.isMobile ? DRAW_CALL_LIMIT_MOBILE : DRAW_CALL_LIMIT_DESKTOP;

    // 连续 30 帧 drop > 10ms → 降级（D2 performanceMonitor.autoDowngradeThreshold）
    if (this.consecutiveDroppedFrames >= FRAME_DROP_CONSECUTIVE_THRESHOLD) {
      return [true, `PERFORMANCE_DROP: ${this.consecutiveDroppedFrames} consecutive frames exceeded ${FRAME_DROP_MS_THRESHOLD}ms drop`];
    }

    // GPU 显存超 48MB → 降级（C1 gpuDegradeThresholds.gpuMemoryLimit）
    if (this.currentGpuMemoryMB > GPU_MEMORY_LIMIT_MB) {
      return [true, `GPU_MEMORY_EXCEEDED: ${this.currentGpuMemoryMB.toFixed(2)}MB > ${GPU_MEMORY_LIMIT_MB}MB limit`];
    }

    // draw call 超限 → 降级（C1 gpuDegradeThresholds.drawCallLimit）
    if (this.currentDrawCalls > drawCallLimit) {
      return [true, `DRAW_CALL_EXCEEDED: ${this.currentDrawCalls} > ${drawCallLimit} limit`];
    }

    // 单帧耗时超预算（补充检测，frameBudget + dropThreshold）
    if (this.lastMetrics.frameTimeMs > frameBudget + FRAME_DROP_MS_THRESHOLD) {
      return [true, `FRAME_TIME_EXCEEDED: ${this.lastMetrics.frameTimeMs.toFixed(2)}ms > ${frameBudget + FRAME_DROP_MS_THRESHOLD}ms budget`];
    }

    return [false, ''];
  }

  /**
   * 内部 rAF tick 回调：采集帧率，检测掉帧，触发降级。
   */
  private tick = (now: number): void => {
    if (!this.running) return;

    const frameTimeMs = now - this.lastFrameTime;
    this.lastFrameTime = now;

    const fps = frameTimeMs > 0 ? 1000 / frameTimeMs : 60;
    const frameBudget = this.isMobile ? MOBILE_FRAME_BUDGET_MS : DESKTOP_FRAME_BUDGET_MS;

    // 检测掉帧：单帧耗时 > 帧预算 + dropThreshold
    const isDropped = frameTimeMs > frameBudget + FRAME_DROP_MS_THRESHOLD;

    if (isDropped) {
      this.consecutiveDroppedFrames++;
    } else {
      // 重置连续掉帧计数
      this.consecutiveDroppedFrames = 0;
    }

    // 更新指标缓存
    this.lastMetrics = {
      fps: Math.round(fps * 100) / 100,
      frameTimeMs: Math.round(frameTimeMs * 100) / 100,
      drawCalls: this.currentDrawCalls,
      droppedFrames: this.consecutiveDroppedFrames,
      gpuMemoryMB: this.currentGpuMemoryMB,
    };

    // 连续掉帧达到阈值时触发回调
    if (this.consecutiveDroppedFrames >= FRAME_DROP_CONSECUTIVE_THRESHOLD) {
      for (const cb of this.frameDropCallbacks) {
        cb(this.consecutiveDroppedFrames, frameTimeMs);
      }
    }

    // 检测是否应降级（含 cooldown，每级停留至少 30s）
    const cooldownElapsed = now - this.lastDegradeTime >= DOWNGRADE_COOLDOWN_MS;
    if (cooldownElapsed) {
      const [shouldDegrade, reason] = this.shouldDegrade();
      if (shouldDegrade && this.degradeCallback) {
        this.lastDegradeTime = now;
        this.degradeCallback(reason);
      }
    }

    // 继续下一帧
    this.rafHandle = requestAnimationFrame(this.tick);
  };
}
