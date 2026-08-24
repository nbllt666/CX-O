/**
 * useVisionPipeline 测试。
 *
 * 编排核心为纯函数工厂 createVisionPipeline（依赖注入、不碰 DOM/React），
 * 故主要针对工厂做确定性单测；另配一条 renderHook 测总闸接线。
 *
 * 覆盖（checklist「主动视频叙事管线」）：
 * - 总闸：enabled=false 时不初始化采样本、不上传、无待传；
 * - 调用链：事件 → build → encode → upload 一次，参数含 event_type/ts/source；
 * - 双源：screen 与 camera 事件各自打入对应独立缓冲；
 * - 资源：dispose 后不再采样与上传。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, renderHook } from '@testing-library/react';

import { useCaptureStore } from '../store/captureStore';
import { RingFrameBuffer } from '../vision/RingFrameBuffer';
import type { FrameSourceKind } from '../vision/RingFrameBuffer';
import { VideoClipBuilder } from '../vision/VideoClipBuilder';
import { createVisionPipeline, useVisionPipeline } from './useVisionPipeline';

interface TestFrame {
  dataUrl: string;
  vector: number[] | null;
  ts: number;
}

/** 构造按源顺序返回帧序列的 sample 注入函数；队列耗尽返回 null */
function makeSampleQueue(
  byKind: Partial<Record<FrameSourceKind, TestFrame[]>>,
): (kind: FrameSourceKind) => Promise<TestFrame | null> {
  const idx: Record<FrameSourceKind, number> = { screen: 0, camera: 0 };
  return (kind: FrameSourceKind) => {
    const list = byKind[kind];
    if (!list) return Promise.resolve(null);
    const i = idx[kind];
    idx[kind] = i + 1;
    const frame = list[i];
    return Promise.resolve(frame ?? null);
  };
}

/** 组装一份注入齐全的 deps；便于各用例覆盖单个依赖 */
function makeDeps(overrides: Record<string, unknown> = {}): any {
  const screenBuf = new RingFrameBuffer<string>('screen', { retentionMs: 60_000, maxFrames: 1000 });
  const cameraBuf = new RingFrameBuffer<string>('camera', { retentionMs: 60_000, maxFrames: 1000 });
  const detector = { feed: vi.fn(() => null) } as any; // 默认不触发；用例可换真 detector
  const builder = new VideoClipBuilder<string>();
  const encode = vi.fn();
  encode.mockResolvedValue(new Blob(['webm'], { type: 'video/webm' }));
  const upload = vi.fn();
  upload.mockResolvedValue({ accepted: true });
  return {
    enabled: true,
    intervalSec: 1,
    encodeAndUpload: false,
    detector,
    builder,
    screenBuf,
    cameraBuf,
    bufferFor: (k: FrameSourceKind) => (k === 'screen' ? screenBuf : cameraBuf),
    sample: vi.fn(),
    encode,
    upload,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  useCaptureStore.setState({
    visionEnabled: false,
    videoModeEnabled: false,
    screenActive: false,
    cameraActive: false,
    frameMode: 'interval',
    frameIntervalSec: 5,
  });
});

describe('createVisionPipeline 总闸', () => {
  it('enabled=false：不采样、不上传、无待传', async () => {
    const sample = vi.fn();
    const upload = vi.fn();
    const pipe = createVisionPipeline(makeDeps({ enabled: false, sample, upload }));
    expect(pipe.enabled).toBe(false);
    expect(await pipe.tick()).toBe(0);
    expect(sample).not.toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
    expect(pipe.pendingClipCount()).toBe(0);
  });
});

describe('createVisionPipeline 调用链 build→encode→upload', () => {
  it('突变命中 → build → encode → upload 一次，参数含 eventType/ts/source', async () => {
    const buildSpy = vi.spyOn(VideoClipBuilder.prototype, 'build');
    const d = makeDeps({ encodeAndUpload: true });
    d.detector = {
      feed: (prev: number[], curr: number[], now: number) =>
        prev.every((v) => v === 0) && curr.some((v) => v > 0)
          ? { type: 'scene_change', ts: now, source: 'screen' }
          : null,
    };
    d.bufferFor = (k: FrameSourceKind) => (k === 'screen' ? d.screenBuf : d.cameraBuf);
    d.sample = makeSampleQueue({
      screen: [
        { dataUrl: 'a', vector: [0, 0, 0], ts: 0 },
        { dataUrl: 'b', vector: [1, 1, 1], ts: 1000 },
      ],
    });
    const upload = vi.fn().mockResolvedValue({ accepted: true });
    d.upload = upload;

    const pipe = createVisionPipeline(d);
    expect(await pipe.tick()).toBe(0); // 首帧建基线
    expect(await pipe.tick()).toBe(1); // 突变 → 打包
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload).toHaveBeenCalledWith({
      blob: expect.any(Blob),
      eventType: 'scene_change',
      ts: 1000,
      source: 'screen',
    });
    expect(buildSpy).toHaveBeenCalledTimes(1);
    expect(pipe.pendingClipCount()).toBe(0); // 编码上传成功，无待传
    buildSpy.mockRestore();
  });

  it('encodeAndUpload=false：仅记录待传，不调用 upload', async () => {
    const d = makeDeps({ encodeAndUpload: false });
    d.detector = { feed: () => ({ type: 'scene_change', ts: 0, source: 'screen' }) };
    d.sample = makeSampleQueue({
      screen: [
        { dataUrl: 'a', vector: [0, 0, 0], ts: 0 },
        { dataUrl: 'b', vector: [1, 1, 1], ts: 1000 },
      ],
    });
    const pipe = createVisionPipeline(d);
    expect(await pipe.tick()).toBe(0);
    expect(await pipe.tick()).toBe(1);
    expect(d.upload).not.toHaveBeenCalled();
    expect(pipe.pendingClipCount()).toBe(1);
  });
});

