/**
 * useTtsLipSync — TTS 频谱口型数据源。
 *
 * 以 RAF 节奏读取 useWebSocket 内部 TTS 播放器输出链上的 AnalyserNode，
 * 计算实时音量（0~1）与五元音权重，写入 ref 供 VRMViewer/Live2DViewer
 * 渲染循环直读（不经 React state，避免每帧重渲染）。
 *
 * 播放停止（isPlaying=false）时归零 → 闭嘴。
 * AnalyserNode 懒创建于首个 TTS 块，故逐帧重试 getAnalyser() 直到可用。
 */
import { useEffect, useRef } from 'react';
import type { MutableRefObject } from 'react';
import { computeVowelWeights } from '../../hooks/useAudioAnalyzer';
import type { VowelWeights } from '../../hooks/useAudioAnalyzer';

export interface UseTtsLipSyncOptions {
  /** 取 TTS 播放链上的分析节点（未播放过时返回 null） */
  getAnalyser: () => AnalyserNode | null;
  /** TTS 播放状态（useWebSocket 的 isTTSPlaying） */
  isPlaying: boolean;
  /** 音量归一化因子（与 useAudioAnalyzer 默认 100 同口径） */
  normalizationFactor?: number;
}

export interface UseTtsLipSyncReturn {
  volumeRef: MutableRefObject<number>;
  vowelWeightsRef: MutableRefObject<VowelWeights>;
}

const ZERO_VOWELS: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };
/** 与 useAudioAnalyzer 内部调用同口径的元音计算音量门限 */
const VOWEL_VOLUME_THRESHOLD = 0.05;

export function useTtsLipSync({
  getAnalyser,
  isPlaying,
  normalizationFactor = 100,
}: UseTtsLipSyncOptions): UseTtsLipSyncReturn {
  const volumeRef = useRef(0);
  const vowelWeightsRef = useRef<VowelWeights>({ ...ZERO_VOWELS });
  const getAnalyserRef = useRef(getAnalyser);
  getAnalyserRef.current = getAnalyser;

  useEffect(() => {
    if (!isPlaying) {
      volumeRef.current = 0;
      vowelWeightsRef.current = { ...ZERO_VOWELS };
      return;
    }

    let raf = 0;
    let analyser: AnalyserNode | null = null;
    let dataArray: Uint8Array<ArrayBuffer> | null = null;

    const tick = () => {
      if (!analyser) {
        analyser = getAnalyserRef.current();
        if (analyser) {
          dataArray = new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount));
        }
      }
      if (analyser && dataArray) {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const volume = Math.min(sum / dataArray.length / normalizationFactor, 1);
        volumeRef.current = volume;
        vowelWeightsRef.current = computeVowelWeights(dataArray, VOWEL_VOLUME_THRESHOLD, volume);
      }
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [isPlaying, normalizationFactor]);

  return { volumeRef, vowelWeightsRef };
}
