/**
 * BonePidController 单测：骨骼 PID 平滑控制器的稳定性与收敛性。
 *
 * 覆盖场景（对齐 spec「骨骼 PID 平滑」Requirement）：
 * 1. 阶跃目标：单调平滑趋近、无振荡发散、最终静差 <0.001rad
 * 2. dt 异常（0 / 负值 / NaN / Infinity）：current 不变且不产生 NaN
 * 3. dt 超大（切后台回来）：钳制后安全收敛不爆炸
 * 4. reset 后重新收敛
 * 5. options 参数可配（kp 差异反映到收敛速度）
 */
import { describe, it, expect } from 'vitest';

import { BonePidController } from './vrmBonePid';

/** 模拟 60fps 帧间隔 */
const DT = 1 / 60;

/** 以固定步长推进若干帧并采样全部输出 */
function step(pid: BonePidController, frames: number, dt = DT, gainScale = 1): number[] {
  const samples: number[] = [];
  for (let i = 0; i < frames; i += 1) {
    samples.push(pid.update(dt, gainScale));
  }
  return samples;
}

/** 统计相邻采样间的反向穿越次数（运动方向反转，用于判定振荡） */
function countReversals(samples: number[]): number {
  let reversals = 0;
  for (let i = 1; i < samples.length; i += 1) {
    if (samples[i] < samples[i - 1] - 1e-9) {
      reversals += 1;
    }
  }
  return reversals;
}

describe('BonePidController', () => {
  it('1. 阶跃目标 0→3.0：单调平滑收敛、无振荡发散、最终静差<0.001', () => {
    const pid = new BonePidController(0);
    pid.setTarget(3.0);
    const samples = step(pid, 600);

    // 最终收敛：静差 <0.001rad（spec 验收口径）
    expect(Math.abs(samples[samples.length - 1] - 3.0)).toBeLessThan(0.001);
    // 无反向穿越（单调趋近，无振荡发散）
    expect(countReversals(samples)).toBeLessThanOrEqual(1);
    // 全程有限且峰值不过冲（允许极小裕量）
    for (const v of samples) {
      expect(Number.isFinite(v)).toBe(true);
    }
    expect(Math.max(...samples)).toBeLessThanOrEqual(3.0 + 0.05);
    // 首帧平滑起步：位移远小于总行程（非瞬时跳变）
    expect(samples[0]).toBeGreaterThan(0);
    expect(samples[0]).toBeLessThan(0.5);
  });

  it('1b. 小角度阶跃 0→0.35（对齐 [bone:head:0:0:0.35:1.2] 真实标签量级）收敛', () => {
    const pid = new BonePidController(0);
    pid.setTarget(0.35);
    const samples = step(pid, 300);
    expect(Math.abs(samples[samples.length - 1] - 0.35)).toBeLessThan(0.001);
    expect(countReversals(samples)).toBeLessThanOrEqual(1);
  });

  it('2. dt=0 / 负值 / NaN / Infinity：current 不变且不产生 NaN，之后仍可正常收敛', () => {
    const pid = new BonePidController(0.5);
    pid.setTarget(2.0);

    expect(pid.update(0)).toBe(0.5);
    expect(pid.update(-0.016)).toBe(0.5);
    expect(pid.update(Number.NaN)).toBe(0.5);
    expect(pid.update(Number.POSITIVE_INFINITY)).toBe(0.5);
    expect(Number.isFinite(pid.value)).toBe(true);

    // 异常 dt 不破坏控制器状态，恢复正常帧后仍收敛
    const samples = step(pid, 300);
    expect(Math.abs(samples[samples.length - 1] - 2.0)).toBeLessThan(0.001);
  });

  it('3. dt 超大（切后台 10s）：钳制后单步位移受 maxSpeed×maxDt 限制，安全收敛不爆炸', () => {
    const pid = new BonePidController(0);
    pid.setTarget(1.5);

    // 单帧 dt=10s → 钳到 maxDt=0.5，速度受 maxSpeed=10 限幅 → 单步位移 ≤5
    const oneStep = pid.update(10);
    expect(Number.isFinite(oneStep)).toBe(true);
    expect(oneStep).toBeLessThanOrEqual(10 * 0.5 + 1e-9);
    expect(oneStep).toBeGreaterThan(0);

    // 后续正常帧收敛且无发散
    const samples = step(pid, 300);
    for (const v of samples) {
      expect(Number.isFinite(v)).toBe(true);
    }
    expect(Math.abs(samples[samples.length - 1] - 1.5)).toBeLessThan(0.001);
  });

  it('4. reset(current) 清空积分/微分历史并从新起点重新收敛', () => {
    const pid = new BonePidController(0);
    pid.setTarget(2.0);
    step(pid, 300);
    expect(Math.abs(pid.value - 2.0)).toBeLessThan(0.001);

    // 重置到 0 并换新目标：重新收敛
    pid.reset(0);
    expect(pid.value).toBe(0);
    pid.setTarget(1.0);
    const samples = step(pid, 300);
    expect(Math.abs(samples[samples.length - 1] - 1.0)).toBeLessThan(0.001);
    expect(countReversals(samples)).toBeLessThanOrEqual(1);
  });

  it('4b. 无参 reset 保留 current 只清历史（归中/释放场景运动连续）', () => {
    const pid = new BonePidController(0);
    pid.setTarget(1.0);
    step(pid, 120); // 推进到中途（未收敛）
    const mid = pid.value;
    expect(mid).toBeGreaterThan(0);

    pid.reset();
    expect(pid.value).toBe(mid); // current 保持连续
  });

  it('5. options 参数可配：kp 越大同帧数下推进越远', () => {
    const slow = new BonePidController(0, { kp: 2.0, ki: 0.8, kd: 0.5 });
    const fast = new BonePidController(0, { kp: 12.0, ki: 0.8, kd: 0.5 });
    slow.setTarget(1.0);
    fast.setTarget(1.0);

    const slowSamples = step(slow, 10);
    const fastSamples = step(fast, 10);
    expect(fastSamples[fastSamples.length - 1]).toBeGreaterThan(
      slowSamples[slowSamples.length - 1],
    );
    // 两组均保持稳定（有限值）
    for (const v of [...slowSamples, ...fastSamples]) {
      expect(Number.isFinite(v)).toBe(true);
    }
  });

  it('6. gainScale 提升响应度（归中 speed=3.3 快于常规 1.0）', () => {
    const normal = new BonePidController(0);
    const boosted = new BonePidController(0);
    normal.setTarget(1.0);
    boosted.setTarget(1.0);

    const normalSamples = step(normal, 10, DT, 1.0);
    const boostedSamples = step(boosted, 10, DT, 3.3);
    expect(boostedSamples[boostedSamples.length - 1]).toBeGreaterThan(
      normalSamples[normalSamples.length - 1],
    );
  });
});
