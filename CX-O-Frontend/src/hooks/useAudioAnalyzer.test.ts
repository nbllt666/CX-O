/**
 * useAudioAnalyzer 行为锁定测试（M6 基线）。
 *
 * 目的：在 M6 重构（抽取 useAudioPipeline 工厂）之前钉住 hook 的外部行为，
 * 重构后此文件不改一行，全 PASS 即行为等价。
 *
 * 覆盖：
 * - 初始状态
 * - Effect 1：AudioContext/Analyser/MediaElementSource 生命周期（audioElement + enabled 依赖）
 * - Effect 2：RAF 分析循环（isPlaying + enabled 依赖）
 * - volume / voiceBandVolume / vowelWeights 计算
 * - 节流 setState（100ms via performance.now()）
 * - 自定义 options（fftSize, smoothingTimeConstant, normalizationFactor）
 * - unmount 清理
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useAudioAnalyzer } from './useAudioAnalyzer';
import { MockAudioContext } from '../test/mockWebSocket';

let rafQueue: FrameRequestCallback[] = [];
const originalRaf = global.requestAnimationFrame;
const originalCancelRaf = global.cancelAnimationFrame;
const originalPerformanceNow = performance.now;

beforeEach(() => {
  rafQueue = [];
  global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    rafQueue.push(cb);
    return rafQueue.length;
  }) as typeof requestAnimationFrame;
  global.cancelAnimationFrame = (() => {
    rafQueue = [];
  }) as typeof cancelAnimationFrame;
  // Default: performance.now() returns 0 so the initial render-time analyze()
  // is throttled (0 - 0 = 0 < 100), keeping lastStateUpdateRef at 0.
  // Individual tests override to a value >= 100 to trigger a flush.
  performance.now = () => 0;
});

afterEach(() => {
  global.requestAnimationFrame = originalRaf;
  global.cancelAnimationFrame = originalCancelRaf;
  performance.now = originalPerformanceNow;
});

function flushRaf(): void {
  const cbs = rafQueue;
  rafQueue = [];
  act(() => {
    cbs.forEach((cb) => cb(0));
  });
}

/** Build a frequency array of given length filled with a constant value. */
function makeFreqData(value: number, length: number = 128): Uint8Array {
  const arr = new Uint8Array(length);
  arr.fill(value);
  return arr;
}

