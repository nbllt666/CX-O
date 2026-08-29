/**
 * 视频片段打包（主动视觉视频叙事增强模块）。
 *
 * 消费 RingFrameBuffer：检测到事件后从环形缓冲回溯 preRollSec 秒的事件前帧、
 * 延续 postRollSec 秒事件后帧，打包为一个 clip（帧序列 + 元数据 + 时间戳锚点），
 * 供上层上传 / 叙事存档。
 *
 * 【解耦约定】与 RingFrameBuffer 的 ts 单位保持一致——**毫秒**。
 * - build()：纯同步逻辑，只做「回溯窗口计算 + meta/锚点组装」，不触碰 DOM。
 * - encodeFrames()：负责真实压缩编码，依赖浏览器 canvas，异步返回 Blob；环境无
 *   真实 canvas / MediaRecorder 时优雅降级返回 null。由上层 useVisionPipeline
 *   决定何时编码，build() 不主动调用 encodeFrames()。
 */
import {
  RingFrameBuffer,
  TimestampedFrame,
  FrameSourceKind,
} from './RingFrameBuffer';

/** 片段打包配置；秒级参数默认 3 / 6 / 10 */
export interface VideoClipConfig {
  /** 事件前回溯秒数（默认 3） */
  preRollSec?: number;
  /** 事件后延续秒数（默认 6） */
  postRollSec?: number;
  /** 单片段上限秒数（默认 10）；事件后最多延续到此 */
  clipMaxSec?: number;
  /** 编码目标宽（默认 640），仅浏览器编码生效 */
  maxWidth?: number;
  /** JPEG 质量（默认 0.8），仅浏览器编码生效 */
  jpegQuality?: number;
}

/** 事件描述：来自触发器（检测器） */
export interface ClipEvent {
  type: string;
  ts: number;
  source: FrameSourceKind;
}

/** 打包产物：帧序列 + 元数据 + 时间戳锚点（encoded 由上层编码后回填） */
export interface BuiltClip<T> {
  frames: TimestampedFrame<T>[];
  meta: { eventType: string; ts: number; source: FrameSourceKind };
  startTs: number;
  endTs: number;
  encoded: string | null;
  mimeType: string | null;
}

/** 编码目标画布尺寸（浏览器 encodeFrames 使用） */
export interface EncodeOptions {
  width: number;
  height: number;
}

export class VideoClipBuilder<T> {
  readonly preRollSec: number;
  readonly postRollSec: number;
  readonly clipMaxSec: number;
  readonly maxWidth: number;
  readonly jpegQuality: number;

  constructor(config: VideoClipConfig = {}) {
    this.preRollSec = config.preRollSec ?? 3;
    this.postRollSec = config.postRollSec ?? 6;
    this.clipMaxSec = config.clipMaxSec ?? 10;
    this.maxWidth = config.maxWidth ?? 640;
    this.jpegQuality = config.jpegQuality ?? 0.8;
  }

  /**
   * 回溯窗口 + meta/锚点组装（纯同步，不依赖 DOM，可单测）。
   * 只返回 build 后的帧序列与时间戳锚点，encoded 保持 null，
   * 实际压缩编码由上层决定时机调用 encodeFrames。
   */
  build(
    buffer: RingFrameBuffer<T>,
    event: ClipEvent,
  ): BuiltClip<T> {
    // ts 单位为毫秒：秒级配置 × 1000 换算回溯窗口
    const preMs = this.preRollSec * 1000;
    const postMs = this.postRollSec * 1000;
    const clipMaxMs = this.clipMaxSec * 1000;

    const startTs = event.ts - preMs;
    // 事件后延续被 clipMaxSec 封顶：最多到「事件当刻 + clipMaxSec」
    const afterEnd = event.ts + postMs;
    const maxEnd = event.ts + clipMaxMs;
    const endTs = afterEnd > maxEnd ? maxEnd : afterEnd;

    // slice 为空（空缓冲 / 事件落在窗口外）时返回空帧序列，不抛异常
    const frames = buffer.slice(startTs, endTs);

    return {
      frames,
      meta: { eventType: event.type, ts: event.ts, source: event.source },
      startTs,
      endTs,
      encoded: null,
      mimeType: null,
    };
  }

