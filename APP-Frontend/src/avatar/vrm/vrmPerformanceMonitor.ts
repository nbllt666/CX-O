/**
 * VRM 性能监控：FPS 统计与降级/恢复状态机。
 *
 * 行为口径对齐 CX-O-Frontend components/business/vrm/vrm-performance-monitor.ts：
 * - 每帧累计帧数，累计满 1 秒结算一次 currentFPS
 * - 未降级：currentFPS 连续 2 秒低于 30 时触发降级（degraded=true）
 * - 已降级：currentFPS 连续 2 秒高于 50 时触发恢复（degraded=false）
 * - 升降级均需连续满足阈值才切换，避免边界抖动
 */
export class PerformanceMonitor {
  private frameCount = 0;
  private lastTime = performance.now();
  public currentFPS = 60;
  public degraded = false;
  private lowFpsTimer = 0;
  private recoveredTimer = 0;
  private listeners = new Set<(degraded: boolean) => void>();

  /**
   * 每帧调用。时间累计采用 performance.now() 差值（与 lastTime 初始值口径一致），
   * 达到 1 秒时结算 currentFPS 并清零，随后按当前状态判定升降级。
   */
  update(_dt: number): void {
    this.frameCount++;
    const now = performance.now();
    if (now - this.lastTime < 1000) {
      return;
    }

    this.currentFPS = this.frameCount;
    this.lastTime = now;
    this.frameCount = 0;

    if (this.degraded) {
      if (this.currentFPS > 50) {
        this.recoveredTimer += 1;
        if (this.recoveredTimer >= 2) {
          this.setDegraded(false);
        }
      } else {
        this.recoveredTimer = 0;
      }
    } else {
      if (this.currentFPS < 30) {
        this.lowFpsTimer += 1;
        if (this.lowFpsTimer >= 2) {
          this.setDegraded(true);
        }
      } else {
        this.lowFpsTimer = 0;
      }
    }
  }

  private setDegraded(degraded: boolean): void {
    this.degraded = degraded;
    for (const listener of this.listeners) {
      listener(degraded);
    }
  }

  subscribe(cb: (degraded: boolean) => void): () => void {
    this.listeners.add(cb);
    return () => {
      this.listeners.delete(cb);
    };
  }

  reset(): void {
    this.frameCount = 0;
    this.lastTime = performance.now();
    this.lowFpsTimer = 0;
    this.recoveredTimer = 0;
    this.degraded = false;
  }
}
