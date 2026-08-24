/**
 * useVisionPipeline — 主动视觉视频叙事采集管线（采集 → 检测 → 打包 → 上传）。
 *
 * 职责与边界（本版范围）：
 * - 采集：接入 useVideoCapture（screen/camera 双源），把捕获当前帧数据推入对应源
 *   的 RingFrameBuffer，并把降采样向量投给 VisionEventDetector。
 * - 检测：VisionEventDetector 判定事件；可打包类（默认 scene_change）命中时调
 *   VideoClipBuilder.build 打包为 BuiltClip。
 * - 打包/上传：设计上「是否真编码上传」受配置与环境影响。默认 encodeAndUpload=false
 *   只把打包结果记录为待上传（pending）；encodeAndUpload=true 时编码为 Blob 后走
 *   uploadVisionClip 真实上传。编码降级（无 Blob）或上传失败时回退为「待上传记录」。
 * - 【明确剥离】本管线不实现发声 / 主动搭话——事件是否触发语音、是否打断回复、
 *   是否主动开口完全交给上层自主系统，本 hook 只负责把视觉片段可靠采下来送上去。
 *
 * 总闸：managedEnabled（options.enabled ?? captureStore.videoModeEnabled）为 false 时整个
 * 管线不启动——不建检测循环、不上传（零侵入，不干扰现有画面帧发送链路）。
 * 视频叙事是重量级采集，默认关闭，门为独立 videoModeEnabled（与图片轮询的 visionEnabled 彼此独立）。
 *
 * 解耦/可测性：核心编排抽离为纯函数工厂 createVisionPipeline(deps)（见下方导出），
 * 不碰 React/DOM；本 hook 只是把 store 开关 + useVideoCapture 帧抓取 + 真实检测/打包/
 * 上传实现注入进去，并用 1s 节拍驱动 tick。测试直接针对 createVisionPipeline 或经
 * hook 的依赖注入点进行，避免依赖真实 canvas/MediaRecorder/网络。
 */
import { useCallback, useEffect, useRef } from 'react';

import { uploadVisionClip } from '../api/clients/vision';
import type { UploadVisionClipRequest } from '../api/clients/vision';
import { useCaptureStore } from '../store/captureStore';
import { RingFrameBuffer } from '../vision/RingFrameBuffer';
import type { FrameSourceKind } from '../vision/RingFrameBuffer';
import { VisionEventDetector } from '../vision/VisionEventDetector';
import type { VisionEvent, VisionEventDetectorOptions } from '../vision/VisionEventDetector';
import { VideoClipBuilder } from '../vision/VideoClipBuilder';
import type { BuiltClip, VideoClipConfig } from '../vision/VideoClipBuilder';
import { isDuplicateFrame, shouldSendByInterval } from './capture/frameThrottle';
import { useVideoCapture } from './capture/useVideoCapture';

/** 帧模型：浏览器采集返回 JPEG dataURL 字符串 */
export type VisionFrame = string;

/** 一次采样产出：帧 dataURL + 降采样向量（供 detector）+ 时间戳 */
export interface SampledFrame {
  dataUrl: string;
  vector: number[] | null;
  ts: number;
}

/** 管线节拍：1s 一拍，兼顾最小采样间隔（frameIntervalSec≥1）与间隔改动即时生效 */
export const PIPELINE_TICK_MS = 1000;

/** 默认可打包事件类型：突变类场景跳转才值得生成视频片段 */
function defaultIsPackable(type: string): boolean {
  return type === 'scene_change';
}

// ── 纯编排工厂（依赖注入，便于单测；不依赖 React/DOM） ──

