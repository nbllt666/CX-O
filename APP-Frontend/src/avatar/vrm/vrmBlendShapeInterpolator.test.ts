/**
 * BlendShapeInterpolator 单测：L2 指令（setExpression）写入目标权重，
 * L3 update 以 lerpSpeed=5.0 指数平滑收敛，残差 <0.001 时归位。
 *
 * 用假 VRM（expressionManager.setValue 为 vi.fn()）观察写入序列，
 * 不依赖任何真实 VRM 运行时。
 */
import { describe, it, expect, vi } from 'vitest';
import type { VRM } from '@pixiv/three-vrm';

import { BlendShapeInterpolator } from './vrmBlendShapeInterpolator';

function createFakeVRM() {
  const setValue = vi.fn();
  const vrm = {
    expressionManager: { setValue },
  } as unknown as VRM;
  return { vrm, setValue };
}

/** 取 setValue 对某名称最后一次写入的数值 */
function lastValue(setValue: ReturnType<typeof vi.fn>, name: string): number | undefined {
  const calls = setValue.mock.calls.filter((c) => c[0] === name);
  return calls.length ? (calls[calls.length - 1][1] as number) : undefined;
}

describe('BlendShapeInterpolator', () => {
  it('override：setExpression(Happy, 0.3) 后多帧收敛到 0.3（残差归位）', () => {
    const { vrm, setValue } = createFakeVRM();
    const interp = new BlendShapeInterpolator();
    interp.setExpression('Happy', 0.3);

    for (let i = 0; i < 200; i += 1) {
      interp.update(1 / 60, vrm);
    }

    // 残差归位：最终写入恰好为目标值 0.3
    expect(lastValue(setValue, 'Happy')).toBe(0.3);
    // 首帧写入处于 0 与目标之间（平滑逼近而非瞬时跳变）
    const first = setValue.mock.calls[0][1] as number;
    expect(first).toBeGreaterThan(0);
    expect(first).toBeLessThan(0.3);
  });

  it('additive：连续叠加并钳制到 [0, 1]', () => {
    const { vrm, setValue } = createFakeVRM();
    const interp = new BlendShapeInterpolator();

    // 三次 0.4 叠加 → 0.4 → 0.8 → 1.0（钳制）
    interp.setExpression('Blink', 0.4, 'additive');
    interp.setExpression('Blink', 0.4, 'additive');
    interp.setExpression('Blink', 0.4, 'additive');

    // 在 override 基线之上再叠加 → min(1, 0.5+0.7) = 1.0
    interp.setExpression('Happy', 0.5);
    interp.setExpression('Happy', 0.7, 'additive');

    // override 权重钳制到 [0, 1]
    interp.setExpression('Sad', 2.5);
    interp.setExpression('Angry', -1);

    // dt 足够大使 lerpSpeed*dt ≥ 1 → 一帧直接到位
    interp.update(1, vrm);

    expect(lastValue(setValue, 'Blink')).toBe(1.0);
    expect(lastValue(setValue, 'Happy')).toBe(1.0);
    expect(lastValue(setValue, 'Sad')).toBe(1.0);
    expect(lastValue(setValue, 'Angry')).toBe(0.0);
  });

  it('fadeOutUnusedExpressions：非活跃 key 目标归零并平滑', () => {
    const { vrm, setValue } = createFakeVRM();
    const interp = new BlendShapeInterpolator();

    interp.setExpression('Happy', 0.8);
    interp.setExpression('Blink', 0.5);
    // 先推进一帧建立当前权重（currentWeights 仅在 update 时写入）
    interp.update(1, vrm);
    interp.fadeOutUnusedExpressions(['Happy']); // Blink 目标 → 0

    // 首帧平滑下降：Blink 未瞬时归零（0.5 → 0.458）
    interp.update(1 / 60, vrm);
    const blinkAfterFirst = lastValue(setValue, 'Blink') as number;
    expect(blinkAfterFirst).toBeGreaterThan(0);
    expect(blinkAfterFirst).toBeLessThan(0.5);

    // 持续更新后归零
    for (let i = 0; i < 200; i += 1) {
      interp.update(1 / 60, vrm);
    }
    expect(lastValue(setValue, 'Blink')).toBe(0);
    // 活跃 key 目标未受影响
    expect(lastValue(setValue, 'Happy')).toBe(0.8);
  });

  it('setBlendShapes 后非活跃旧表情淡出（O-1 接线行为佐证）', () => {
    const { vrm, setValue } = createFakeVRM();
    const interp = new BlendShapeInterpolator();

    // 模拟 setBlendShapes 批次一：写 Happy 并更新若干帧建立 current
    interp.setExpression('Happy', 0.8);
    for (let i = 0; i < 200; i += 1) {
      interp.update(1 / 60, vrm);
    }
    expect(lastValue(setValue, 'Happy')).toBe(0.8);

    // 模拟 setBlendShapes 批次二：新活跃集为 ['Sad']，
    // 内部 fadeOutUnusedExpressions(['Sad']) 把旧表情 Happy 目标置 0
    interp.setExpression('Sad', 0.6);
    interp.fadeOutUnusedExpressions(['Sad']);

    // 更新后旧表情 Happy 平滑归零
    for (let i = 0; i < 200; i += 1) {
      interp.update(1 / 60, vrm);
    }
    expect(lastValue(setValue, 'Happy')).toBe(0);
    // 新活跃表情 Sad 不受影响，仍收敛到目标 0.6
    expect(lastValue(setValue, 'Sad')).toBe(0.6);
  });

  it('reset 清空目标与当前权重', () => {
    const { vrm, setValue } = createFakeVRM();
    const interp = new BlendShapeInterpolator();

    interp.setExpression('Happy', 0.8);
    interp.update(1 / 60, vrm);
    expect(setValue).toHaveBeenCalledTimes(1);

    interp.reset();

    // 重置后再 update：无目标可写，setValue 不再被调用
    interp.update(1 / 60, vrm);
    expect(setValue).toHaveBeenCalledTimes(1);

    // 重置后可重新写入
    interp.setExpression('Happy', 0.5);
    interp.update(1 / 60, vrm);
    expect(setValue).toHaveBeenCalledTimes(2);
  });
});
