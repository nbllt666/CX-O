/**
 * OBS 采集状态存储（Task 9：OBS 采集桌宠支持）。
 *
 * 职责：
 * - 抠像背景模式开关（greenScreen）：由 PetPage 组件内 useState 提升至此，
 *   全量持久化（Electron 落 userData 文件、浏览器回退 localStorage），
 *   设置页等外部消费方可直接读取（SubTask 9.2）。
 * - 采集尺寸预设（captureWidth / captureHeight）：持久化记录当前采集尺寸，
 *   Electron 下由 PetPage 经 setWindowSize IPC 应用到桌宠窗（SubTask 9.3）。
 *
 * 头像自适应策略（纯函数，便于单测）：
 * - Electron 模式：窗口已按预设 setSize，Live2D/VRM 引擎随容器重排自适应，
 *   缩放因子取 1——若再乘比例因子会与引擎自适应叠加导致双重缩放、头像被裁；
 * - 浏览器模式：渲染层无窗口控制权，降级为仅按预设比例缩放头像
 *   （computeAvatarScaleFactor，基准 400x500，clamp [0.5, 2]）。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';

export const OBS_STORE_NAME = 'cxo-pet-obs';

/** 采集尺寸基准（与 main.ts 桌宠窗默认尺寸一致） */
export const CAPTURE_BASE_WIDTH = 400;
export const CAPTURE_BASE_HEIGHT = 500;
/** 采集尺寸下限（与 main.ts 桌宠窗 minWidth/minHeight 一致） */
export const CAPTURE_MIN_WIDTH = 300;
export const CAPTURE_MIN_HEIGHT = 400;
/** 头像自适应缩放因子上下限（防极端自定义尺寸把头像压没或撑爆） */
export const AVATAR_SCALE_FACTOR_MIN = 0.5;
export const AVATAR_SCALE_FACTOR_MAX = 2;

export interface CaptureSize {
  width: number;
  height: number;
}

export interface CaptureSizePreset extends CaptureSize {
  id: string;
}

/** 采集尺寸预设档（升序；循环切换按数组顺序推进，含 spec 点名的 400x500 / 550x700） */
export const CAPTURE_SIZE_PRESETS: CaptureSizePreset[] = [
  { id: '300x400', width: 300, height: 400 },
  { id: '400x500', width: 400, height: 500 },
  { id: '550x700', width: 550, height: 700 },
  { id: '640x800', width: 640, height: 800 },
];

export const DEFAULT_CAPTURE_SIZE: CaptureSize = { width: 400, height: 500 };

/** 尺寸合法化：非有限数回落默认，取整后夹到下限之上 */
export function clampCaptureSize(width: number, height: number): CaptureSize {
  const w = Number.isFinite(width) ? Math.round(width) : DEFAULT_CAPTURE_SIZE.width;
  const h = Number.isFinite(height) ? Math.round(height) : DEFAULT_CAPTURE_SIZE.height;
  return {
    width: Math.max(CAPTURE_MIN_WIDTH, w),
    height: Math.max(CAPTURE_MIN_HEIGHT, h),
  };
}

/** 头像缩放因子：短边比例（min(w/400, h/500)），clamp [0.5, 2]；非法输入取 1（不缩放） */
export function computeAvatarScaleFactor(width: number, height: number): number {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return 1;
  }
  const raw = Math.min(width / CAPTURE_BASE_WIDTH, height / CAPTURE_BASE_HEIGHT);
  return Math.min(AVATAR_SCALE_FACTOR_MAX, Math.max(AVATAR_SCALE_FACTOR_MIN, raw));
}

/**
 * 头像自适应缩放决策：
 * - windowResizeApplied = true（Electron：窗口已 setSize）→ 1，交由引擎随容器自适应；
 * - false（浏览器降级路径）→ 按预设比例缩放头像。
 */
export function resolveAvatarScale(
  width: number,
  height: number,
  windowResizeApplied: boolean,
): number {
  return windowResizeApplied ? 1 : computeAvatarScaleFactor(width, height);
}

/** 循环切换：当前尺寸命中预设则推进到下一档（末尾回卷）；未命中（自定义值）回落默认档 */
export function getNextCaptureSize(width: number, height: number): CaptureSize {
  const index = CAPTURE_SIZE_PRESETS.findIndex(
    (p) => p.width === width && p.height === height,
  );
  if (index < 0) {
    return { ...DEFAULT_CAPTURE_SIZE };
  }
  const next = CAPTURE_SIZE_PRESETS[(index + 1) % CAPTURE_SIZE_PRESETS.length];
  return { width: next.width, height: next.height };
}

interface ObsState {
  /** 抠像背景模式：true = 绿幕（#00ff00），false = 透明 */
  greenScreen: boolean;
  /** 当前采集尺寸（持久化；Electron 下重启后经 PetPage 效果重新应用到窗口） */
  captureWidth: number;
  captureHeight: number;
  setGreenScreen: (v: boolean) => void;
  toggleGreenScreen: () => void;
  setCaptureSize: (width: number, height: number) => void;
  /** 右键菜单循环切换入口：推进到下一档预设 */
  cycleCaptureSize: () => void;
}

export const useObsStore = create<ObsState>()(
  persist(
    (set) => ({
      greenScreen: false,
      captureWidth: DEFAULT_CAPTURE_SIZE.width,
      captureHeight: DEFAULT_CAPTURE_SIZE.height,

      setGreenScreen: (v) => set({ greenScreen: v }),
      toggleGreenScreen: () => set((state) => ({ greenScreen: !state.greenScreen })),
      setCaptureSize: (width, height) => {
        const size = clampCaptureSize(width, height);
        set({ captureWidth: size.width, captureHeight: size.height });
      },
      cycleCaptureSize: () =>
        set((state) => {
          const next = getNextCaptureSize(state.captureWidth, state.captureHeight);
          return { captureWidth: next.width, captureHeight: next.height };
        }),
    }),
    {
      name: OBS_STORE_NAME,
      storage: createStorage(),
      merge: (persisted, current) => {
        const p = (persisted as Partial<ObsState>) || {};
        const size = clampCaptureSize(
          p.captureWidth ?? current.captureWidth,
          p.captureHeight ?? current.captureHeight,
        );
        return {
          ...current,
          ...p,
          greenScreen: typeof p.greenScreen === 'boolean' ? p.greenScreen : current.greenScreen,
          captureWidth: size.width,
          captureHeight: size.height,
        };
      },
    },
  ),
);