export interface VisionPipelineDeps {
  /** 总闸；false 时 tick 直接返回，不上传 */
  enabled: boolean;
  /** 采样间隔秒（captureStore.frameIntervalSec，已被 store 钳制 1~60） */
  intervalSec: number;
  /** true 时打包后尝试编码并真实上传；false 仅记录待上传 */
  encodeAndUpload: boolean;
  detector: VisionEventDetector;
  builder: VideoClipBuilder<VisionFrame>;
  /** 取指定来源的环形缓冲（screen/camera 双源各自独立） */
  bufferFor: (kind: FrameSourceKind) => RingFrameBuffer<VisionFrame>;
  /** 采样当前源的一帧；未就绪/无帧返回 null */
  sample: (kind: FrameSourceKind) => Promise<SampledFrame | null>;
  /** 编码为 Blob；环境不支持 / 降级返回 null */
  encode: (clip: BuiltClip<VisionFrame>) => Promise<Blob | null>;
  /** 实际上传出口（默认 uploadVisionClip，可注入 mock） */
  upload: (req: UploadVisionClipRequest) => Promise<{ accepted: boolean }>;
  /** 判定某事件类型是否值得打包（默认 scene_change） */
  isPackable?: (type: string) => boolean;
  /** 命中可打包事件后的钩子（事件透视用，不参与控制流） */
  onEvent?: (event: VisionEvent) => void;
  /** 上传结果钩子 */
  onUploaded?: (result: { accepted: boolean }) => void;
}

export interface VisionPipelineController {
  /** 当前总闸值（经 setEnabled 可变） */
  readonly enabled: boolean;
  setEnabled: (v: boolean) => void;
  setIntervalSec: (v: number) => void;
  /** 采样一轮双源；返回本轮打包的事件数（含降级待传） */
  tick: () => Promise<number>;
  /** 尝试把全部待传片段编码并上传；返回成功上传数 */
  flush: () => Promise<number>;
  /** 停止管线：清空待传/缓冲/时间轴状态，后续 tick 不再采样与上传 */
  dispose: () => void;
  /** 当前待上传（已打包未成功上传）片段数 */
  pendingClipCount: () => number;
  /** 只读快照：当前待上传片段列表（测试/自省用） */
  getPendingClips: () => BuiltClip<VisionFrame>[];
}

/**
 * 视频叙事采集编排核心（纯逻辑，依赖全部注入）。
 * iterate：每轮对该源做「节流 → 去重 → 入缓冲 → 检测 → 命中可打包则 build→encode/upload」。
 */
