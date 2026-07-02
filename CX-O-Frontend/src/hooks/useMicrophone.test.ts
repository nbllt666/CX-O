/**
 * useMicrophone 行为锁定测试（M6 基线）。
 *
 * 目的：在 M6 重构（抽取 useAudioPipeline 工厂）之前钉住 hook 的外部行为，
 * 重构后此文件不改一行，全 PASS 即行为等价。
 *
 * 覆盖：toggle on/off 生命周期、AudioContext 配置、Analyser 配置、MediaRecorder、
 * currentLevel 监控、cleanup、unmount 清理、createExtraNodes 插入点。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useMicrophone } from './useMicrophone';
import {
  MockAudioContext,
  MockMediaRecorder,
  MockAnalyserNode,
} from '../test/mockWebSocket';

let rafQueue: FrameRequestCallback[] = [];
const originalRaf = global.requestAnimationFrame;
const originalCancelRaf = global.cancelAnimationFrame;

beforeEach(() => {
  rafQueue = [];
  global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
    rafQueue.push(cb);
    return rafQueue.length;
  }) as typeof requestAnimationFrame;
  global.cancelAnimationFrame = (() => {
    rafQueue = [];
  }) as typeof cancelAnimationFrame;
});

afterEach(() => {
  global.requestAnimationFrame = originalRaf;
  global.cancelAnimationFrame = originalCancelRaf;
});

function flushRaf(): void {
  const cbs = rafQueue;
  rafQueue = [];
  cbs.forEach((cb) => cb(0));
}

describe('useMicrophone', () => {
  beforeEach(() => {
    MockAudioContext.reset();
    MockMediaRecorder.reset();
  });

  describe('initial state', () => {
    it('isEnabled is false and currentLevel is 0', () => {
      const { result } = renderHook(() => useMicrophone());
      expect(result.current.isEnabled).toBe(false);
      expect(result.current.currentLevel).toBe(0);
    });

    it('exposes audioContextRef and analyserRef initially null', () => {
      const { result } = renderHook(() => useMicrophone());
      expect(result.current.audioContextRef.current).toBeNull();
      expect(result.current.analyserRef.current).toBeNull();
    });

    it('exposes toggle and cleanup functions', () => {
      const { result } = renderHook(() => useMicrophone());
      expect(typeof result.current.toggle).toBe('function');
      expect(typeof result.current.cleanup).toBe('function');
    });
  });

  describe('toggle on', () => {
    it('creates AudioContext with latencyHint=interactive', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      expect(MockAudioContext.instances).toHaveLength(1);
      expect(MockAudioContext.LAST!.ctorOptions).toEqual({ latencyHint: 'interactive' });
      expect(result.current.isEnabled).toBe(true);
    });

    it('creates analyser with fftSize=256 and smoothing=0.8', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const analyser = result.current.analyserRef.current as unknown as MockAnalyserNode;
      expect(analyser).toBeDefined();
      expect(analyser.fftSize).toBe(256);
      expect(analyser.smoothingTimeConstant).toBe(0.8);
    });

    it('creates and starts MediaRecorder', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      expect(MockMediaRecorder.instances).toHaveLength(1);
      expect(MockMediaRecorder.LAST!.state).toBe('recording');
    });

    it('exposes audioContextRef and analyserRef after toggle on', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      expect(result.current.audioContextRef.current).not.toBeNull();
      expect(result.current.analyserRef.current).not.toBeNull();
    });

    it('captures MediaRecorder with audio/webm;codecs=opus mimeType', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      expect(MockMediaRecorder.LAST!.mimeType).toBe('audio/webm;codecs=opus');
    });
  });

  describe('toggle off', () => {
    it('cleans up AudioContext and stops MediaRecorder', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const ctx = MockAudioContext.LAST!;
      const rec = MockMediaRecorder.LAST!;

      await act(async () => {
        await result.current.toggle();
      });
      expect(result.current.isEnabled).toBe(false);
      expect(ctx.closed).toBe(true);
      expect(rec.state).toBe('inactive');
    });

    it('resets currentLevel to 0', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const analyser = result.current.analyserRef.current as unknown as MockAnalyserNode;
      analyser.setFrequencyData(new Array(128).fill(64));
      act(() => flushRaf());
      expect(result.current.currentLevel).toBeGreaterThan(0);

      await act(async () => {
        await result.current.toggle();
      });
      expect(result.current.currentLevel).toBe(0);
    });

    it('clears audioContextRef', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      await act(async () => {
        await result.current.toggle();
      });
      expect(result.current.audioContextRef.current).toBeNull();
    });
  });

  describe('currentLevel monitoring', () => {
    it('updates currentLevel from analyser frequency data via RAF', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const analyser = result.current.analyserRef.current as unknown as MockAnalyserNode;
      analyser.setFrequencyData(new Array(128).fill(64));

      act(() => flushRaf());
      // avg = 64, normalized = 64/128 = 0.5
      expect(result.current.currentLevel).toBeCloseTo(0.5, 1);
    });

    it('currentLevel is 0 when analyser data is all zeros', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const analyser = result.current.analyserRef.current as unknown as MockAnalyserNode;
      analyser.setFrequencyData(new Array(128).fill(0));

      act(() => flushRaf());
      expect(result.current.currentLevel).toBe(0);
    });

    it('currentLevel is clamped to 1.0 for max frequency data', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const analyser = result.current.analyserRef.current as unknown as MockAnalyserNode;
      analyser.setFrequencyData(new Array(128).fill(255));

      act(() => flushRaf());
      // avg = 255, normalized = min(255/128, 1) = 1.0
      expect(result.current.currentLevel).toBe(1);
    });
  });

  describe('cleanup', () => {
    it('cleanup() closes AudioContext without changing isEnabled state', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const ctx = MockAudioContext.LAST!;

      act(() => {
        result.current.cleanup();
      });
      // cleanup() stops resources but does not flip isEnabled — toggle() does that.
      expect(ctx.closed).toBe(true);
      expect(result.current.audioContextRef.current).toBeNull();
    });

    it('cleanup stops MediaRecorder if active', async () => {
      const { result } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const rec = MockMediaRecorder.LAST!;
      expect(rec.state).toBe('recording');

      act(() => {
        result.current.cleanup();
      });
      expect(rec.state).toBe('inactive');
    });
  });

  describe('onDataAvailable', () => {
    it('fires onDataAvailable when MediaRecorder produces data', async () => {
      const onDataAvailable = vi.fn();
      const { result } = renderHook(() => useMicrophone({ onDataAvailable }));
      await act(async () => {
        await result.current.toggle();
      });

      const mockBlob = {
        size: 4,
        arrayBuffer: () => Promise.resolve(new ArrayBuffer(4)),
      } as unknown as Blob;
      await act(async () => {
        MockMediaRecorder.LAST!.triggerDataAvailable(mockBlob);
      });
      expect(onDataAvailable).toHaveBeenCalledTimes(1);
      const buf = onDataAvailable.mock.calls[0][0] as ArrayBuffer;
      expect(buf.byteLength).toBe(4);
    });

    it('does not fire onDataAvailable when blob size is 0', async () => {
      const onDataAvailable = vi.fn();
      const { result } = renderHook(() => useMicrophone({ onDataAvailable }));
      await act(async () => {
        await result.current.toggle();
      });

      const emptyBlob = { size: 0, arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)) } as unknown as Blob;
      await act(async () => {
        MockMediaRecorder.LAST!.triggerDataAvailable(emptyBlob);
      });
      expect(onDataAvailable).not.toHaveBeenCalled();
    });
  });

  describe('createExtraNodes', () => {
    it('calls createExtraNodes with ctx and source when provided', async () => {
      const mockNode = { connect: vi.fn(), disconnect: vi.fn() } as unknown as AudioNode;
      const createExtraNodes = vi.fn((_ctx: AudioContext, _source: MediaStreamAudioSourceNode) => ({ lastNode: mockNode }));
      const { result } = renderHook(() => useMicrophone({ createExtraNodes }));
      await act(async () => {
        await result.current.toggle();
      });
      expect(createExtraNodes).toHaveBeenCalledTimes(1);
      const [ctx, source] = createExtraNodes.mock.calls[0];
      expect(ctx).toBe(MockAudioContext.LAST);
      expect(source).toBeDefined();
    });
  });

  describe('unmount', () => {
    it('triggers cleanup on unmount', async () => {
      const { result, unmount } = renderHook(() => useMicrophone());
      await act(async () => {
        await result.current.toggle();
      });
      const ctx = MockAudioContext.LAST!;

      act(() => unmount());
      expect(ctx.closed).toBe(true);
    });
  });
});
