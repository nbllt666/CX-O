import { describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';

import { useMicAsrUplink } from './useMicAsrUplink';
import type { UseMicAsrUplinkOptions } from './useMicAsrUplink';

// 提供稳定的管线 mock，便于断言「是否重建采集上行」
const pipeline = vi.hoisted(() => {
  const analyserRef = { current: null as unknown };
  return {
    audioContextRef: { current: null as unknown },
    analyserRef,
    init: vi.fn(),
    close: vi.fn(() => Promise.resolve()),
    createStreamSource: vi.fn<(s: MediaStream) => MediaStreamAudioSourceNode | null>(() => null),
    createElementSource: vi.fn(() => null),
    createScriptProcessor: vi.fn(() => null),
    createStreamDestination: vi.fn(() => null),
  };
});

vi.mock('./audio/pipeline', () => ({
  useAudioPipeline: () => pipeline,
}));

const opts = (enabled: boolean): UseMicAsrUplinkOptions => ({
  enabled,
  gain: 1,
  sendAudio: () => {},
  speaking: false,
});

/** 拦截 getUserMedia：返回可手动 resolve 的 promise，暴露轨道 stop 的 spy */
function mockGetUserMedia() {
  let resolve!: (stream: MediaStream) => void;
  const promise = new Promise<MediaStream>((r) => {
    resolve = r;
  });
  const stop = vi.fn();
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn(() => promise) },
  });
  return {
    stop,
    resolve: () =>
      resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream),
  };
}

describe('useMicAsrUplink startCapture 护栏', () => {
  it('授权弹窗期间卸载：resolve 后停止轨道且不建管线、不激活、不报错', async () => {
    const g = mockGetUserMedia();
    const { result, unmount } = renderHook(() => useMicAsrUplink(opts(true)));

    unmount(); // 用户在授权弹窗期间卸载
    g.resolve(); // getUserMedia 迟到 resolve
    await act(async () => {});

    expect(g.stop).toHaveBeenCalledTimes(1);
    expect(pipeline.init).not.toHaveBeenCalled();
    expect(pipeline.createStreamSource).not.toHaveBeenCalled();
    expect(result.current.isActive).toBe(false);
  });

  it('授权弹窗期间关闭开关：resolve 后停止轨道且不建管线、不激活', async () => {
    const g = mockGetUserMedia();
    const { result, rerender } = renderHook(
      ({ e }: { e: boolean }) => useMicAsrUplink(opts(e)),
      { initialProps: { e: true } },
    );

    rerender({ e: false }); // 用户在弹窗期间关掉开关
    g.resolve();
    await act(async () => {});

    expect(g.stop).toHaveBeenCalledTimes(1);
    expect(pipeline.init).not.toHaveBeenCalled();
    expect(result.current.isActive).toBe(false);
  });

  it('正常授权：resolve 后建立管线并激活', async () => {
    pipeline.init.mockClear();
    const g = mockGetUserMedia();
    pipeline.analyserRef.current = {
      frequencyBinCount: 16,
      getByteFrequencyData: (a: Uint8Array) => a.fill(0),
      connect: () => {},
    };
    pipeline.createStreamSource.mockReturnValueOnce({
      connect: vi.fn(),
      disconnect: vi.fn(),
    } as unknown as MediaStreamAudioSourceNode);
    pipeline.createScriptProcessor.mockReturnValueOnce({
      connect: vi.fn(),
      disconnect: vi.fn(),
      onaudioprocess: null,
    } as never);
    pipeline.createStreamDestination.mockReturnValueOnce({} as never);

    const { result } = renderHook(() => useMicAsrUplink(opts(true)));
    g.resolve();

    await waitFor(() => expect(result.current.isActive).toBe(true));
    expect(pipeline.init).toHaveBeenCalled();
  });
});

/** 多实例 getUserMedia mock：每次调用返回可独立 resolve 的 promise，逐个暴露轨道 stop spy（H13） */
function mockMultiGetUserMedia() {
  const pendings: Array<{ stop: ReturnType<typeof vi.fn>; resolve: () => void }> = [];
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn(
        () =>
          new Promise<MediaStream>((resolve) => {
            const stop = vi.fn();
            pendings.push({
              stop,
              resolve: () => resolve({ getTracks: () => [{ stop }] } as unknown as MediaStream),
            });
          }),
      ),
    },
  });
  return pendings;
}

describe('useMicAsrUplink startCapture 并发竞态（H13）', () => {
  it('授权等待窗口内二次启动：首个迟到 MediaStream 停轨丢弃，最终仅一份上行管线激活', async () => {
    // 准备一轮完整的管线节点 mock（供第二次 start 成功建图）；清零累计计数
    pipeline.init.mockClear();
    (pipeline.createStreamSource as ReturnType<typeof vi.fn>).mockClear();
    (pipeline.createScriptProcessor as ReturnType<typeof vi.fn>).mockClear();
    (pipeline.createStreamDestination as ReturnType<typeof vi.fn>).mockClear();
    pipeline.analyserRef.current = {
      frequencyBinCount: 16,
      getByteFrequencyData: (a: Uint8Array) => a.fill(0),
      connect: () => {},
    };
    pipeline.createStreamSource.mockReturnValueOnce({
      connect: vi.fn(),
      disconnect: vi.fn(),
    } as unknown as MediaStreamAudioSourceNode);
    pipeline.createScriptProcessor.mockReturnValueOnce({
      connect: vi.fn(),
      disconnect: vi.fn(),
      onaudioprocess: null,
    } as never);
    pipeline.createStreamDestination.mockReturnValueOnce({} as never);

    const pendings = mockMultiGetUserMedia();

    const { result, rerender } = renderHook(
      ({ e }: { e: boolean }) => useMicAsrUplink(opts(e)),
      { initialProps: { e: true } },
    );

    // 第一次启动发起（授权挂起）
    await act(async () => {});
    expect(pendings.length).toBe(1);

    // 授权等待窗口内：关闭开关（作废第一轮）→ 立即再次开启（第二轮启动）
    rerender({ e: false });
    rerender({ e: true });
    await act(async () => {});
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(2);

    // 第一轮授权迟到 resolve：必须立即停轨丢弃，不得泄漏 MediaStream
    pendings[0].resolve();
    await act(async () => {});
    expect(pendings[0].stop).toHaveBeenCalledTimes(1);

    // 第二轮授权到达：正常建图激活，且全程只建一份管线（PCM 不双份上行）
    pendings[1].resolve();
    await waitFor(() => expect(result.current.isActive).toBe(true));
    expect(pipeline.init).toHaveBeenCalledTimes(1);
    expect(pipeline.createStreamSource).toHaveBeenCalledTimes(1);
  });
});