export function createVisionPipeline(deps: VisionPipelineDeps): VisionPipelineController {
  const enabledRef = { v: deps.enabled };
  const intervalSecRef = { v: deps.intervalSec };
  const disposedRef = { v: false };
  const isPackable = deps.isPackable ?? defaultIsPackable;

  // 每源采样时间轴 / 去重 / 检测前向量
  const lastSampleAt = new Map<FrameSourceKind, number>();
  const lastFrame = new Map<FrameSourceKind, string>();
  const lastVector = new Map<FrameSourceKind, number[]>();
  const pending: BuiltClip<VisionFrame>[] = [];

  const encodeToBlob = async (clip: BuiltClip<VisionFrame>): Promise<Blob | null> => {
    try {
      return await deps.encode(clip);
    } catch {
      return null; // 编码异常按无 Blob 处理
    }
  };

  const uploadOrKeep = async (clip: BuiltClip<VisionFrame>): Promise<void> => {
    const blob = await encodeToBlob(clip);
    if (!blob) {
      pending.push(clip); // 编码降级 → 记录待传
      return;
    }
    try {
      const result = await deps.upload({
        blob,
        eventType: clip.meta.eventType,
        ts: clip.meta.ts,
        source: clip.meta.source,
      });
      deps.onUploaded?.(result);
    } catch {
      pending.push(clip); // 上传失败 → 保留待传，不使整轮中断
    }
  };

  const packageEvent = async (kind: FrameSourceKind, event: VisionEvent): Promise<void> => {
    const clip = deps.builder.build(deps.bufferFor(kind), {
      type: event.type,
      ts: event.ts,
      source: kind,
    });
    if (!deps.encodeAndUpload) {
      pending.push(clip); // 未启用编码 → 记录待传
      return;
    }
    await uploadOrKeep(clip);
  };

  async function tick(): Promise<number> {
    if (disposedRef.v || !enabledRef.v) return 0;
    let packaged = 0;
    const kinds: FrameSourceKind[] = ['screen', 'camera'];
    for (const kind of kinds) {
      const frame = await deps.sample(kind);
      if (!frame) continue;
      const now = frame.ts;
      // 节流：距上次采样未满 intervalSec 跳过本帧
      if (!shouldSendByInterval(now, lastSampleAt.get(kind) ?? null, intervalSecRef.v)) continue;
      // 静止去重：与上次采得帧完全一致则跳过（屏幕静止时重复采样无信息量）
      if (isDuplicateFrame(frame.dataUrl, lastFrame.get(kind) ?? null)) continue;

      deps.bufferFor(kind).push(frame.dataUrl, now);
      lastSampleAt.set(kind, now);
      lastFrame.set(kind, frame.dataUrl);

      if (!frame.vector) {
        continue; // 无向量则无法参与检测，但帧仍已入缓冲
      }
      const prev = lastVector.get(kind);
      lastVector.set(kind, frame.vector);
      if (!prev) continue; // 首帧仅建基线，不做差分
      const event = deps.detector.feed(prev, frame.vector, now, kind);
      if (event && isPackable(event.type)) {
        deps.onEvent?.(event);
        await packageEvent(kind, event);
        packaged++;
      }
    }
    return packaged;
  }

  async function flush(): Promise<number> {
    if (disposedRef.v) return 0;
    if (!deps.encodeAndUpload) return 0; // 未启用编码无法生成 Blob，无可刷
    let uploaded = 0;
    for (let i = pending.length - 1; i >= 0; i--) {
      const clip = pending[i];
      const blob = await encodeToBlob(clip);
      if (!blob) continue;
      try {
        const result = await deps.upload({
          blob,
          eventType: clip.meta.eventType,
          ts: clip.meta.ts,
          source: clip.meta.source,
        });
        pending.splice(i, 1);
        uploaded++;
        deps.onUploaded?.(result);
      } catch {
        // 上传失败保留待传
      }
    }
    return uploaded;
  }

  function dispose(): void {
    disposedRef.v = true;
    pending.length = 0;
    lastSampleAt.clear();
    lastFrame.clear();
    lastVector.clear();
  }

  return {
    get enabled() {
      return enabledRef.v;
    },
    setEnabled: (v) => {
      enabledRef.v = v;
    },
    setIntervalSec: (v) => {
      intervalSecRef.v = v;
    },
    tick,
    flush,
    dispose,
    pendingClipCount: () => pending.length,
    getPendingClips: () => [...pending],
  };
}

// ── 降采样（dataURL → 检测向量）默认实现 ──

/** 采样网格：16×12=192 维，逐像素取 R 通道归一化到 [0,1]，供 detector 做帧差分 */
const SAMPLE_GRID_W = 16;
const SAMPLE_GRID_H = 12;

/** 把 JPEG dataURL 绘制到低分辨率画布读取像素向量；环境不支持时返回 null */
async function sampleDataUrlToVector(dataUrl: string): Promise<number[] | null> {
  if (typeof document === 'undefined') return null;
  const img = await new Promise<HTMLImageElement | null>((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = dataUrl;
  });
  if (!img) return null;
  const canvas = document.createElement('canvas');
  canvas.width = SAMPLE_GRID_W;
  canvas.height = SAMPLE_GRID_H;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0, SAMPLE_GRID_W, SAMPLE_GRID_H);
  const { data } = ctx.getImageData(0, 0, SAMPLE_GRID_W, SAMPLE_GRID_H);
  const vector: number[] = new Array(SAMPLE_GRID_W * SAMPLE_GRID_H);
  for (let i = 0; i < data.length; i += 4) {
    vector[i / 4] = data[i] / 255;
  }
  return vector;
}

