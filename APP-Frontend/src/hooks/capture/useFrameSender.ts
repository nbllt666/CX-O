/**
 * useFrameSender — 画面帧发送链路（SubTask 4.8）。
 *
 * 链路：激活帧源（useVideoCapture.captureFrame）→ 节奏裁决（frameThrottle）
 *       → sendFrame 注入函数（PetPage：对话图像链路 /api/chat/stream images 上行）。
 *
 * 节奏：
 * - interval 模式：每拍检查一次（1s 节拍），满 intervalSec 且非重复帧才发送；
 *   用 1s 节拍而非 intervalSec 长定时器——间隔改动即时生效，且无需为
 *   「上次发送时间」重建定时器。
 * - manual 模式：仅 sendNow() 触发；手动是显式意图，不做静止去重。
 *
 * 上行互斥：canSend 返回 false（如对话进行中）时本拍跳过，避免并发流式会话。
 * 资源：卸载/模式切换/源关闭时清理节拍器，无泄漏。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { isDuplicateFrame, pickActiveFrameSource, shouldSendByInterval } from './frameThrottle';
import type { FrameSource } from './frameThrottle';
import type { CaptureSourceKind } from './useVideoCapture';

export interface UseFrameSenderOptions {
  /** 帧源列表，按优先级降序（屏幕 > 摄像头） */
  sources: FrameSource[];
  /** 发送节奏模式（captureStore.frameMode） */
  mode: 'manual' | 'interval';
  /** 定时抽帧间隔秒（captureStore.frameIntervalSec，已被 store 钳制 1~60） */
  intervalSec: number;
  /** 实际上行出口：帧 dataURL + 来源（PetPage 注入对话图像链路） */
  sendFrame: (dataUrl: string, kind: CaptureSourceKind) => void;
  /** 上行互斥闸：返回 false 时本拍跳过（如对话流式进行中）；缺省恒可发 */
  canSend?: () => boolean;
}

export interface UseFrameSenderReturn {
  /** 手动点发：有帧实际发出返回 true（无激活源/帧未就绪/被互斥跳过返回 false） */
  sendNow: () => boolean;
  /** 最近一次成功发送时间戳（ms），未发送过为 null */
  lastSentAt: number | null;
}

/** 定时模式检查节拍：1s 一拍，兼顾 intervalSec=1 下限与改动即时生效 */
const TICK_MS = 1000;

export function useFrameSender({
  sources,
  mode,
  intervalSec,
  sendFrame,
  canSend,
}: UseFrameSenderOptions): UseFrameSenderReturn {
  const [lastSentAt, setLastSentAt] = useState<number | null>(null);

  const sourcesRef = useRef(sources);
  sourcesRef.current = sources;
  const sendFrameRef = useRef(sendFrame);
  sendFrameRef.current = sendFrame;
  const canSendRef = useRef(canSend);
  canSendRef.current = canSend;
  const intervalSecRef = useRef(intervalSec);
  intervalSecRef.current = intervalSec;
  const lastSentAtRef = useRef<number | null>(null);
  const lastSentDataUrlRef = useRef<string | null>(null);

  /** 抓帧并上行；applyDedupe=false 时跳过静止去重（手动点发） */
  const grabAndSend = useCallback((applyDedupe: boolean): boolean => {
    if (canSendRef.current && !canSendRef.current()) return false;
    const source = pickActiveFrameSource(sourcesRef.current);
    if (!source) return false;
    const dataUrl = source.captureFrame();
    if (!dataUrl) return false;
    if (applyDedupe && isDuplicateFrame(dataUrl, lastSentDataUrlRef.current)) return false;

    sendFrameRef.current(dataUrl, source.kind);
    const now = Date.now();
    lastSentAtRef.current = now;
    lastSentDataUrlRef.current = dataUrl;
    setLastSentAt(now);
    return true;
  }, []);

  const sendNow = useCallback((): boolean => grabAndSend(false), [grabAndSend]);

  // 定时抽帧：仅 interval 模式启用节拍器；每拍做间隔 + 去重裁决
  useEffect(() => {
    if (mode !== 'interval') return;
    const timer = setInterval(() => {
      const now = Date.now();
      if (!shouldSendByInterval(now, lastSentAtRef.current, intervalSecRef.current)) return;
      grabAndSend(true);
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [mode, grabAndSend]);

  return { sendNow, lastSentAt };
}

export default useFrameSender;
