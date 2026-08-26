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
 * - adaptive 模式：每拍抽一帧按画面变化度动态算间隔（变化大→更频繁），
 *   环境不支持像素差异计算时自动退化为 interval 行为（用 intervalSec 定时）。
 * - manual 模式：仅 sendNow() 触发；手动是显式意图，不做静止去重。
 *
 * 上行互斥：canSend 返回 false（如对话进行中）时本拍跳过，避免并发流式会话。
 * 资源：卸载/模式切换/源关闭时清理节拍器，无泄漏。
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  computeAdaptiveIntervalSec,
  computeChangeMagnitude,
  isDuplicateFrame,
  pickActiveFrameSource,
  shouldSendByInterval,
} from './frameThrottle';
import type { FrameSource } from './frameThrottle';
import type { CaptureSourceKind } from './useVideoCapture';

/**
 * adaptive 模式动态间隔的生产者。
 *
 * - 入参：当前帧 dataURL、上次成功发送帧 dataURL（可为 null）、基准间隔秒；
 * - 返回：本拍应采用的最小发送间隔（秒），非正数表示每次放行；
 * - 承诺：不抛错。任何异常/无法比对的降级都收敛为「返回 baseIntervalSec」，
 *   即退化为 interval 行为；
 * - 注入点：UseFrameSenderOptions.adaptiveIntervalProvider。真实现走
 *   computeChangeMagnitude + computeAdaptiveIntervalSec；测试可注入确定性 producer。
 */
export type AdaptiveIntervalProvider = (
  dataUrl: string,
  prevDataUrl: string | null,
  baseIntervalSec: number,
) => Promise<number>;

/** 默认生产者：随画面变化度动态调整间隔；变化度不可算（=0 或抛错）→ 退化固定间隔 */
export async function defaultAdaptiveIntervalProvider(
  dataUrl: string,
  prevDataUrl: string | null,
  baseIntervalSec: number,
): Promise<number> {
  let magnitude: number;
  try {
    magnitude = await computeChangeMagnitude(dataUrl, prevDataUrl);
  } catch {
    return baseIntervalSec; // 环境不支持像素差异计算 → 退化 interval
  }
  if (magnitude === 0) return baseIntervalSec; // 无从比较/降级 0 → 退化 interval
  return computeAdaptiveIntervalSec({ baseIntervalSec, magnitude });
}

export interface UseFrameSenderOptions {
  /** 帧源列表，按优先级降序（屏幕 > 摄像头） */
  sources: FrameSource[];
  /** 发送节奏模式（captureStore.frameMode，放开含 adaptive） */
  mode: 'manual' | 'interval' | 'adaptive';
  /** 定时抽帧间隔秒（captureStore.frameIntervalSec，已被 store 钳制 1~60） */
  intervalSec: number;
  /** 实际上行出口：帧 dataURL + 来源（PetPage 注入对话图像链路） */
  sendFrame: (dataUrl: string, kind: CaptureSourceKind) => void;
  /** 上行互斥闸：返回 false 时本拍跳过（如对话流式进行中）；缺省恒可发 */
  canSend?: () => boolean;
  /**
   * adaptive 模式的动态间隔生产者（可选）。缺省用 defaultAdaptiveIntervalProvider
   * （computeChangeMagnitude + computeAdaptiveIntervalSec）。测试可注入确定性实现，
   * 以便不依赖 canvas/jsdom 也能验证 adaptive 分支的裁决行为。
   */
  adaptiveIntervalProvider?: AdaptiveIntervalProvider;
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
  adaptiveIntervalProvider,
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
  const adaptiveIntervalProviderRef = useRef<AdaptiveIntervalProvider | undefined>(adaptiveIntervalProvider);
  adaptiveIntervalProviderRef.current = adaptiveIntervalProvider;
  const lastSentAtRef = useRef<number | null>(null);
  const lastSentDataUrlRef = useRef<string | null>(null);
  // 自适应抽帧串行闸：上一拍 async（动态间隔计算 + 发送）未完成时跳过本拍，避免重叠抓帧/并发写 lastSent*
  const adaptiveInFlightRef = useRef(false);

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

  // 定时抽帧：interval/adaptive 模式均启用 1s 节拍器；manual 不启用。
  // 每拍做间隔裁决；adaptive 额外按画面变化度算动态间隔。
  useEffect(() => {
    if (mode === 'manual') return;

    // interval：每拍满 intervalSec 且非重复帧才发送（回归：行为保持不变）
    if (mode === 'interval') {
      const timer = setInterval(() => {
        const now = Date.now();
        if (!shouldSendByInterval(now, lastSentAtRef.current, intervalSecRef.current)) return;
        grabAndSend(true);
      }, TICK_MS);
      return () => clearInterval(timer);
    }

    // adaptive：每拍用同一帧 dataUrl 做间隔决策并发送，避免「决策帧」与「发送帧」不一致；
    // 用 adaptiveInFlightRef 串行化：上一拍 async（动态间隔计算 + 发送）未完结时跳过本拍。
    const timer = setInterval(() => {
      if (adaptiveInFlightRef.current) return;
      const source = pickActiveFrameSource(sourcesRef.current);
      if (!source) return; // 未激活/未就绪不硬采
      const dataUrl = source.captureFrame();
      if (!dataUrl) return;
      // 静止去重：与上次成功发送帧一致则跳过（沿用 grabAndSend 的去重语义）
      if (isDuplicateFrame(dataUrl, lastSentDataUrlRef.current)) return;
      const now = Date.now();
      adaptiveInFlightRef.current = true;
      // computeChangeMagnitude 是 async，环境不支持时可降级 0 或抛错；
      // 生产者在 try/catch 内被防御，任何异常退化为 interval
      void (async () => {
        try {
          const provider = adaptiveIntervalProviderRef.current ?? defaultAdaptiveIntervalProvider;
          let adaptiveIntervalSec: number;
          try {
            adaptiveIntervalSec = await provider(dataUrl, lastSentDataUrlRef.current, intervalSecRef.current);
          } catch {
            adaptiveIntervalSec = intervalSecRef.current; // 生产者抛错/环境不支持 → 退化 interval
          }
          if (!shouldSendByInterval(now, lastSentAtRef.current, adaptiveIntervalSec)) return;
          // 互斥闸：对话流式进行中跳过（与 interval/manual 分支同语义）
          if (canSendRef.current && !canSendRef.current()) return;
          // 发送决策所用的同一帧 dataUrl，不再二次抓帧
          sendFrameRef.current(dataUrl, source.kind);
          const sentAt = Date.now();
          lastSentAtRef.current = sentAt;
          lastSentDataUrlRef.current = dataUrl;
          setLastSentAt(sentAt);
        } finally {
          adaptiveInFlightRef.current = false;
        }
      })();
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [mode, grabAndSend]);

  return { sendNow, lastSentAt };
}

export default useFrameSender;