// ── React hook（把 store + useVideoCapture + 真实实现接入工厂） ──

export interface UseVisionPipelineOptions {
  /** 增强总开关；缺省读 captureStore.videoModeEnabled（视频叙事独立门） */
  enabled?: boolean;
  /** true 时编码并真实上传；false 仅记录待传（默认 false，保守降级） */
  encodeAndUpload?: boolean;
  /** 检测器配置 */
  detectorOptions?: VisionEventDetectorOptions;
  /** 打包配置（preRoll/postRoll/clipMax 等） */
  clipConfig?: VideoClipConfig;
  /** 环形缓冲留存窗口（默认 30s，与 RingFrameBuffer 默认一致） */
  bufferRetentionMs?: number;
  /** 环形缓冲容量上限（默认 120） */
  bufferMaxFrames?: number;
  /** 编码目标尺寸（默认 640×360） */
  encodeSize?: { width: number; height: number };
  /** 注入编码实现（默认 builder.encodeFrames；测试可替换） */
  encode?: (clip: BuiltClip<VisionFrame>) => Promise<Blob | null>;
  /** 注入实际上传出口（默认 uploadVisionClip；测试可 mock） */
  upload?: (req: UploadVisionClipRequest) => Promise<{ accepted: boolean }>;
  /** 自定义可打包事件判定（默认 scene_change） */
  isPackable?: (type: string) => boolean;
  /** 事件透视钩子 */
  onEvent?: (event: VisionEvent) => void;
  /** 上传结果钩子 */
  onUploaded?: (result: { accepted: boolean }) => void;
  /** 复用宿主已有采集实例采样屏/摄两源，避免与宿主产生双份 getUserMedia/DisplayMedia。
   *  提供后内部不再自建 useVideoCapture（其 active 恒 false，不拉起任何流），完全使用注入的 captureFrame。 */
  cap?: {
    screen: { captureFrame: () => string | null };
    camera: { captureFrame: () => string | null };
  };
}

export interface UseVisionPipelineReturn {
  /** 管线是否运行中：总闸开 且 至少一个会话源激活 */
  active: boolean;
  /** 生效的总闸值 */
  enabled: boolean;
  /** 当前待上传（已打包未成功上传）片段数 */
  pendingClipCount: () => number;
  /** 尝试编码并上传全部待传片段；返回成功上传数 */
  flush: () => Promise<number>;
  /** 停止管线并清理资源（节拍器 / 状态 / 缓冲） */
  dispose: () => void;
}