  /**
   * 真实压缩编码（浏览器环境）。把每帧绘制到低分辨率 canvas，经
   * captureStream + MediaRecorder 合成 WebM 返回 Blob。
   * 环境无真实 canvas / 无 MediaRecorder 时优雅降级返回 null。
   * 注意：Node / vitest(jsdom) 下 canvas.getContext('2d') 返回 null，
   * 因此在此环境恒返回 null，测试只断言降级分支。
   */
  async encodeFrames(
    frames: TimestampedFrame<T>[],
    options: EncodeOptions,
  ): Promise<Blob | null> {
    // 能力检测：无真实 canvas 上下文 → 降级
    const host = this.tryCreateCanvas(options.width, options.height);
    if (!host) return null;
    const { canvas, ctx } = host;

    if (typeof MediaRecorder === 'undefined') return null;

    const fps = this.estimateFps(frames);
    const stream = canvas.captureStream(fps);

    // 优选浏览器可用的 WebM 编码器
    const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(
      (t) => MediaRecorder.isTypeSupported(t),
    );
    if (!mime) return null;

    const recorder = new MediaRecorder(stream, {
      mimeType: mime,
      videoBitsPerSecond: 3_000_000,
    });
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) chunks.push(e.data);
    };
    // stopped：onstop resolve；onerror reject（对齐 onstop 的收尾路径，避免录制
    // 异常时 await 永久挂起）。两者都触发时以先 settle 者为准，防止未处理 rejection。
    let settled = false;
    const stopped = new Promise<void>((resolve, reject) => {
      recorder.onstop = () => {
        if (!settled) {
          settled = true;
          resolve();
        }
      };
      recorder.onerror = (event) => {
        if (!settled) {
          settled = true;
          const err = (event as unknown as { error?: unknown }).error;
          reject(err instanceof Error ? err : new Error('MediaRecorder 录制异常'));
        }
      };
    });
    recorder.start();

    // 逐帧绘制到低分辨率画布，帧间隔由 ts 密度估算（clamp 到 [16,500]ms）
    const intervalMs = Math.min(500, Math.max(16, Math.round(1000 / fps)));
    try {
      for (const f of frames) {
        // 浏览器下 T 为可绘制源（CanvasImageSource）；此绘制仅真实 canvas 环境执行
        ctx.drawImage(f.frame as unknown as CanvasImageSource, 0, 0, options.width, options.height);
        await new Promise((r) => setTimeout(r, intervalMs));
      }
    } catch (err) {
      // 绘制/等待异常（如帧源已释放）：仍终止 recorder 保住 onstop 清理路径，再向上抛出
      try {
        if (recorder.state !== 'inactive') recorder.stop();
        await stopped;
      } catch {
        // recorder 可能已因 error 自行停止（stopped 经 onerror reject），忽略二次异常
      }
      throw err;
    } finally {
      // 无论成功或异常都要停掉 captureStream 的轨道，避免 MediaStream 轨道泄漏
      stream.getTracks().forEach((t) => t.stop());
    }
    if (recorder.state !== 'inactive') recorder.stop();
    await stopped;

    if (chunks.length === 0) return null;
    return new Blob(chunks, { type: mime });
  }

  /** 惰性建画布；任何环节不可用即返回 null（优雅降级） */
  private tryCreateCanvas(
    width: number,
    height: number,
  ): { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D } | null {
    if (typeof document === 'undefined') return null;
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    return { canvas, ctx };
  }

  /** 由帧 ts 中位间距估算帧率（clamp [1,60]）；帧数不足时按 10fps 兜底 */
  private estimateFps(frames: TimestampedFrame<T>[]): number {
    if (frames.length < 2) return 10;
    const deltas: number[] = [];
    for (let i = 1; i < frames.length; i++) {
      const d = frames[i].ts - frames[i - 1].ts;
      if (d > 0) deltas.push(d);
    }
    if (deltas.length === 0) return 10;
    deltas.sort((a, b) => a - b);
    const median = deltas[Math.floor(deltas.length / 2)];
    return Math.min(60, Math.max(1, Math.round(1000 / median)));
  }
}