describe('createVisionPipeline 双源独立缓冲', () => {
  it('screen 与 camera 事件各自打包出对应来源的片段帧', async () => {
    const d = makeDeps({ encodeAndUpload: false });
    // 用真检测器：首帧建基线，次帧突变触发 scene_change；错开 ts 避开冷却
    d.detector = new (await import('../vision/VisionEventDetector')).VisionEventDetector();
    d.sample = makeSampleQueue({
      screen: [
        { dataUrl: 'a', vector: [0, 0, 0], ts: 0 },
        { dataUrl: 'b', vector: [1, 1, 1], ts: 1000 },
      ],
      camera: [
        { dataUrl: 'c', vector: [0, 0, 0], ts: 20_000 },
        { dataUrl: 'd', vector: [1, 1, 1], ts: 21_000 },
      ],
    });
    const pipe = createVisionPipeline(d);
    expect(await pipe.tick()).toBe(0); // 双源首帧/基线
    expect(await pipe.tick()).toBe(2); // 双源各出一次 scene_change
    expect(pipe.pendingClipCount()).toBe(2);

    const clips = pipe.getPendingClips();
    const screenClip = clips.find((c) => c.meta.source === 'screen');
    const cameraClip = clips.find((c) => c.meta.source === 'camera');
    expect(screenClip?.meta.eventType).toBe('scene_change');
    expect(screenClip?.meta.ts).toBe(1000);
    // 帧来自 screen 缓冲
    expect(screenClip?.frames.map((f) => f.frame)).toEqual(['a', 'b']);
    expect(cameraClip?.meta.ts).toBe(21_000);
    expect(cameraClip?.frames.map((f) => f.frame)).toEqual(['c', 'd']);
  });
});

describe('createVisionPipeline dispose', () => {
  it('dispose 后不再采样与上传', async () => {
    const d = makeDeps({ encodeAndUpload: true });
    d.detector = { feed: () => ({ type: 'scene_change', ts: 0, source: 'screen' }) };
    d.sample = makeSampleQueue({
      screen: [
        { dataUrl: 'a', vector: [0, 0, 0], ts: 0 },
        { dataUrl: 'b', vector: [1, 1, 1], ts: 1000 },
        { dataUrl: 'c', vector: [0, 0, 0], ts: 2000 },
      ],
    });
    const upload = vi.fn().mockResolvedValue({ accepted: true });
    d.upload = upload;
    const pipe = createVisionPipeline(d);

    expect(await pipe.tick()).toBe(0);
    expect(await pipe.tick()).toBe(1);
    expect(upload).toHaveBeenCalledTimes(1);

    pipe.dispose();
    expect(await pipe.tick()).toBe(0); // disposed → 立即返回，不再采样/上传
    expect(upload).toHaveBeenCalledTimes(1);
    expect(pipe.pendingClipCount()).toBe(0); // 状态已清空
  });
});

describe('useVisionPipeline 总闸接线', () => {
  it('videoModeEnabled=false：管线不启动（enabled/active 均 false，无待传）', () => {
    useCaptureStore.setState({
      visionEnabled: true, // 图片轮询开关开启，但不应影响视频管线的门
      videoModeEnabled: false,
      screenActive: false,
      cameraActive: false,
      frameMode: 'interval',
    });
    const { result } = renderHook(() => useVisionPipeline());
    expect(result.current.enabled).toBe(false);
    expect(result.current.active).toBe(false);
    expect(result.current.pendingClipCount()).toBe(0);
  });

  it('videoModeEnabled=true：管线启动（enabled/active 依会话源）', () => {
    useCaptureStore.setState({
      visionEnabled: false, // 图片轮询开关关闭，也不应阻断视频管线的门
      videoModeEnabled: true,
      screenActive: true,
      cameraActive: false,
      frameMode: 'interval',
    });
    const { result } = renderHook(() => useVisionPipeline());
    expect(result.current.enabled).toBe(true);
    expect(result.current.active).toBe(true);
  });
});