export function useVisionPipeline(options: UseVisionPipelineOptions = {}): UseVisionPipelineReturn {
  const videoModeEnabled = useCaptureStore((s) => s.videoModeEnabled);
  const screenActive = useCaptureStore((s) => s.screenActive);
  const cameraActive = useCaptureStore((s) => s.cameraActive);
  const frameMode = useCaptureStore((s) => s.frameMode);
  const frameIntervalSec = useCaptureStore((s) => s.frameIntervalSec);

  // 双源采集生命周期（总开关关闭时 active=false → 不拉起媒体流，零侵入）。
  // 若宿主经 cap 注入外部采集实例（如 PetPage 复用自有 useVideoCapture），内部
  // 采集 active 恒 false → 不建立任何 getUserMedia/DisplayMedia 流，避免双份采集。
  const screenCap = useVideoCapture({ kind: 'screen', active: options.cap ? false : screenActive });
  const cameraCap = useVideoCapture({ kind: 'camera', active: options.cap ? false : cameraActive });

  const managedEnabled = options.enabled ?? videoModeEnabled;

  // ref 同步最新渲染值，使 engine 的缺省实现总能读到最新状态
  const enabledRef = useRef(managedEnabled);
  enabledRef.current = managedEnabled;
  const frameModeRef = useRef(frameMode);
  frameModeRef.current = frameMode;
  const screenActiveRef = useRef(screenActive);
  screenActiveRef.current = screenActive;
  const cameraActiveRef = useRef(cameraActive);
  cameraActiveRef.current = cameraActive;
  const screenCapRef = useRef(screenCap);
  screenCapRef.current = screenCap;
  const cameraCapRef = useRef(cameraCap);
  cameraCapRef.current = cameraCap;
  const extCapRef = useRef(options.cap);
  extCapRef.current = options.cap;

  const engineRef = useRef<VisionPipelineController | null>(null);
  if (!engineRef.current) {
    // 双源独立缓冲 + 共享检测器 / 打包器
    const buffers = {
      screen: new RingFrameBuffer<VisionFrame>('screen', {
        retentionMs: options.bufferRetentionMs,
        maxFrames: options.bufferMaxFrames,
      }),
      camera: new RingFrameBuffer<VisionFrame>('camera', {
        retentionMs: options.bufferRetentionMs,
        maxFrames: options.bufferMaxFrames,
      }),
    };
    const detector = new VisionEventDetector(options.detectorOptions);
    const builder = new VideoClipBuilder<VisionFrame>(options.clipConfig);

    engineRef.current = createVisionPipeline({
      enabled: managedEnabled,
      intervalSec: frameIntervalSec,
      encodeAndUpload: options.encodeAndUpload ?? false,
      detector,
      builder,
      bufferFor: (kind) => buffers[kind],
      encode: options.encode ?? ((clip) => builder.encodeFrames(clip.frames, options.encodeSize ?? { width: 640, height: 360 })),
      upload: options.upload ?? uploadVisionClip,
      isPackable: options.isPackable,
      onEvent: options.onEvent,
      onUploaded: options.onUploaded,
      sample: async (kind) => {
        // manual 模式不自动采样（与 useFrameSender 语义一致；管线为自动录制，interval 才采样）
        if (frameModeRef.current === 'manual') return null;
        const active = kind === 'screen' ? screenActiveRef.current : cameraActiveRef.current;
        if (!active) return null;
        // 优先用宿注入的采样源（避免双份采集），否则走内部自建 useVideoCapture
        const ext = extCapRef.current;
        const cap = ext ? ext[kind] : kind === 'screen' ? screenCapRef.current : cameraCapRef.current;
        if (!cap) return null;
        const dataUrl = cap.captureFrame();
        if (!dataUrl) return null;
        const vector = await sampleDataUrlToVector(dataUrl);
        return { dataUrl, vector, ts: Date.now() };
      },
    });
  }

  // 总闸 / 间隔变化同步到 engine
  useEffect(() => {
    engineRef.current?.setEnabled(managedEnabled);
  }, [managedEnabled]);
  useEffect(() => {
    engineRef.current?.setIntervalSec(frameIntervalSec);
  }, [frameIntervalSec]);

  // 节拍驱动：总闸关时不启动定时器；卸载时清理防泄漏
  useEffect(() => {
    if (!managedEnabled) return;
    const timer = setInterval(() => {
      void engineRef.current?.tick();
    }, PIPELINE_TICK_MS);
    return () => clearInterval(timer);
  }, [managedEnabled]);

  useEffect(() => {
    return () => engineRef.current?.dispose();
  }, []);

  const flush = useCallback(() => engineRef.current?.flush() ?? Promise.resolve(0), []);
  const dispose = useCallback(() => engineRef.current?.dispose(), []);
  const pendingClipCount = useCallback(() => engineRef.current?.pendingClipCount() ?? 0, []);

  return {
    active: managedEnabled && (screenActive || cameraActive),
    enabled: managedEnabled,
    pendingClipCount,
    flush,
    dispose,
  };
}

export default useVisionPipeline;