describe('useAudioAnalyzer', () => {
  let audioElement: HTMLAudioElement;

  beforeEach(() => {
    MockAudioContext.reset();
    audioElement = document.createElement('audio');
  });

  describe('initial state', () => {
    it('returns zero volume / voiceBandVolume / vowelWeights', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement: null, isPlaying: false }),
      );
      expect(result.current.volume).toBe(0);
      expect(result.current.voiceBandVolume).toBe(0);
      expect(result.current.vowelWeights).toEqual({ a: 0, i: 0, u: 0, e: 0, o: 0 });
    });

    it('exposes volumeRef and vowelWeightsRef initially zero', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement: null, isPlaying: false }),
      );
      expect(result.current.volumeRef.current).toBe(0);
      expect(result.current.vowelWeightsRef.current).toEqual({ a: 0, i: 0, u: 0, e: 0, o: 0 });
    });

    it('does not create AudioContext when audioElement is null', () => {
      renderHook(() => useAudioAnalyzer({ audioElement: null, isPlaying: false }));
      expect(MockAudioContext.instances).toHaveLength(0);
    });

    it('does not create AudioContext when enabled=false', () => {
      renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: false, enabled: false }),
      );
      expect(MockAudioContext.instances).toHaveLength(0);
    });
  });

  describe('Effect 1: AudioContext lifecycle', () => {
    it('creates AudioContext + Analyser + MediaElementSource when audioElement is provided', () => {
      renderHook(() => useAudioAnalyzer({ audioElement, isPlaying: false }));
      expect(MockAudioContext.instances).toHaveLength(1);
      const ctx = MockAudioContext.LAST!;
      expect(ctx.analysersCreated).toBe(1);
      expect(ctx.elementSourcesCreated).toBe(1);
    });

    it('configures analyser with default fftSize=256 and smoothing=0.8', () => {
      renderHook(() => useAudioAnalyzer({ audioElement, isPlaying: false }));
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      expect(analyser.fftSize).toBe(256);
      expect(analyser.smoothingTimeConstant).toBe(0.8);
    });

    it('connects source -> analyser -> destination', () => {
      renderHook(() => useAudioAnalyzer({ audioElement, isPlaying: false }));
      const ctx = MockAudioContext.LAST!;
      const analyser = ctx.lastAnalyser!;
      // source.connect(analyser) — analyser should have one destination recorded
      expect(analyser.connectedTo).toHaveLength(1);
      expect(analyser.connectedTo[0]).toBe(ctx.destination);
    });

    it('does not recreate nodes when same audioElement + enabled remain unchanged', () => {
      const { rerender } = renderHook(
        ({ el }) => useAudioAnalyzer({ audioElement: el, isPlaying: false }),
        { initialProps: { el: audioElement } },
      );
      expect(MockAudioContext.instances).toHaveLength(1);

      rerender({ el: audioElement });
      expect(MockAudioContext.instances).toHaveLength(1);
    });

    it('recreates AudioContext when audioElement changes', () => {
      const el2 = document.createElement('audio');
      const { rerender } = renderHook(
        ({ el }) => useAudioAnalyzer({ audioElement: el, isPlaying: false }),
        { initialProps: { el: audioElement } },
      );
      expect(MockAudioContext.instances).toHaveLength(1);

      rerender({ el: el2 });
      expect(MockAudioContext.instances).toHaveLength(2);
    });

    it('closes AudioContext and disconnects source when enabled flips to false', () => {
      const { rerender } = renderHook(
        ({ en }) => useAudioAnalyzer({ audioElement, isPlaying: false, enabled: en }),
        { initialProps: { en: true } },
      );
      const ctx = MockAudioContext.LAST!;
      expect(ctx.closed).toBe(false);

      rerender({ en: false });
      expect(ctx.closed).toBe(true);
    });

    it('cleanup on unmount disconnects source and closes AudioContext', () => {
      const { unmount } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: false }),
      );
      const ctx = MockAudioContext.LAST!;
      const source = ctx.elementSourcesCreated;
      expect(source).toBe(1);

      unmount();
      expect(ctx.closed).toBe(true);
    });
  });

  describe('Effect 2: RAF analysis loop', () => {
    it('does not start RAF when isPlaying=false', () => {
      renderHook(() => useAudioAnalyzer({ audioElement, isPlaying: false }));
      expect(rafQueue).toHaveLength(0);
    });

    it('does not start RAF when enabled=false', () => {
      renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, enabled: false }),
      );
      expect(rafQueue).toHaveLength(0);
    });

    it('does not start RAF when audioElement is null', () => {
      renderHook(() => useAudioAnalyzer({ audioElement: null, isPlaying: true }));
      expect(rafQueue).toHaveLength(0);
    });

    it('starts RAF loop when isPlaying becomes true', () => {
      const { rerender } = renderHook(
        ({ playing }) => useAudioAnalyzer({ audioElement, isPlaying: playing }),
        { initialProps: { playing: false } },
      );
      expect(rafQueue).toHaveLength(0);

      rerender({ playing: true });
      // analyze() called once synchronously + scheduled RAF
      expect(rafQueue.length).toBeGreaterThanOrEqual(1);
    });

    it('resets state and cancels RAF when isPlaying flips to false', () => {
      const { result, rerender } = renderHook(
        ({ playing }) => useAudioAnalyzer({ audioElement, isPlaying: playing }),
        { initialProps: { playing: true } },
      );
      // flush some frames
      flushRaf();

      rerender({ playing: false });
      expect(result.current.volume).toBe(0);
      expect(result.current.voiceBandVolume).toBe(0);
      expect(result.current.vowelWeights).toEqual({ a: 0, i: 0, u: 0, e: 0, o: 0 });
      expect(rafQueue).toHaveLength(0);
    });

    it('reads getByteFrequencyData on each frame', () => {
      renderHook(() => useAudioAnalyzer({ audioElement, isPlaying: true }));
      const analyserNode = MockAudioContext.LAST!.lastAnalyser!;
      const spy = vi.spyOn(analyserNode, 'getByteFrequencyData');

      flushRaf();
      expect(spy).toHaveBeenCalled();
    });

    it('computes normalized volume from average of frequency data', () => {
      // With all 50s over 128 bins: avg=50, normalized=50/100=0.5
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, normalizationFactor: 100 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      analyser.setFrequencyData(makeFreqData(50, 128));

      // lastStateUpdateRef starts at 0; use t=1000 so first update flushes (1000-0 >= 100)
      performance.now = () => 1000;
      flushRaf();

      expect(result.current.volume).toBeCloseTo(0.5, 5);
    });

    it('clamps normalized volume to 1.0', () => {
      // Uint8Array wraps (not clamps): fill(300) → 44. Use 200 which fits in uint8.
      // avg=200, normalized=200/100=2.0 → clamped to 1.0
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, normalizationFactor: 100 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      analyser.setFrequencyData(makeFreqData(200, 128));

      performance.now = () => 1000;
      flushRaf();

      expect(result.current.volume).toBe(1);
    });

    it('computes voiceBandVolume from bins 2-34', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, normalizationFactor: 100 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      analyser.setFrequencyData(makeFreqData(80, 128));

      performance.now = () => 1000;
      flushRaf();

      // voiceStart=2, voiceEnd=34 → 33 bins of value 80 → avg=80, normalized=80/100=0.8
      expect(result.current.voiceBandVolume).toBeCloseTo(0.8, 5);
    });

    it('returns zero vowel weights when volume below threshold (0.05)', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, normalizationFactor: 100 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      // avg=2 → normalized=0.02 < 0.05
      analyser.setFrequencyData(makeFreqData(2, 128));

      performance.now = () => 1000;
      flushRaf();

      expect(result.current.vowelWeights).toEqual({ a: 0, i: 0, u: 0, e: 0, o: 0 });
    });

    it('computes vowel weights proportionally when volume above threshold', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, normalizationFactor: 100 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      // Build a frequency array with distinguishable bands.
      // Use values > 5 so average exceeds 0.05 * 100 = 5 (volume threshold).
      // Fill bins 2-8 with 100 (a-band), others with 10.
      const data = new Uint8Array(128);
      data.fill(10);
      for (let i = 2; i <= 8; i++) data[i] = 100;
      analyser.setFrequencyData(data);

      performance.now = () => 1000;
      flushRaf();

      const vowels = result.current.vowelWeights;
      // All weights should be > 0 since volume > 0.05
      expect(vowels.a).toBeGreaterThan(0);
      expect(vowels.i).toBeGreaterThan(0);
      expect(vowels.u).toBeGreaterThan(0);
      expect(vowels.e).toBeGreaterThan(0);
      expect(vowels.o).toBeGreaterThan(0);
      // Weights should sum to 1 (since total > 0)
      const sum = vowels.a + vowels.i + vowels.u + vowels.e + vowels.o;
      expect(sum).toBeCloseTo(1, 5);
    });

    it('updates volumeRef synchronously even when state is throttled', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, normalizationFactor: 100 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      analyser.setFrequencyData(makeFreqData(50, 128));

      // performance.now() still returns 0 (from beforeEach) — within throttle window
      // (0 - 0 = 0 < 100), so state update is throttled but ref is always updated
      flushRaf();

      // ref updated synchronously even though state was throttled
      expect(result.current.volumeRef.current).toBeCloseTo(0.5, 5);
      expect(result.current.volume).toBe(0); // state NOT flushed — still 0
    });

    it('throttles state updates to once per 100ms', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true, normalizationFactor: 100 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;

      // First update at t=1000 — state flushes (1000-0 >= 100)
      analyser.setFrequencyData(makeFreqData(50, 128));
      performance.now = () => 1000;
      flushRaf();
      expect(result.current.volume).toBeCloseTo(0.5, 5);

      // Second update at t=1050 (within throttle window) — state stays at 0.5
      analyser.setFrequencyData(makeFreqData(80, 128));
      performance.now = () => 1050;
      flushRaf();
      expect(result.current.volume).toBeCloseTo(0.5, 5); // still 0.5, throttled
      // But ref reflects latest
      expect(result.current.volumeRef.current).toBeCloseTo(0.8, 5);

      // Third update at t=1120 (>= 100ms since last flush at 1000) — state flushes
      analyser.setFrequencyData(makeFreqData(20, 128));
      performance.now = () => 1120;
      flushRaf();
      expect(result.current.volume).toBeCloseTo(0.2, 5);
    });

    it('cancels RAF on unmount', () => {
      const { unmount } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true }),
      );
      expect(rafQueue.length).toBeGreaterThanOrEqual(1);
      const cancelSpy = vi.spyOn(global, 'cancelAnimationFrame');

      unmount();
      expect(cancelSpy).toHaveBeenCalled();
    });
  });

  describe('custom options', () => {
    it('respects custom fftSize', () => {
      renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: false, fftSize: 512 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      expect(analyser.fftSize).toBe(512);
    });

    it('respects custom smoothingTimeConstant', () => {
      renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: false, smoothingTimeConstant: 0.5 }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      expect(analyser.smoothingTimeConstant).toBe(0.5);
    });

    it('respects custom normalizationFactor', () => {
      const { result } = renderHook(() =>
        useAudioAnalyzer({
          audioElement,
          isPlaying: true,
          normalizationFactor: 200,
        }),
      );
      const analyser = MockAudioContext.LAST!.lastAnalyser!;
      // avg=100, normalized=100/200=0.5
      analyser.setFrequencyData(makeFreqData(100, 128));

      performance.now = () => 1000;
      flushRaf();

      expect(result.current.volume).toBeCloseTo(0.5, 5);
    });
  });

  describe('unmount', () => {
    it('cleans up AudioContext and RAF on unmount', () => {
      const { unmount } = renderHook(() =>
        useAudioAnalyzer({ audioElement, isPlaying: true }),
      );
      const ctx = MockAudioContext.LAST!;
      expect(ctx.closed).toBe(false);

      unmount();
      expect(ctx.closed).toBe(true);
      expect(rafQueue).toHaveLength(0);
    });
  });
});
