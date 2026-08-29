import { describe, expect, it, vi } from 'vitest';

import { RingFrameBuffer } from './RingFrameBuffer';
import { VideoClipBuilder } from './VideoClipBuilder';

/** 构造测试缓冲：Frame 用数字帧序号即可，ts 单位为毫秒（与 RingFrameBuffer 对齐） */
function makeBuffer() {
  return new RingFrameBuffer<number>('camera', {
    retentionMs: 60_000,
    maxFrames: 1000,
  });
}

/** 事件前 3s + 事件后 6s，默认配置回溯窗口 */
describe('VideoClipBuilder build 回溯窗口', () => {
  it('startTs≈ts-preRoll*1000、endTs≈ts+postRoll*1000，帧按升序', () => {
    const buf = makeBuffer();
    const builder = new VideoClipBuilder<number>(); // 默认 3/6/10
    // 连续压入 0s~20s 每 1000ms 一帧
    for (let i = 0; i <= 20; i++) buf.push(i, i * 1000);

    const eventTs = 10_000;
    const clip = builder.build(buf, { type: 'motion', ts: eventTs, source: 'camera' });

    expect(clip.startTs).toBe(eventTs - 3 * 1000); // 7000
    expect(clip.endTs).toBe(eventTs + 6 * 1000); // 16000
    // 命中 [7000,16000] 闭区间，共 10 帧，升序
    expect(clip.frames.map((f) => f.ts)).toEqual(
      Array.from({ length: 10 }, (_, i) => (i + 7) * 1000),
    );
    expect(clip.frames[0].frame).toBe(7);
    expect(clip.frames[clip.frames.length - 1].frame).toBe(16);
  });
});

describe('VideoClipBuilder build 截断', () => {
  it('事件后超过 clipMaxSec 的帧被截断，endTs 不超过 ts+clipMaxSec*1000', () => {
    const buf = makeBuffer();
    // postRoll 12s 超过 clipMax 5s → 应被截断到事件当刻+5s
    const builder = new VideoClipBuilder<number>({ preRollSec: 1, postRollSec: 12, clipMaxSec: 5 });
    for (let i = 0; i <= 20; i++) buf.push(i, i * 1000);

    const eventTs = 10_000;
    const clip = builder.build(buf, { type: 'motion', ts: eventTs, source: 'camera' });

    expect(clip.startTs).toBe(eventTs - 1 * 1000); // 9000
    expect(clip.endTs).toBe(eventTs + 5 * 1000); // 15000（被封顶）
    expect(clip.endTs).toBeLessThanOrEqual(eventTs + 5 * 1000);
    // 事件后只延续到 15000，不含 16000
    expect(clip.frames[clip.frames.length - 1].ts).toBe(15_000);
  });

  it('postRoll 未超 clipMax 时不截断', () => {
    const buf = makeBuffer();
    const builder = new VideoClipBuilder<number>({ preRollSec: 1, postRollSec: 4, clipMaxSec: 10 });
    for (let i = 0; i <= 20; i++) buf.push(i, i * 1000);
    const clip = builder.build(buf, { type: 'x', ts: 10_000, source: 'screen' });
    expect(clip.endTs).toBe(10_000 + 4 * 1000); // 14000，未被截断
  });
});

describe('VideoClipBuilder build meta 与顺序', () => {
  it('meta 正确携带 eventType/ts/source，帧按升序', () => {
    const buf = makeBuffer();
    const builder = new VideoClipBuilder<number>();
    for (let i = 0; i <= 10; i++) buf.push(i, i * 500);

    const clip = builder.build(buf, { type: 'sound-peak', ts: 2_500, source: 'screen' });
    expect(clip.meta.eventType).toBe('sound-peak');
    expect(clip.meta.ts).toBe(2_500);
    expect(clip.meta.source).toBe('screen');

    // 帧严格严格升序
    const ts = clip.frames.map((f) => f.ts);
    expect([...ts].sort((a, b) => a - b)).toEqual(ts);
    // build 不编码：encoded / mimeType 恒为 null
    expect(clip.encoded).toBeNull();
    expect(clip.mimeType).toBeNull();
  });
});

