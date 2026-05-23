import { useEffect, useRef, useState } from 'react';

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
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  useEffect(() => {
    if (!audioElement || !isPlaying || !enabled) {
      setVolume(0);
      return;
    }

    const AudioContextClass = window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const audioContext = new AudioContextClass();
    audioContextRef.current = audioContext;

    const analyser = audioContext.createAnalyser();
    analyser.fftSize = fftSize;
    analyser.smoothingTimeConstant = smoothingTimeConstant;
    analyserRef.current = analyser;

    const source = audioContext.createMediaElementSource(audioElement);
    sourceRef.current = source;
    source.connect(analyser);
    analyser.connect(audioContext.destination);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const analyze = () => {
      analyser.getByteFrequencyData(dataArray);
      const sum = dataArray.reduce((acc, val) => acc + val, 0);
      const average = sum / dataArray.length;
      const normalizedVolume = Math.min(average / normalizationFactor, 1);
      setVolume(normalizedVolume);
      animationFrameRef.current = requestAnimationFrame(analyze);
    };

    analyze();

    return () => {
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
      }
      if (sourceRef.current) {
        sourceRef.current.disconnect();
      }
      if (analyserRef.current) {
        analyserRef.current.disconnect();
      }
      if (audioContextRef.current) {
        audioContextRef.current.close();
      }
    };
  }, [audioElement, isPlaying, enabled, fftSize, smoothingTimeConstant, normalizationFactor]);

  return { volume };
}

export default useAudioAnalyzer;
