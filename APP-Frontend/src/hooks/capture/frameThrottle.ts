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