describe('VideoClipBuilder build 空降级', () => {
  it('空缓冲返回空帧序列但不抛异常', () => {
    const buf = new RingFrameBuffer<number>('camera');
    const builder = new VideoClipBuilder<number>();
    const clip = builder.build(buf, { type: 'x', ts: 5_000, source: 'camera' });
    expect(clip.frames).toEqual([]);
    expect(clip.meta.ts).toBe(5_000);
    expect(clip.startTs).toBe(2_000);
  });

  it('事件落在窗口外（无帧命中）返回空帧序列但不抛异常', () => {
    const buf = makeBuffer();
    buf.push(1, 0); // 仅 0ms 一帧
    const builder = new VideoClipBuilder<number>();
    // 事件 ts=5000 → 窗口 [2000,11000]，帧 ts=0 落在窗口外
    const clip = builder.build(buf, { type: 'x', ts: 5_000, source: 'camera' });
    expect(clip.frames).toEqual([]);
  });
});

describe('VideoClipBuilder encodeFrames 降级', () => {
  it('方法存在且签名正确；无真实 canvas（jsdom）环境优雅降级返回 null', async () => {
    const builder = new VideoClipBuilder<number>();
    // 断言方法存在（对 encodeFrames 的最低验证）
    expect(typeof builder.encodeFrames).toBe('function');

    const blob = await builder.encodeFrames(
      [
        { frame: 1, ts: 0 },
        { frame: 2, ts: 16 },
      ],
      { width: 640, height: 360 },
    );
    // jsdom 下 canvas.getContext('2d') 返回 null → 不调用真实 canvas，恒返回 null
    expect(blob).toBeNull();
  });
});

describe('VideoClipBuilder encodeFrames 异常清理', () => {
  it('drawImage 抛错时仍终止 recorder 并释放 captureStream 轨道，且向上抛出原错误', async () => {
    // ── Fake 环境：最小 canvas / MediaRecorder 替身（真实清理路径验证）──
    const trackStop = vi.fn();
    const fakeStream = { getTracks: () => [{ stop: trackStop }] };
    const drawImage = vi.fn(() => {
      throw new Error('draw fail');
    });
    const fakeCanvas = {
      width: 0,
      height: 0,
      getContext: () => ({ drawImage }),
      captureStream: () => fakeStream,
    };

    // 最小 FakeMediaRecorder：记录 stop 次数；stop() 触发 onstop（与真实行为一致）
    let stopCalls = 0;
    const instances: unknown[] = [];
    class FakeMediaRecorder {
      static isTypeSupported(): boolean {
        return true;
      }
      state: 'recording' | 'inactive' = 'inactive';
      ondataavailable: ((e: unknown) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: ((e: unknown) => void) | null = null;
      constructor() {
        instances.push(this);
      }
      start(): void {
        this.state = 'recording';
      }
      stop(): void {
        stopCalls += 1;
        this.state = 'inactive';
        this.onstop?.();
      }
    }

    const originalCreateElement: (tag: string, options?: ElementCreationOptions) => HTMLElement =
      document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation(
      (tag: string, options?: ElementCreationOptions) =>
        tag === 'canvas'
          ? (fakeCanvas as unknown as HTMLCanvasElement)
          : originalCreateElement(tag, options),
    );
    const originalMediaRecorder = (globalThis as { MediaRecorder?: unknown }).MediaRecorder;
    (globalThis as { MediaRecorder?: unknown }).MediaRecorder = FakeMediaRecorder;

    try {
      const builder = new VideoClipBuilder<number>();
      await expect(
        builder.encodeFrames(
          [
            { frame: 1, ts: 0 },
            { frame: 2, ts: 16 },
          ],
          { width: 320, height: 180 },
        ),
      ).rejects.toThrow('draw fail');
    } finally {
      createElementSpy.mockRestore();
      (globalThis as { MediaRecorder?: unknown }).MediaRecorder = originalMediaRecorder;
    }

    // 异常路径仍完成清理：captureStream 轨道已 stop、recorder 已终止（onstop 清理路径被保住）
    expect(trackStop).toHaveBeenCalledTimes(1);
    expect(stopCalls).toBe(1);
    expect(instances.length).toBe(1);
  });
});