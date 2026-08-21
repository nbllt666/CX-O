/**
 * PerformanceMonitor 单测：FPS 结算与降级/恢复状态机。
 *
 * 用 vi.spyOn(performance, 'now') 模拟时间推进（构造器读取同一 mock），
 * 每“秒”先在本秒区间内模拟 frames 次 update，再推进到整秒边界触发结算。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { PerformanceMonitor } from './vrmPerformanceMonitor';

let now = 0;

/** 模拟一“秒”：本秒区间内跑 frames 帧（含结算 update），随后推进到整秒边界触发结算 */
function runSecond(monitor: PerformanceMonitor, frames: number): void {
  const start = now;
  // 结算用的 update 本身也计一帧 → 循环内跑 frames-1 帧
  for (let f = 0; f < frames - 1; f += 1) {
    now = start + ((f + 1) * 999) / frames; // 保持 < start + 1000，避免提前结算
    monitor.update(0);
  }
  now = start + 1000; // 越过整秒边界触发结算（本帧计入 frames）
  monitor.update(0);
}

describe('PerformanceMonitor', () => {
  beforeEach(() => {
    now = 0;
    vi.spyOn(performance, 'now').mockImplementation(() => now);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('低帧持续 2 秒后降级并触发一次回调', () => {
    const monitor = new PerformanceMonitor();
    const onDegraded = vi.fn();
    const onRecovered = vi.fn();
    monitor.subscribe((degraded) => (degraded ? onDegraded() : onRecovered()));

    // 第 1 秒：25 帧 → currentFPS=25，不足阈值，仅计时 1
    runSecond(monitor, 25);
    expect(monitor.currentFPS).toBe(25);
    expect(monitor.degraded).toBe(false);
    expect(onDegraded).not.toHaveBeenCalled();

    // 第 2 秒：仍 25 帧 → 连续 2 秒低帧 → 降级，回调仅触发一次
    runSecond(monitor, 25);
    expect(monitor.currentFPS).toBe(25);
    expect(monitor.degraded).toBe(true);
    expect(onDegraded).toHaveBeenCalledTimes(1);
    expect(onRecovered).not.toHaveBeenCalled();
  });

  it('降级后高帧持续 2 秒恢复并触发回调', () => {
    const monitor = new PerformanceMonitor();
    const onDegraded = vi.fn();
    const onRecovered = vi.fn();
    monitor.subscribe((degraded) => (degraded ? onDegraded() : onRecovered()));

    // 先进入降级（连续 2 秒低帧）
    runSecond(monitor, 25);
    runSecond(monitor, 25);
    expect(monitor.degraded).toBe(true);

    // 第 3 秒：60 帧 → recoveredTimer=1，未达连续 2 秒
    runSecond(monitor, 60);
    expect(monitor.currentFPS).toBe(60);
    expect(monitor.degraded).toBe(true);

    // 第 4 秒：仍 60 帧 → 连续 2 秒高帧 → 恢复
    runSecond(monitor, 60);
    expect(monitor.currentFPS).toBe(60);
    expect(monitor.degraded).toBe(false);
    expect(onRecovered).toHaveBeenCalledTimes(1);
    expect(onDegraded).toHaveBeenCalledTimes(1);
  });

  it('防抖动：低帧不足 2 秒不降级', () => {
    const monitor = new PerformanceMonitor();
    const onDegraded = vi.fn();
    monitor.subscribe((degraded) => {
      if (degraded) onDegraded();
    });

    // 第 1 秒低帧
    runSecond(monitor, 25);
    expect(monitor.degraded).toBe(false);

    // 第 2 秒回升高帧 → 低帧计时清零
    runSecond(monitor, 60);
    expect(monitor.degraded).toBe(false);
    expect(onDegraded).not.toHaveBeenCalled();

    // 第 3 秒再次低帧 → 仅 1 秒，需连续 2 秒才降级
    runSecond(monitor, 25);
    expect(monitor.degraded).toBe(false);
    expect(onDegraded).not.toHaveBeenCalled();
  });
});
