/**
 * 视觉事件检测（纯逻辑，视频叙事增强地基模块）。
 *
 * 场景模型：前端在帧节流之后做「何时值得打包视频」的轻量判定，贵重的视频理解
 * 绝不能无脑定时打包，必须事件驱动。本模块只做前端粗筛（scene_change 等触发），
 * 复杂 emotion/state 类事件由后端精判，故本类不要求全量实现类型枚举，仅枚举
 * 全量以便上层透传。
 *
 * 分级策略（省算力）：
 *   帧流 → [帧差分] 相邻帧差异 < diffThreshold → 跳过（画面静止）
 *       ↓ 有变化
 *   [变化量评估]
 *       ├─ 微变化（光标/鼠标）→ 忽略（不产生事件，也不视为静止）
 *       ├─ 中变化（滚动/打字）→ 低频关注（user_action + lowPriority）
 *       └─ 突变（切窗/场景跳转/大动作）→ 触发打包（scene_change）
 *
 * 双向解耦原则：
 *   - feed 接收「向量」而非 ImageData，本模块不碰 DOM / 不依赖 React；
 *   - 两向量差异抽象为可注入的 distanceFn（默认归一化欧氏距离），便于纯逻辑单测；
 *   - ts 均由调用方传入（不依赖 Date.now() 内部取时），可注入任意时间轴。
 *
 * 护栏：diffThreshold=0.08、eventCooldownMs=15000（同类事件冷却）、
 * maxClipsPerHour=12（滑窗 1 小时打包上限）。
 */
export type SampledVector = number[];

/** 两向量差异函数；默认实现为 L2 归一化欧氏距离（除以维度，量纲不随网格大小漂移） */
export type DistanceFn = (a: SampledVector, b: SampledVector) => number;

/** 视觉事件类型全量枚举；本类实现 scene_change/user_action/user_left/user_returned，其余供上层挂载 */
export type VisionEventType =
  | 'scene_change'
  | 'user_action'
  | 'emotion_shift'
  | 'focus_mode'
  | 'user_idle'
  | 'user_left'
  | 'user_returned'
  | 'sleep_detected';

export interface VisionEvent {
  type: VisionEventType;
  ts: number;
  source: 'camera' | 'screen';
  /** 帧差异原始幅值（供上层分档参考） */
  magnitude?: number;
  /** 中变化标志：低频关注类事件置 true，提示上层降低优先级处理 */
  lowPriority?: boolean;
}

export interface VisionEventDetectorOptions {
  /** 相邻帧「静止」判定阈值，低于它视为画面静止跳过；默认 0.08 */
  diffThreshold?: number;
  /** 突变阈值，达到它触发 scene_change 打包；默认 0.35 */
  abruptThreshold?: number;
  /** 微变化/中变化分界，位于 diffThreshold 与 abruptThreshold 之间；默认 0.16 */
  microThreshold?: number;
  /** 同类事件冷却（毫秒），冷却期内同类事件不重复触发；默认 15000 */
  eventCooldownMs?: number;
  /** 每小时打包上限，滑窗 1 小时超过则拒绝触发；默认 12 */
  maxClipsPerHour?: number;
  /** 距离函数，可注入以适配不同降采样表示；默认 L2 归一化欧氏距离 */
  distanceFn?: DistanceFn;
}

/** 默认 L2 归一化欧氏距离：sqrt(Σ(a-b)²/n)，n 为维度数 */
export function l2NormalizedDistance(a: SampledVector, b: SampledVector): number {
  const n = a.length;
  if (n === 0) return 0;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0);
    sum += d * d;
  }
  return Math.sqrt(sum / n);
}

const HOUR_MS = 3_600_000;

export class VisionEventDetector {
  readonly diffThreshold: number;
  readonly abruptThreshold: number;
  readonly microThreshold: number;
  readonly eventCooldownMs: number;
  readonly maxClipsPerHour: number;
  readonly distanceFn: DistanceFn;

  /** 各类事件最近一次发出的时间戳（不同类型独立冷却） */
  private readonly lastEmittedAt = new Map<VisionEventType, number>();
  /** 已计入打包预算的触发时间戳（滑窗去旧） */
  private readonly hitTimestamps: number[] = [];
  /** 当前用户在场状态（undefined 表示未知，便于首次调用按边沿触发） */
  private presenceActive: boolean | undefined = undefined;

