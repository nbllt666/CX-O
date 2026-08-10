/**
 * 音频设置存储（Task 4 / Task 6 共享契约文件，接口冻结）。
 *
 * 边界划分（tasks.md 执行期约束）：
 * - Task 4 负责消费本存储驱动实际采集/播放逻辑（麦克风增益、TTS 音量、弹幕播报开关）；
 * - Task 6 负责设置页 UI，仅读写本存储，不自行另建音频持久化层。
 *
 * 全部字段持久化（createStorage：Electron 落 userData 文件，浏览器回退 localStorage）。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';

export const AUDIO_STORE_NAME = 'cxo-pet-audio';

export function clampVolume(v: number): number {
  if (Number.isNaN(v)) return 1;
  return Math.min(1, Math.max(0, v));
}

/** 麦克风增益 0~2（1 为原始电平） */
export function clampMicGain(v: number): number {
  if (Number.isNaN(v)) return 1;
  return Math.min(2, Math.max(0, v));
}

interface AudioSettingsState {
  /** 麦克风上行开关（ASR 流） */
  micEnabled: boolean;
  /** TTS 播放音量 0~1 */
  ttsVolume: number;
  /** 麦克风增益 0~2 */
  micGain: number;
  /** 弹幕语音播报/回复开关 */
  danmakuVoiceEnabled: boolean;
  setMicEnabled: (v: boolean) => void;
  setTtsVolume: (v: number) => void;
  setMicGain: (v: number) => void;
  setDanmakuVoiceEnabled: (v: boolean) => void;
}

export const useAudioStore = create<AudioSettingsState>()(
  persist(
    (set) => ({
      micEnabled: false,
      ttsVolume: 1,
      micGain: 1,
      danmakuVoiceEnabled: false,

      setMicEnabled: (v) => set({ micEnabled: v }),
      setTtsVolume: (v) => set({ ttsVolume: clampVolume(v) }),
      setMicGain: (v) => set({ micGain: clampMicGain(v) }),
      setDanmakuVoiceEnabled: (v) => set({ danmakuVoiceEnabled: v }),
    }),
    {
      name: AUDIO_STORE_NAME,
      storage: createStorage(),
      merge: (persisted, current) => {
        const p = (persisted as Partial<AudioSettingsState>) || {};
        return {
          ...current,
          ...p,
          ttsVolume: clampVolume(p.ttsVolume ?? current.ttsVolume),
          micGain: clampMicGain(p.micGain ?? current.micGain),
        };
      },
    },
  ),
);
