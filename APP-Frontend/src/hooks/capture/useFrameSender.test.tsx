/**
 * useFrameSender 测试。
 *
 * adaptive 分支的可测性依赖动态间隔生产者（AdaptiveIntervalProvider）——
 * 真实现（defaultAdaptiveIntervalProvider）走 computeChangeMagnitude + canvas，
 * 在 node/jsdom 下必然降级 0，无法直接表达「活跃/静止」差异。故本测试通过
 * UseFrameSenderOptions.adaptiveIntervalProvider 注入确定性 producer 断言裁决，
 * 再对默认生产者做纯函数级单测覆盖「降级 0 → 退化 interval」路径。
 *
 * 节奏断言用单次大步进 `advanceTimersByTimeAsync(ms)` 驱动（多次小步进在
 * send 触发 setState 后与 React+fakeTimers 失步，导致后续节拍不触发）。
 *
 * 覆盖（checklist「发送节奏可控」）：
 * - manual 回归：不启动节拍器，仅 sendNow() 点发；
 * - interval 回归：满 intervalSec 才放行（5s：4s→1 帧，6s→2 帧）；
 * - adaptive 活跃 → 更频繁（provider 返回 1，6s 内 6 帧，远多于固定 5s）；
 * - adaptive 静止 → 拉长（provider 返回 10，6s 内仅首帧发出）；
 * - adaptive 不支持 → 退化为 interval（provider 抛错，按 intervalSec=5 定时）；
 * - defaultAdaptiveIntervalProvider：变化度不可算（=0/相同帧）→ 退化 baseIntervalSec。
 * - dutyCycle 透传：注入 provider 第 4 参收到注入值/缺省 undefined（缺省路径与现状一致）。
 */
import { act, cleanup, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { defaultAdaptiveIntervalProvider, useFrameSender } from './useFrameSender';
import type { FrameSource } from './frameThrottle';
import type { CaptureSourceKind } from './useVideoCapture';

/** 每次抓帧都返回唯一 dataURL 的激活帧源，避免静止去重干扰节奏断言 */
function makeChangingSource(kind: CaptureSourceKind = 'screen'): FrameSource {
  let n = 0;
  return { kind, active: true, captureFrame: () => `data:image/jpeg;base64,frame${n++}` };
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** 单次大步进：让 setInterval 触发并冲刷 async IIFE 的微任务 */
async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('useFrameSender manual 回归', () => {
  it('manual 模式不启动节拍器，仅 sendNow 点发', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    const { result } = renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'manual',
        intervalSec: 5,
        sendFrame,
      }),
    );

    await advance(3000); // 3s：manual 不启用节拍器，应毫无动静
    expect(sendFrame).not.toHaveBeenCalled();

    expect(result.current.sendNow()).toBe(true);
    expect(sendFrame).toHaveBeenCalledTimes(1);
  });
});

describe('useFrameSender interval 回归', () => {
  it('5s 间隔：4s 内仅首帧发，6s 内发两帧（第 1、6 秒）', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'interval',
        intervalSec: 5,
        sendFrame,
      }),
    );

    await advance(4000); // t=4s：首帧(1s)后仅 3s，不足 5s → 仅 1 帧
    expect(sendFrame).toHaveBeenCalledTimes(1);
  });

  it('5s 间隔：6s 后发两帧（第 1、6 秒）', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'interval',
        intervalSec: 5,
        sendFrame,
      }),
    );

    await advance(6000); // t=6s：满 5s → 第 2 帧
    expect(sendFrame).toHaveBeenCalledTimes(2);
  });
});

describe('useFrameSender adaptive', () => {
  it('活跃画面（动态间隔=1s）→ 6s 内发 6 帧，远多于固定 5s', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    const provider = vi.fn(async () => 1);
    renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'adaptive',
        intervalSec: 5, // 基准 5s，但活跃时动态间隔压到 1s
        sendFrame,
        adaptiveIntervalProvider: provider,
      }),
    );

    await advance(6000);
    expect(sendFrame).toHaveBeenCalledTimes(6); // 每秒一拍即发
    expect(provider).toHaveBeenCalledTimes(6); // 每个节拍都向 producer 询问动态间隔
  });

  it('静止画面（动态间隔=10s）→ 6s 内仅首帧发出', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'adaptive',
        intervalSec: 5,
        sendFrame,
        adaptiveIntervalProvider: async () => 10,
      }),
    );

    await advance(6000); // 首帧(1s)后距 10s 尚缺 9s → 不再发
    expect(sendFrame).toHaveBeenCalledTimes(1);
  });

  it('环境不支持（provider 抛错）→ 退化为 interval（按 intervalSec=5 定时）', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'adaptive',
        intervalSec: 5,
        sendFrame,
        adaptiveIntervalProvider: async () => {
          throw new Error('canvas unsupported');
        },
      }),
    );

    await advance(6000); // 5s 节拍：第 1、6 秒各一帧，与 interval 完全一致
    expect(sendFrame).toHaveBeenCalledTimes(2);
  });
});

describe('defaultAdaptiveIntervalProvider（退化路径纯函数）', () => {
  it('变化度不可算（返回 0）→ 退化为 baseIntervalSec', async () => {
    await expect(defaultAdaptiveIntervalProvider('data:image/img,a', null, 5)).resolves.toBe(5);
    // 两帧完全一致（computeChangeMagnitude 快速路径返回 0）同样退化到基准间隔
    await expect(defaultAdaptiveIntervalProvider('data:image/img,a', 'data:image/img,a', 5)).resolves.toBe(5);
  });
});

describe('useFrameSender dutyCycle 透传', () => {
  it('传 dutyCycle 时 provider 第 4 参收到该值', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    const provider = vi.fn(async () => 1);
    renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'adaptive',
        intervalSec: 5,
        sendFrame,
        dutyCycle: 80,
        adaptiveIntervalProvider: provider,
      }),
    );

    await advance(1500); // 首拍（1s）即向 provider 询问动态间隔
    expect(provider).toHaveBeenCalledTimes(1);
    expect(provider).toHaveBeenCalledWith('data:image/jpeg;base64,frame0', null, 5, 80);
  });

  it('不传 dutyCycle 时 provider 第 4 参收到 undefined（缺省路径与现状一致）', async () => {
    vi.useFakeTimers();
    const sendFrame = vi.fn();
    const provider = vi.fn(async () => 1);
    renderHook(() =>
      useFrameSender({
        sources: [makeChangingSource('screen')],
        mode: 'adaptive',
        intervalSec: 5,
        sendFrame,
        adaptiveIntervalProvider: provider,
      }),
    );

    await advance(1500);
    expect(provider).toHaveBeenCalledTimes(1);
    expect(provider).toHaveBeenCalledWith('data:image/jpeg;base64,frame0', null, 5, undefined);
  });
});