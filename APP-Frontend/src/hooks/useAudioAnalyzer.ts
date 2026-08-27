/**
 * useAudioAnalyzer — 音频频谱分析钩子。
 *
 * 将 HTMLAudioElement 接入 AudioContext → Analyser 管线，按 RAF 节奏计算：
 * - volume：全频段平均音量（0~1，经 normalizationFactor 归一）
 * - voiceBandVolume：人声频段（bin 2~34）平均音量
 * - vowelWeights：五元音（a/i/u/e/o）权重，供 VRM 口型驱动
 *
 * 状态经 100ms 节流写入 React state；实时值同步写入 ref 供渲染循环直读。
 */
import { useEffect, useRef, useState, useCallback } from 'react';

import { useAudioPipeline } from './audio/pipeline';

export interface UseAudioAnalyzerOptions {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
  enabled?: boolean;
  fftSize?: number;
  smoothingTimeConstant?: number;
  normalizationFactor?: number;
}

export interface VowelWeights {
  a: number;
  i: number;
  u: number;
  e: number;
  o: number;
}

export interface UseAudioAnalyzerReturn {
  volume: number;
  voiceBandVolume: number;
  vowelWeights: VowelWeights;
  volumeRef: React.MutableRefObject<number>;
  vowelWeightsRef: React.MutableRefObject<VowelWeights>;
}

const ZERO_VOWELS: VowelWeights = { a: 0, i: 0, u: 0, e: 0, o: 0 };

export function computeVowelWeights(
  dataArray: Uint8Array,
  volumeThreshold: number,
  overallVolume: number,
): VowelWeights {
  const bandSum = (start: number, end: number) => {
    let s = 0;
    const lo = Math.max(start, 0);
    const hi = Math.min(end, dataArray.length - 1);
    for (let i = lo; i <= hi; i++) s += dataArray[i];
    return s / (hi - lo + 1);
  };

  const a = bandSum(2, 8);
  const i = bandSum(15, 25);
  const u = bandSum(5, 12);
  const e = bandSum(10, 20);
  const o = bandSum(3, 10);

  if (overallVolume < volumeThreshold) {
    return { ...ZERO_VOWELS };
  }

  const total = a + i + u + e + o;
  if (total === 0) {
    return { ...ZERO_VOWELS };
  }

  return {
    a: a / total,
    i: i / total,
    u: u / total,
    e: e / total,
    o: o / total,
  };
}

export function useAudioAnalyzer({
  audioElement,
  isPlaying,
  enabled = true,
  fftSize = 256,
  smoothingTimeConstant = 0.8,
  normalizationFactor = 100,
}: UseAudioAnalyzerOptions): UseAudioAnalyzerReturn {
  const [volume, setVolume] = useState(0);
  const [voiceBandVolume, setVoiceBandVolume] = useState(0);
  const [vowelWeights, setVowelWeights] = useState<VowelWeights>({ ...ZERO_VOWELS });

  const volumeRef = useRef(0);
  const vowelWeightsRef = useRef<VowelWeights>({ ...ZERO_VOWELS });

  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const sourceAudioElRef = useRef<HTMLAudioElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const lastStateUpdateRef = useRef(0);

  const {
    audioContextRef,
    analyserRef,
    init: initPipeline,
    close: closePipeline,
    createElementSource,
  } = useAudioPipeline({ fftSize, smoothingTimeConstant });

  const throttledSetState = useCallback(
    (newVolume: number, newVoiceBand: number, newVowels: VowelWeights) => {
      volumeRef.current = newVolume;
      vowelWeightsRef.current = newVowels;

      const now = performance.now();
      if (now - lastStateUpdateRef.current >= 100) {
        lastStateUpdateRef.current = now;
        setVolume(newVolume);
        setVoiceBandVolume(newVoiceBand);
        setVowelWeights(newVowels);
      }
    },
    [],
  );

  // 管理 audioContext 生命周期，仅依赖 [audioElement, enabled]
  useEffect(() => {
    if (!audioElement || !enabled) {
      if (sourceRef.current) {
        sourceRef.current.disconnect();
        sourceRef.current = null;
      }
      closePipeline();
      sourceAudioElRef.current = null;
      return;
    }

    if (
      sourceAudioElRef.current === audioElement &&
      sourceRef.current &&
      audioContextRef.current
    ) {
      return;
    }

    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }

    // F3（第五轮）: close 为异步完成（analyserRef 同步置空、audioContextRef 异步
    // 置空），旧实现 close 后立刻 init：audioContextRef 仍非空 → init 幂等早退 →
    // analyser 恒为 null → createElementSource 后 connect(null) 抛 TypeError。
    // 串行 await close 完成后再重建；cancelled 标志防止 effect 重跑/销毁后
    // 异步续体仍创建新 AudioContext 造成泄漏。
    let cancelled = false;
    const setupPipeline = async () => {
      await closePipeline();
      if (cancelled) return;
      initPipeline();
      const source = createElementSource(audioElement)!;
      sourceRef.current = source;
      sourceAudioElRef.current = audioElement;
      source.connect(analyserRef.current!);
      analyserRef.current!.connect(audioContextRef.current!.destination);
    };
    void setupPipeline();

    return () => {
      cancelled = true;
      if (sourceRef.current) {
        sourceRef.current.disconnect();
        sourceRef.current = null;
      }
      closePipeline();
      sourceAudioElRef.current = null;
    };
  }, [
    audioElement,
    enabled,
    initPipeline,
    closePipeline,
    createElementSource,
    audioContextRef,
    analyserRef,
  ]);

  useEffect(() => {
    if (!audioElement || !isPlaying || !enabled) {
      setVolume(0);
      setVoiceBandVolume(0);
      setVowelWeights({ ...ZERO_VOWELS });
      volumeRef.current = 0;
      vowelWeightsRef.current = { ...ZERO_VOWELS };
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      return;
    }

    // setupPipeline 为异步：组件挂载即满足 audioElement && isPlaying && enabled 时，
    // analyser 可能尚未就绪（analyserRef 是 ref，就绪后不会触发本 effect 重跑）。
    // 以 RAF 轮询探测 analyser 就绪后再启动分析循环，避免「永不启动」。
    const tryStart = (): void => {
      const analyser = analyserRef.current;
      if (!analyser) {
        animationFrameRef.current = requestAnimationFrame(tryStart);
        return;
      }

      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      const analyze = () => {
        analyser.getByteFrequencyData(dataArray);

        const sum = dataArray.reduce((acc, val) => acc + val, 0);
        const average = sum / dataArray.length;
        const normalizedVolume = Math.min(average / normalizationFactor, 1);

        const voiceStart = 2;
        const voiceEnd = Math.min(34, dataArray.length - 1);
        let voiceSum = 0;
        for (let i = voiceStart; i <= voiceEnd; i++) voiceSum += dataArray[i];
        const voiceAverage = voiceSum / (voiceEnd - voiceStart + 1);
        const normalizedVoiceBand = Math.min(voiceAverage / normalizationFactor, 1);

        const vowels = computeVowelWeights(dataArray, 0.05, normalizedVolume);

        throttledSetState(normalizedVolume, normalizedVoiceBand, vowels);

        animationFrameRef.current = requestAnimationFrame(analyze);
      };

      analyze();
    };

    tryStart();

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [audioElement, isPlaying, enabled, normalizationFactor, throttledSetState, analyserRef]);

  return { volume, voiceBandVolume, vowelWeights, volumeRef, vowelWeightsRef };
}

export default useAudioAnalyzer;
