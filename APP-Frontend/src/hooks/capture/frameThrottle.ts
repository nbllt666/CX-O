/**
 * 画面帧发送节奏裁决（纯逻辑，SubTask 4.8）。
 *
 * 节奏模型（checklist「视觉采集与开关」：发送节奏可控，避免持续占用带宽）：
 * - manual   仅手动点发（sendNow），不做间隔判定；
 * - interval 定时抽帧，距上次成功发送满 intervalSec 秒才放行下一帧；
 * - 画面静止去重：与上次成功发送的帧 dataURL 完全一致则跳过
 *   （屏幕静止时重复上传同一张图没有信息量，纯耗带宽）。
 *
 * 帧源优先级：调用方按优先级排序传入（屏幕 > 摄像头），每次发送取
 * 第一个激活源——双源同开时屏幕画面信息量更大，且避免一帧双发。
 */
import type { CaptureSourceKind } from './useVideoCapture';

export interface FrameSource {
  kind: CaptureSourceKind;
  /** 采集进行中（captureStore.screenActive / cameraActive 且流已建立） */
  active: boolean;
  /** 抓取当前帧 JPEG dataURL；未就绪返回 null */
  captureFrame: () => string | null;
}

/** 取第一个激活帧源（sources 按优先级降序传入）；无激活源返回 null */
export function pickActiveFrameSource(sources: FrameSource[]): FrameSource | null {
  for (const source of sources) {
    if (source.active) return source;
  }
  return null;
}

/**
 * 定时间隔判定：距上次成功发送满 intervalSec 秒放行。
 * 从未发送过（lastSentAt=null）立即放行首帧；intervalSec 非正数时
 * 按 0 处理（每次都放行），下限钳制归 captureStore。
 */
export function shouldSendByInterval(
  now: number,
  lastSentAt: number | null,
  intervalSec: number,
): boolean {
  if (lastSentAt === null) return true;
  const intervalMs = Math.max(0, intervalSec) * 1000;
  return now - lastSentAt >= intervalMs;
}

/** 画面静止去重：与上次成功发送帧完全一致视为重复（首帧不算重复） */
export function isDuplicateFrame(dataUrl: string, lastSentDataUrl: string | null): boolean {
  if (lastSentDataUrl === null) return false;
  return dataUrl === lastSentDataUrl;
}

// ── 自适应发送频率（SubTask 扩展）：随画面变化度动态调整间隔 ──
// 画面变化大 → 更频繁发送；画面稳定 → 更松间隔省带宽。

/** 变化度量纲：8×6 极小灰度网格（比 useVisionPipeline 的 16×12 更省成本，仅用于差异粗估） */
const CHANGE_GRID_W = 8;
const CHANGE_GRID_H = 6;

/**
 * 纯函数：两帧等长灰度向量间的归一化平均绝对差 ∈[0,1]。
 * 0 = 全同，1 = 全异。长度不一致或空向量返回 0（无从比较）。
 * 抽成独立纯函数以便在无 DOM 环境下确定性单测像素差异路径。
 */
export function magnitudeFromGrays(grayA: number[], grayB: number[]): number {
  if (grayA.length === 0 || grayA.length !== grayB.length) return 0;
  let sum = 0;
  for (let i = 0; i < grayA.length; i++) {
    sum += Math.abs(grayA[i] - grayB[i]);
  }
  return Math.min(1, sum / grayA.length / 255);
}

/** 把 dataURL 绘制到极小网格画布，提取灰度向量；不支持 canvas 或解码失败返回 null */
async function graysFromDataUrl(dataUrl: string): Promise<number[] | null> {
  if (typeof document === 'undefined') return null;
  if (typeof Image === 'undefined') return null;
  // 先探测 2d canvas 可用性：jsdom 等无原生 canvas 的环境 getContext 返回 null，
  // 此时直接降级，避免空等 Image.onload/onerror 永不触发导致挂起。
  const canvas = document.createElement('canvas');
  canvas.width = CHANGE_GRID_W;
  canvas.height = CHANGE_GRID_H;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null; // 环境不支持 2d canvas → 降级
  const img = await new Promise<HTMLImageElement | null>((resolve) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = dataUrl;
  });
  if (!img) return null;
  ctx.drawImage(img, 0, 0, CHANGE_GRID_W, CHANGE_GRID_H);
  const { data } = ctx.getImageData(0, 0, CHANGE_GRID_W, CHANGE_GRID_H);
  const gray: number[] = new Array(CHANGE_GRID_W * CHANGE_GRID_H);
  for (let i = 0, j = 0; i < data.length; i += 4, j++) {
    // 灰度（Rec.601 luma），比单取 R 通道更抗色偏
    gray[j] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
  }
  return gray;
}

/**
 * 两帧 dataURL 间的变化度 ∈[0,1]。**async**（涉及 Image/canvas 异步解码）。
 * - 无前帧（`prevDataUrl===null`）→ 0（无从比较）；
 * - 两帧 dataURL 完全一致 → 0（快速路径）；
 * - 环境不支持 canvas（`document` 缺失或 `getContext('2d')` 为 null）→ 降级 0，**不抛错**；
 * - 否则绘制到 8×6 极小网格，取灰度向量计算归一化平均绝对差（同 changeType 语义）。
 */
export async function computeChangeMagnitude(dataUrl: string, prevDataUrl: string | null): Promise<number> {
  if (prevDataUrl === null) return 0;
  if (dataUrl === prevDataUrl) return 0;
  const [grayA, grayB] = await Promise.all([graysFromDataUrl(dataUrl), graysFromDataUrl(prevDataUrl)]);
  if (!grayA || !grayB) return 0;
  return magnitudeFromGrays(grayA, grayB);
}

/** computeAdaptiveIntervalSec 的入参 */
export interface AdaptiveIntervalOpts {
  /** 参考基准间隔（秒），画面变化在中间态时的收敛点 */
  baseIntervalSec: number;
  /** 画面变化度 ∈[0,1]，由 computeChangeMagnitude 得到 */
  magnitude: number;
  /** 下限秒（默认 1，≈MIN_FRAME_INTERVAL_SEC） */
  minSec?: number;
  /** 上限秒（默认 60，≈MAX_FRAME_INTERVAL_SEC） */
  maxSec?: number;
}

/**
 * 由画面变化度计算自适应发送间隔（秒）。纯函数、无副作用。
 * 以 baseIntervalSec 为中心的分段线性映射：magnitude=0 → maxSec、0.5 → base、1 → minSec，
 * 全程在 [minSec,maxSec] 内单调递减（变化越激烈 → 发送越频繁）。
 * magnitude 钳制 [0,1]；min/max 乱序自动交换；非法输入按保守（最松）处理。
 */
export function computeAdaptiveIntervalSec(opts: AdaptiveIntervalOpts): number {
  const { baseIntervalSec, magnitude } = opts;
  const minSec = opts.minSec ?? 1;
  const maxSec = opts.maxSec ?? 60;
  const floor = Math.min(minSec, maxSec);
  const ceil = Math.max(minSec, maxSec);
  const m = Math.min(1, Math.max(0, Number.isFinite(magnitude) ? magnitude : 0));
  const base = Number.isFinite(baseIntervalSec)
    ? Math.min(ceil, Math.max(floor, baseIntervalSec))
    : ceil;
  if (m <= 0.5) {
    // [0, 0.5]：maxSec → base 线性下降
    return ceil - (ceil - base) * (m / 0.5);
  }
  // (0.5, 1]：base → minSec 线性下降
  return base - (base - floor) * ((m - 0.5) / 0.5);
}
