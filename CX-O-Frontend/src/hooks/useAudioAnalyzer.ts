import { useEffect, useRef, useState, useCallback } from 'react';

export interface UseAudioAnalyzerOptions {
  audioElement: HTMLAudioElement | null;
  isPlaying: boolean;
  enabled?: boolean;
  fftSize?: number;
  smoothingTimeConstant?: number;
  normalizationFactor?: number;
}

export interface UseAudioAnalyzerReturn {
  volume: number;
  voiceBandVolume: number;
  vowelWeights: { a: number; i: number; u: number; e: number; o: number };
  volumeRef: React.MutableRefObject<number>;
  vowelWeightsRef: React.MutableRefObject<{ a: number; i: number; u: number; e: number; o: number }>;
}

function computeVowelWeights(
  dataArray: Uint8Array,
  volumeThreshold: number,
  overallVolume: number,
): { a: number; i: number; u: number; e: number; o: number } {
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
    return { a: 0, i: 0, u: 0, e: 0, o: 0 };
  }

  const total = a + i + u + e + o;
  if (total === 0) {
    return { a: 0, i: 0, u: 0, e: 0, o: 0 };
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
  const [vowelWeights, setVowelWeights] = useState<{ a: number; i: number; u: number; e: number; o: number }>({
    a: 0,
    i: 0,
    u: 0,
    e: 0,
    o: 0,
  });

  const volumeRef = useRef(0);
  const vowelWeightsRef = useRef<{ a: number; i: number; u: number; e: number; o: number }>({
    a: 0,
    i: 0,
    u: 0,
    e: 0,
    o: 0,
  });

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const sourceAudioElRef = useRef<HTMLAudioElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const lastStateUpdateRef = useRef(0);

  const throttledSetState = useCallback(
    (newVolume: number, newVoiceBand: number, newVowels: { a: number; i: number; u: number; e: number; o: number }) => {
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

  // 第一个 effect: 管理 audioContext 生命周期，仅依赖 [audioElement, enabled]
  useEffect(() => {
    if (!audioElement || !enabled) {
      if (sourceRef.current) {
        sourceRef.current.disconnect();
        sourceRef.current = null;
      }
      if (audioContextRef.current) {
        audioContextRef.current.close().catch(() => {});
        audioContextRef.current = null;
      }
      analyserRef.current = null;
      sourceAudioElRef.current = null;
      return;
    }

    if (sourceAudioElRef.current === audioElement && sourceRef.current && audioContextRef.current) {
      return;
    }

    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    analyserRef.current = null;

    const AudioContextClass =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const audioContext = new AudioContextClass();
    audioContextRef.current = audioContext;

    const analyser = audioContext.createAnalyser();
    analyser.fftSize = fftSize;
    analyser.smoothingTimeConstant = smoothingTimeConstant;
    analyserRef.current = analyser;

    const source = audioContext.createMediaElementSource(audioElement);
    sourceRef.current = source;
    sourceAudioElRef.current = audioElement;
    source.connect(analyser);
    analyser.connect(audioContext.destination);

    return () => {
      if (sourceRef.current) {
        sourceRef.current.disconnect();
        sourceRef.current = null;
      }
      if (audioContextRef.current) {
        audioContextRef.current.close().catch(() => {});
        audioContextRef.current = null;
      }
      analyserRef.current = null;
      sourceAudioElRef.current = null;
    };
  }, [audioElement, enabled]);

  useEffect(() => {
    if (!audioElement || !isPlaying || !enabled) {
      setVolume(0);
      setVoiceBandVolume(0);
      setVowelWeights({ a: 0, i: 0, u: 0, e: 0, o: 0 });
      volumeRef.current = 0;
      vowelWeightsRef.current = { a: 0, i: 0, u: 0, e: 0, o: 0 };
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      return;
    }

    const analyser = analyserRef.current;
    if (!analyser) return;

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

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };
  }, [audioElement, isPlaying, enabled, normalizationFactor, throttledSetState]);

  return { volume, voiceBandVolume, vowelWeights, volumeRef, vowelWeightsRef };
}

export default useAudioAnalyzer;