  constructor(options: VisionEventDetectorOptions = {}) {
    this.diffThreshold = options.diffThreshold ?? 0.08;
    this.abruptThreshold = options.abruptThreshold ?? 0.35;
    this.microThreshold = options.microThreshold ?? 0.16;
    this.eventCooldownMs = options.eventCooldownMs ?? 15_000;
    this.maxClipsPerHour = options.maxClipsPerHour ?? 12;
    this.distanceFn = options.distanceFn ?? l2NormalizedDistance;
  }

  /**
   * 核心方法：比较相邻帧差异并按幅值分级。
   * 返回值：
   *   - 静止（diff < diffThreshold）→ null；
   *   - 突变（diff >= abruptThreshold）→ scene_change，触发打包；
   *   - 中变化（diff >= microThreshold）→ user_action（低频标志 lowPriority）；
   *   - 微变化（其余区间）→ null（忽略，但不把画面推进为「静止」态）。
   */
  feed(
    prevFrame: SampledVector,
    currFrame: SampledVector,
    now: number,
    source: 'camera' | 'screen',
  ): VisionEvent | null {
    const diff = this.distanceFn(prevFrame, currFrame);

    // 静止：差异低于静态阈值 → 无事件，画面为完全静止
    if (diff < this.diffThreshold) return null;

    // 突变：切窗/场景跳转/大动作 → 值得打包视频，走 clip 预算
    if (diff >= this.abruptThreshold) {
      return this.tryEmit('scene_change', now, source, diff, false);
    }

    // 中变化：滚动/打字等 → 低频关注，标记 lowPriority，走 clip 预算
    if (diff >= this.microThreshold) {
      return this.tryEmit('user_action', now, source, diff, true);
    }

    // 微变化：光标/鼠标等 → 忽略（返回 null），但此帧确有活动，
    // 不把画面推进为「静止」态（避免微小移动被当成全静而丢失后续上下文）。
    return null;
  }

  /**
   * 用户在场状态切换辅助：active=false → user_left，active=true → user_returned。
   * 仅边沿触发（状态未变化返回 null），走冷却但不消耗打包预算。
   */
  feedPresence(active: boolean, now: number, source: 'camera' | 'screen'): VisionEvent | null {
    if (active === this.presenceActive) return null; // 状态未翻转，忽略重复调用
    this.presenceActive = active;
    const type: VisionEventType = active ? 'user_returned' : 'user_left';
    return this.tryEmit(type, now, source, undefined, false, false);
  }

  /** 当前滑窗 1 小时内已计入的打包触发数 */
  getHourlyCount(now: number): number {
    const cutoff = now - HOUR_MS;
    let count = 0;
    for (const t of this.hitTimestamps) {
      if (t > cutoff) count++;
    }
    return count;
  }

  /** 判断当前是否允许再触发一次打包（未超每小时上限） */
  canTrigger(now: number): boolean {
    return this.getHourlyCount(now) < this.maxClipsPerHour;
  }

  /** 复位全部内部状态（冷却时间戳、打包预算、在场状态） */
  reset(): void {
    this.lastEmittedAt.clear();
    this.hitTimestamps.length = 0;
    this.presenceActive = undefined;
  }

  /**
   * 统一发射口：先过冷却闸（同类事件独立）、再过打包预算闸（clip 类事件），
   * countTowardLimit=false 时（presence 事件）不消耗打包预算。
   */
  private tryEmit(
    type: VisionEventType,
    now: number,
    source: 'camera' | 'screen',
    magnitude: number | undefined,
    lowPriority: boolean,
    countTowardLimit = true,
  ): VisionEvent | null {
    const last = this.lastEmittedAt.get(type);
    if (last !== undefined && now - last < this.eventCooldownMs) return null; // 冷却期内同类不重复
    if (countTowardLimit && !this.canTrigger(now)) return null; // 每小时上限已达，拒绝触发
    this.lastEmittedAt.set(type, now);
    if (countTowardLimit) this.tryPrune(now);
    return {
      type,
      ts: now,
      source,
      magnitude,
      ...(lowPriority ? { lowPriority: true } : {}),
    };
  }

  /** 追加打包时间戳并淘汰窗外的旧时间戳，防止数组无限增长 */
  private tryPrune(now: number): void {
    const cutoff = now - HOUR_MS;
    this.hitTimestamps.push(now);
    while (this.hitTimestamps.length > 0 && this.hitTimestamps[0] <= cutoff) {
      this.hitTimestamps.shift();
    }
  }
}