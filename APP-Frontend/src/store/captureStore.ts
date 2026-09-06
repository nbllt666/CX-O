/**
 * 视觉采集状态存储（Task 4 / Task 6 共享契约文件，接口冻结）。
 *
 * 边界划分（tasks.md 执行期约束）：
 * - Task 4 负责屏幕/摄像头采集实现与开关状态管理、桌宠侧开关与状态指示；
 * - Task 6 负责设置页开关 UI，复用本存储，不另建状态层。
 *
 * 硬性约束（checklist「视觉采集与开关」）：
 * - screenActive / cameraActive 为会话内状态，刻意不持久化 —— 默认关闭、重启不自动恢复；
 * - frameMode / frameIntervalSec / frameDutyCycle 持久化（发送节奏偏好）。
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

export const MIN_FRAME_DUTY_CYCLE = 10;
export const MAX_FRAME_DUTY_CYCLE = 90;

/** 自适应占空比钳制：取整并钳到 [10,90]；NaN 按默认 50 兜底（对齐 clampFrameIntervalSec 范式） */
export function clampFrameDutyCycle(v: number): number {
  if (Number.isNaN(v)) return 50;
  return Math.min(MAX_FRAME_DUTY_CYCLE, Math.max(MIN_FRAME_DUTY_CYCLE, Math.round(v)));
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
  /** 帧筛选开关：开启后单帧先经 /api/vision/frame 三态判定再分流（持久化，默认关，对齐 videoModeEnabled 范式） */
  frameFilterEnabled: boolean;
  /** 画面帧发送节奏：手动点发 / 定时抽帧 / 自适应（持久化） */
  frameMode: CaptureFrameMode;
  /** 定时抽帧间隔秒数 1~60（持久化） */
  frameIntervalSec: number;
  /** 自适应抽帧占空比百分比 10~90（持久化）：adaptive 曲线锚点 t=1-duty/100，越大越积极跟随变化、越小越省带宽；默认 50 与历史行为一致 */
  frameDutyCycle: number;
  setScreenActive: (v: boolean) => void;
  setCameraActive: (v: boolean) => void;
  setVisionEnabled: (v: boolean) => void;
  setVideoModeEnabled: (v: boolean) => void;
  setFrameFilterEnabled: (v: boolean) => void;
  setFrameMode: (v: CaptureFrameMode) => void;
  setFrameIntervalSec: (v: number) => void;
  setFrameDutyCycle: (v: number) => void;
}

export const useCaptureStore = create<CaptureState>()(
  persist(
    (set) => ({
      screenActive: false,
      cameraActive: false,
      visionEnabled: false,
      videoModeEnabled: false,
      frameFilterEnabled: false,
      frameMode: 'interval',
      frameIntervalSec: 5,
      frameDutyCycle: 50,

      setScreenActive: (v) => set({ screenActive: v }),
      setCameraActive: (v) => set({ cameraActive: v }),
      setVisionEnabled: (v) => set({ visionEnabled: v }),
      setVideoModeEnabled: (v) => set({ videoModeEnabled: v }),
      setFrameFilterEnabled: (v) => set({ frameFilterEnabled: v }),
      setFrameMode: (v) => set({ frameMode: v }),
      setFrameIntervalSec: (v) => set({ frameIntervalSec: clampFrameIntervalSec(v) }),
      setFrameDutyCycle: (v) => set({ frameDutyCycle: clampFrameDutyCycle(v) }),
    }),
    {
      name: CAPTURE_STORE_NAME,
      storage: createStorage(),
      // 持久化总开关与节奏偏好；采集开启状态绝不落盘（重启不自动恢复）
      partialize: (state) => ({
        visionEnabled: state.visionEnabled,
        videoModeEnabled: state.videoModeEnabled,
        frameFilterEnabled: state.frameFilterEnabled,
        frameMode: state.frameMode,
        frameIntervalSec: state.frameIntervalSec,
        frameDutyCycle: state.frameDutyCycle,
      }),
      merge: (persisted, current) => {
        const p = (persisted as Partial<CaptureState>) || {};
        return {
          ...current,
          visionEnabled: p.visionEnabled ?? current.visionEnabled,
          videoModeEnabled: p.videoModeEnabled ?? current.videoModeEnabled,
          frameFilterEnabled: p.frameFilterEnabled ?? current.frameFilterEnabled,
          // 旧持久化可能写入未知 frameMode，安全回退 interval，避免下游收到未定义档位
          frameMode: isCaptureFrameMode(p.frameMode) ? p.frameMode : 'interval',
          frameIntervalSec: clampFrameIntervalSec(p.frameIntervalSec ?? current.frameIntervalSec),
          // 旧持久化档无 frameDutyCycle 字段时回填默认 50（行为与现状一致）
          frameDutyCycle: clampFrameDutyCycle(p.frameDutyCycle ?? current.frameDutyCycle),
        };
      },
    },
  ),
);
