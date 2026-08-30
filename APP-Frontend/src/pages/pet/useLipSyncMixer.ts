/**
 * useLipSyncMixer — 三路口型音源汇合器（SubTask 4.2/4.3/4.4）。
 *
 * 每帧按 pickLipSource 的优先级裁决选中一路音源，把它的
 * volume/vowelWeights 拷贝到输出 ref（PetAvatar 渲染循环直读）；
 * 无活跃音源时归零闭嘴。拷贝而非共享 ref：三路写入方各自独立
 * 归零/写值，互不污染。
 */
import { useEffect, useRef } from 'react';
import type { MutableRefObject } from 'react';

import type { VowelWeights } from '../../hooks/useAudioAnalyzer';
import { pickLipSource } from './lipMixer';

export interface LipSourceChannel {
  active: boolean;
  volumeRef: MutableRefObject<number>;
  vowelWeightsRef: MutableRefObject<VowelWeights>;
}

export interface UseLipSyncMixerOptions {
  tts: LipSourceChannel;
  danmaku: LipSourceChannel;
  mic: LipSourceChannel;
}

export interface UseLipSyncMixerReturn {
  volumeRef: MutableRefObject<number>;
  vowelWeightsRef: MutableRefObject<VowelWeights>;
}

const ZERO_VOWELS: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };

export function useLipSyncMixer({
  tts,
  danmaku,
  mic,
}: UseLipSyncMixerOptions): UseLipSyncMixerReturn {
  const volumeRef = useRef(0);
  const vowelWeightsRef = useRef<VowelWeights>({ ...ZERO_VOWELS });

  const ttsRef = useRef(tts);
  ttsRef.current = tts;
  const danmakuRef = useRef(danmaku);
  danmakuRef.current = danmaku;
  const micRef = useRef(mic);
  micRef.current = mic;

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const t = ttsRef.current;
      const d = danmakuRef.current;
      const m = micRef.current;
      const picked = pickLipSource(t.active, d.active, m.active);
      const channel =
        picked === 'tts' ? t : picked === 'danmaku' ? d : picked === 'mic' ? m : null;
      if (channel) {
        volumeRef.current = channel.volumeRef.current;
        vowelWeightsRef.current = { ...channel.vowelWeightsRef.current };
        raf = requestAnimationFrame(tick);
      } else {
        // 无活跃音源：归零闭嘴并自停 RAF（不再排下一帧），避免全程空转烧 CPU；
        // 任一路 active 翻转时下方依赖数组触发 effect 重跑，循环自动重启
        volumeRef.current = 0;
        vowelWeightsRef.current = { ...ZERO_VOWELS };
        raf = 0;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // 依赖三路 active：无源→有源时重启 tick 循环；有源→无源时重跑后由 tick 自停
  }, [tts.active, danmaku.active, mic.active]);

  return { volumeRef, vowelWeightsRef };
}

export default useLipSyncMixer;
