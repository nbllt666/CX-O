import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

import { useAudioAnalyzer } from './useAudioAnalyzer';

// —— 可控的 RAF：手动 flush，避免依赖真实帧回调时序（确定性） ——
const raf = vi.hoisted(() => {
  const pending = new Map<number, FrameRequestCallback>();
  let id = 0;
  return {
    pending,
    raf: ((cb: FrameRequestCallback) => {
      id += 1;
      pending.set(id, cb);
      return id;
    }) as (cb: FrameRequestCallback) => number,
    caf: ((n: number) => {
      pending.delete(n);
    }) as (n: number) => void,
    flush() {
      let guard = 0;
      while (pending.size > 0 && guard < 20000) {
        const entries = [...pending.entries()];
        pending.clear();
        for (const [, cb] of entries) cb(performance.now());
        guard += 1;
      }
    },
  };
});
vi.stubGlobal('requestAnimationFrame', raf.raf as never);
vi.stubGlobal('cancelAnimationFrame', raf.caf as never);

// —— 管线 mock：init 会同步填充 analyser（模拟真实「异步 setup 完成后 analyser 就绪」） ——
const pipeline = vi.hoisted(() => {
  const analyserRef = { current: null as unknown };
  const analyserStub = {
    frequencyBinCount: 16,
    connect: () => {},
    getByteFrequencyData: (arr: Uint8Array) => {
      arr.fill(10); // 16 bin 各 10 → 平均 10 → 归一 0.1
    },
  };
  return {
    audioContextRef: { current: { state: 'running', destination: {} } },
    analyserRef,
    init: vi.fn(() => {
      analyserRef.current = analyserStub;
    }),
    close: vi.fn(() => Promise.resolve()),
    createElementSource: vi.fn(() => ({
      connect: vi.fn(),
      disconnect: vi.fn(),
    })),
    createSource: vi.fn(),
    createStreamSource: vi.fn(() => null),
    createScriptProcessor: vi.fn(() => null),
    createStreamDestination: vi.fn(() => null),
  };
});

vi.mock('./audio/pipeline', () => ({
  useAudioPipeline: () => ({
    audioContextRef: pipeline.audioContextRef,
    analyserRef: pipeline.analyserRef,
    init: pipeline.init,
    close: pipeline.close,
    createElementSource: pipeline.createElementSource,
    createStreamSource: pipeline.createStreamSource,
    createScriptProcessor: pipeline.createScriptProcessor,
    createStreamDestination: pipeline.createStreamDestination,
  }),
}));

describe('useAudioAnalyzer 分析循环（analyser 异步就绪时 RAF 探测重试）', () => {
  it('analyser 未就绪时不中止分析：就绪后由 RAF 轮询启动', async () => {
    const { result } = renderHook(() =>
      useAudioAnalyzer({ audioElement: {} as HTMLAudioElement, isPlaying: true }),
    );

    // effect 首次运行时 setupPipeline 尚未完成 → analyser 为 null，但应已排入轮询 RAF
    expect(pipeline.analyserRef.current).toBeNull();
    expect(result.current.volume).toBe(0);

    // 完成 setup 微任务：init() 同步填充 analyser（此时 effect deps 未变，不会重跑）
    await act(async () => {});
    expect(pipeline.analyserRef.current).not.toBeNull();

    // flush 轮询 RAF → 探测到 analyser → 分析启动
    act(() => {
      raf.flush();
    });

    await waitFor(() => expect(result.current.volume).toBeCloseTo(0.1));
  });

  it('音频条件不满足时输出归零且不启动分析', () => {
    const { result } = renderHook(() => useAudioAnalyzer({ audioElement: null, isPlaying: true }));
    act(() => {
      raf.flush();
    });
    expect(result.current.volume).toBe(0);
    expect(result.current.voiceBandVolume).toBe(0);
  });
});