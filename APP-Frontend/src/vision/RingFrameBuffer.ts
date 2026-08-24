/**
 * 环形帧缓冲（纯逻辑，视频叙事地基模块）。
 *
 * 视频叙事模型：像行车记录仪一样持续把采集帧写入内存环形缓冲，平时不落盘、
 * 不上传，只有"出事"（事件触发器）时回调 slice 回溯打包并上传。本模块只做
 * 内存缓冲，不含网络/检测逻辑。
 *
 * 双源（screen/camera）分管线：按 spec 决策点 #4 采用"可独立实例化两个缓冲"
 * 方案，构造函数携带 source 标识，同一前端分别 new 两个实例，保证摄像头与
 * 屏幕两条采集线互不影响、互不复用。ts 由调用方传入（不依赖 Date.now() 内部
 * 取时），便于单测注入任意时间轴。
 */
export type FrameSourceKind = 'camera' | 'screen';

/** 一条带时间戳的帧（frame 为 null 表示该时刻占位，不参与回溯返回） */
export interface TimestampedFrame<T> {
  frame: T;
  ts: number;
}

export interface RingFrameBufferOptions {
  /** 帧留存时间窗（毫秒），超过此时长的最旧帧被淘汰；默认 30s */
  retentionMs?: number;
  /** 容量上限，超过 maxFrames 条也淘汰最旧帧；默认 120（30s×4FPS） */
  maxFrames?: number;
}

/** 内部存储条目：frame 可为 null，表示某时刻无帧的时间轴占位 */
interface RingEntry<T> {
  frame: T | null;
  ts: number;
}

export class RingFrameBuffer<T> {
  readonly source: FrameSourceKind;
  readonly retentionMs: number;
  readonly maxFrames: number;

  /** 帧按 ts 升序存储；head 为最旧，tail 为最新 */
  private readonly entries: RingEntry<T>[] = [];

  constructor(source: FrameSourceKind, options: RingFrameBufferOptions = {}) {
    this.source = source;
    this.retentionMs = options.retentionMs ?? 30_000;
    this.maxFrames = options.maxFrames ?? 120;
  }

  /** 写入一条帧，随后按时间窗与容量双重淘汰最旧帧 */
  push(frame: T | null, ts: number): void {
    this.entries.push({ frame, ts });
    this.evict(ts);
  }

  /**
   * 回溯取 [startTs, endTs] 闭区间内的帧，按 ts 升序返回。
   * 仅返回 frame 非 null 的条目（占位帧不参与回溯结果）。
   */
  slice(startTs: number, endTs: number): TimestampedFrame<T>[] {
    const result: TimestampedFrame<T>[] = [];
    for (const e of this.entries) {
      if (e.ts < startTs) continue;
      if (e.ts > endTs) break; // 已按升序存储，可提前退出
      if (e.frame !== null) result.push({ frame: e.frame, ts: e.ts });
    }
    return result;
  }

  /** 取最近 n 帧（升序）；n 非正数返回空数组 */
  latest(n: number): TimestampedFrame<T>[] {
    if (n <= 0) return [];
    const result: TimestampedFrame<T>[] = [];
    // 从最新往旧扫，收集非占位帧
    for (let i = this.entries.length - 1; i >= 0 && result.length < n; i--) {
      const e = this.entries[i];
      if (e.frame !== null) result.push({ frame: e.frame, ts: e.ts });
    }
    result.reverse(); // 恢复升序
    return result;
  }

  /** 当前缓冲内已存帧条数（含占位帧） */
  get size(): number {
    return this.entries.length;
  }

  /**
   * 淘汰最旧帧，同时套用两个上限：
   * 1) 时间窗：帧距今超出 retentionMs（相对最新帧 ts）即淘汰；
   * 2) 容量：超出 maxFrames 条即淘汰最旧。
   */
  private evict(latestTs: number): void {
    // 时间淘汰：以最新写入帧的时间为基准，早于 cutoff 的帧视为过期
    const cutoff = latestTs - this.retentionMs;
    while (this.entries.length > 0 && this.entries[0].ts < cutoff) {
      this.entries.shift();
    }
    // 容量淘汰：无论时间窗长短，容量上限始终生效
    while (this.entries.length > this.maxFrames) {
      this.entries.shift();
    }
  }
}