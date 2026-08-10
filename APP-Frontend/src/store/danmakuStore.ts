/**
 * 弹幕窗状态存储：显隐记忆、置顶、背景不透明度、暂停滚动。
 * persist 经 createStorage() 在 Electron 下落 userData 文件、浏览器落 localStorage。
 *
 * 设计说明：
 * - visible 记录「用户期望弹幕窗可见」，供重启恢复；渲染层挂载时上报 true，
 *   用户主动隐藏时置 false。主进程启动时读取本存储并创建弹幕窗属主进程侧改动，
 *   当前为 IPC 缺口（见 DanmakuPage 注释与汇报）。
 * - 鼠标穿透（clickThrough）刻意不持久化：重启后默认关闭穿透，
 *   避免托盘/全局快捷键恢复入口未就位时窗口永久不可交互。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';

export const DANMAKU_STORE_NAME = 'cxo-pet-danmaku';

/** 背景不透明度下限：保留最低可读性，避免用户滑到全透明后找不到窗口 */
export const MIN_BACKGROUND_OPACITY = 0.1;
export const MAX_BACKGROUND_OPACITY = 1;

export function clampBackgroundOpacity(v: number): number {
  if (Number.isNaN(v)) return MAX_BACKGROUND_OPACITY;
  return Math.min(MAX_BACKGROUND_OPACITY, Math.max(MIN_BACKGROUND_OPACITY, v));
}

interface DanmakuWindowState {
  /** 用户期望弹幕窗保持可见（重启恢复依据） */
  visible: boolean;
  /** 窗口置顶 */
  alwaysOnTop: boolean;
  /** 玻璃背景层不透明度 0.1~1（仅作用于背景层，不影响文字） */
  backgroundOpacity: number;
  /** 暂停滚动：开启时新弹幕进入缓存队列，恢复后补齐 */
  paused: boolean;
  setVisible: (v: boolean) => void;
  setAlwaysOnTop: (v: boolean) => void;
  setBackgroundOpacity: (v: number) => void;
  setPaused: (v: boolean) => void;
}

export const useDanmakuStore = create<DanmakuWindowState>()(
  persist(
    (set) => ({
      visible: false,
      alwaysOnTop: true,
      backgroundOpacity: MAX_BACKGROUND_OPACITY,
      paused: false,

      setVisible: (v) => set({ visible: v }),
      setAlwaysOnTop: (v) => set({ alwaysOnTop: v }),
      setBackgroundOpacity: (v) => set({ backgroundOpacity: clampBackgroundOpacity(v) }),
      setPaused: (v) => set({ paused: v }),
    }),
    {
      name: DANMAKU_STORE_NAME,
      storage: createStorage(),
      partialize: (state) => ({
        visible: state.visible,
        alwaysOnTop: state.alwaysOnTop,
        backgroundOpacity: state.backgroundOpacity,
        paused: state.paused,
      }),
      merge: (persisted, current) => {
        const p = (persisted as Partial<DanmakuWindowState>) || {};
        return {
          ...current,
          ...p,
          // 历史脏数据兜底：持久化值越界/缺失时收敛到合法区间
          backgroundOpacity: clampBackgroundOpacity(
            p.backgroundOpacity ?? current.backgroundOpacity,
          ),
        };
      },
    },
  ),
);
