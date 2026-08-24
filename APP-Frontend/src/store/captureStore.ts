/**
 * 视觉采集状态存储（Task 4 / Task 6 共享契约文件，接口冻结）。
 *
 * 边界划分（tasks.md 执行期约束）：
 * - Task 4 负责屏幕/摄像头采集实现与开关状态管理、桌宠侧开关与状态指示；
 * - Task 6 负责设置页开关 UI，复用本存储，不另建状态层。
 *
 * 硬性约束（checklist「视觉采集与开关」）：
 * - screenActive / cameraActive 为会话内状态，刻意不持久化 —— 默认关闭、重启不自动恢复；
 * - frameMode / frameIntervalSec 持久化（发送节奏偏好）。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';

export const CAPTURE_STORE_NAME = 'cxo-pet-capture';

export type CaptureFrameMode = 'manual' | 'interval' | 'adaptive';

/** 判断某值是否为合法的帧发送模式（merge 时对旧持久化未知值做安全回退） */
export function isCaptureFrameMode(v: unknown): v is CaptureFrameMode {
  return v === 'manual' || v === 'interval' || v === 'adaptive';
}

export const MIN_FRAME_INTERVAL_SEC = 1;
export const MAX_FRAME_INTERVAL_SEC = 60;

export function clampFrameIntervalSec(v: number): number {
  if (Number.isNaN(v)) return 5;
  return Math.min(MAX_FRAME_INTERVAL_SEC, Math.max(MIN_FRAME_INTERVAL_SEC, Math.round(v)));
}

interface CaptureState {
  /** 屏幕共享采集中（会话内，不持久化） */
  screenActive: boolean;
  /** 摄像头采集中（会话内，不持久化） */
  cameraActive: boolean;
  /** 主动视觉总开关：控制是否向后端发送画面帧（持久化，默认关） */
  visionEnabled: boolean;
  /** 重量级"视频叙事"管线开关：与 visionEnabled 图片轮询彼此独立（持久化，默认关，性能考虑） */
  videoModeEnabled: boolean;
  /** 画面帧发送节奏：手动点发 / 定时抽帧 / 自适应（持久化） */
  frameMode: CaptureFrameMode;
  /** 定时抽帧间隔秒数 1~60（持久化） */
  frameIntervalSec: number;
  setScreenActive: (v: boolean) => void;
  setCameraActive: (v: boolean) => void;
  setVisionEnabled: (v: boolean) => void;
  setVideoModeEnabled: (v: boolean) => void;
  setFrameMode: (v: CaptureFrameMode) => void;
  setFrameIntervalSec: (v: number) => void;
}

export const useCaptureStore = create<CaptureState>()(
  persist(
    (set) => ({
      screenActive: false,
      cameraActive: false,
      visionEnabled: false,
      videoModeEnabled: false,
      frameMode: 'interval',
      frameIntervalSec: 5,

      setScreenActive: (v) => set({ screenActive: v }),
      setCameraActive: (v) => set({ cameraActive: v }),
      setVisionEnabled: (v) => set({ visionEnabled: v }),
      setVideoModeEnabled: (v) => set({ videoModeEnabled: v }),
      setFrameMode: (v) => set({ frameMode: v }),
      setFrameIntervalSec: (v) => set({ frameIntervalSec: clampFrameIntervalSec(v) }),
    }),
    {
      name: CAPTURE_STORE_NAME,
      storage: createStorage(),
      // 持久化总开关与节奏偏好；采集开启状态绝不落盘（重启不自动恢复）
      partialize: (state) => ({
        visionEnabled: state.visionEnabled,
        videoModeEnabled: state.videoModeEnabled,
        frameMode: state.frameMode,
        frameIntervalSec: state.frameIntervalSec,
      }),
      merge: (persisted, current) => {
        const p = (persisted as Partial<CaptureState>) || {};
        return {
          ...current,
          visionEnabled: p.visionEnabled ?? current.visionEnabled,
          videoModeEnabled: p.videoModeEnabled ?? current.videoModeEnabled,
          // 旧持久化可能写入未知 frameMode，安全回退 interval，避免下游收到未定义档位
          frameMode: isCaptureFrameMode(p.frameMode) ? p.frameMode : 'interval',
          frameIntervalSec: clampFrameIntervalSec(p.frameIntervalSec ?? current.frameIntervalSec),
        };
      },
    },
  ),
);
