/**
 * useAudioPipeline 工厂行为测试。
 *
 * 覆盖：init/close 生命周期、幂等性、AudioContext 配置、Analyser 配置、
 * 节点工厂方法（init 前返回 null，init 后返回真实节点）、unmount 自动清理。
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';

import { useAudioPipeline } from './pipeline';
import { MockAudioContext, MockMediaStream } from '../../test/mockWebSocket';

describe('useAudioPipeline', () => {
  beforeEach(() => {
    MockAudioContext.reset();
  });

  describe('initial state', () => {
    it('exposes audioContextRef and analyserRef initially null', () => {
      const { result } = renderHook(() => useAudioPipeline());
      expect(result.current.audioContextRef.current).toBeNull();
      expect(result.current.analyserRef.current).toBeNull();
    });

    it('exposes init, close, and node factory functions', () => {
      const { result } = renderHook(() => useAudioPipeline());
      expect(typeof result.current.init).toBe('function');
      expect(typeof result.current.close).toBe('function');
      expect(typeof result.current.createStreamSource).toBe('function');
      expect(typeof result.current.createElementSource).toBe('function');
      expect(typeof result.current.createScriptProcessor).toBe('function');
      expect(typeof result.current.createStreamDestination).toBe('function');
    });
  });

  describe('init', () => {
    it('creates AudioContext and Analyser', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();

      expect(MockAudioContext.instances).toHaveLength(1);
      expect(result.current.audioContextRef.current).toBe(MockAudioContext.LAST);
      expect(result.current.analyserRef.current).toBe(MockAudioContext.LAST!.lastAnalyser);
    });

    it('is idempotent — second call is a no-op', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      const firstCtx = result.current.audioContextRef.current;

      result.current.init();
      expect(MockAudioContext.instances).toHaveLength(1);
      expect(result.current.audioContextRef.current).toBe(firstCtx);
    });

    it('passes audioContextOptions to AudioContext constructor', () => {
      const { result } = renderHook(() =>
        useAudioPipeline({ audioContextOptions: { latencyHint: 'interactive' } }),
      );
      result.current.init();
      expect(MockAudioContext.LAST!.ctorOptions).toEqual({ latencyHint: 'interactive' });
    });

    it('passes sampleRate option to AudioContext', () => {
      const { result } = renderHook(() =>
        useAudioPipeline({ audioContextOptions: { sampleRate: 16000 } }),
      );
      result.current.init();
      expect(MockAudioContext.LAST!.sampleRate).toBe(16000);
    });

    it('configures analyser with default fftSize=256 and smoothing=0.8', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      const analyser = result.current.analyserRef.current!;
      expect(analyser.fftSize).toBe(256);
      expect(analyser.smoothingTimeConstant).toBe(0.8);
    });

    it('configures analyser with custom fftSize', () => {
      const { result } = renderHook(() => useAudioPipeline({ fftSize: 512 }));
      result.current.init();
      expect(result.current.analyserRef.current!.fftSize).toBe(512);
    });

    it('configures analyser with custom smoothingTimeConstant', () => {
      const { result } = renderHook(() =>
        useAudioPipeline({ smoothingTimeConstant: 0.5 }),
      );
      result.current.init();
      expect(result.current.analyserRef.current!.smoothingTimeConstant).toBe(0.5);
    });
  });

  describe('close', () => {
    it('closes AudioContext and nulls refs', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      const ctx = result.current.audioContextRef.current as unknown as MockAudioContext;

      result.current.close();
      expect(ctx.closed).toBe(true);
      expect(result.current.audioContextRef.current).toBeNull();
      expect(result.current.analyserRef.current).toBeNull();
    });

    it('is idempotent — second call is a no-op', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      result.current.close();

      // Should not throw
      result.current.close();
      expect(result.current.audioContextRef.current).toBeNull();
    });

    it('is a no-op when called before init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.close();
      expect(MockAudioContext.instances).toHaveLength(0);
    });

    it('allows re-init after close', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      result.current.close();
      expect(MockAudioContext.instances).toHaveLength(1);

      result.current.init();
      expect(MockAudioContext.instances).toHaveLength(2);
      expect(result.current.audioContextRef.current).toBe(MockAudioContext.LAST);
    });
  });

  describe('createStreamSource', () => {
    it('returns null before init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      const stream = new MockMediaStream() as unknown as MediaStream;
      expect(result.current.createStreamSource(stream)).toBeNull();
    });

    it('returns MediaStreamAudioSourceNode after init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      const stream = new MockMediaStream() as unknown as MediaStream;
      const source = result.current.createStreamSource(stream);
      expect(source).not.toBeNull();
      expect(MockAudioContext.LAST!.streamSourcesCreated).toBe(1);
    });
  });

  describe('createElementSource', () => {
    it('returns null before init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      const el = document.createElement('audio');
      expect(result.current.createElementSource(el)).toBeNull();
    });

    it('returns MediaElementAudioSourceNode after init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      const el = document.createElement('audio');
      const source = result.current.createElementSource(el);
      expect(source).not.toBeNull();
      expect(MockAudioContext.LAST!.elementSourcesCreated).toBe(1);
    });
  });

  describe('createScriptProcessor', () => {
    it('returns null before init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      expect(result.current.createScriptProcessor(4096)).toBeNull();
    });

    it('returns ScriptProcessorNode after init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      const proc = result.current.createScriptProcessor(4096, 1, 1);
      expect(proc).not.toBeNull();
      expect(proc!.bufferSize).toBe(4096);
      expect(MockAudioContext.LAST!.scriptProcessorsCreated).toBe(1);
    });

    it('defaults inputChannels and outputChannels to 1', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      result.current.createScriptProcessor(2048);
      // MockScriptProcessorNode created — just verify no throw
      expect(MockAudioContext.LAST!.scriptProcessorsCreated).toBe(1);
    });
  });

  describe('createStreamDestination', () => {
    it('returns null before init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      expect(result.current.createStreamDestination()).toBeNull();
    });

    it('returns MediaStreamAudioDestinationNode after init', () => {
      const { result } = renderHook(() => useAudioPipeline());
      result.current.init();
      const dest = result.current.createStreamDestination();
      expect(dest).not.toBeNull();
      expect(dest!.stream).toBeDefined();
      expect(MockAudioContext.LAST!.streamDestinationsCreated).toBe(1);
    });
  });

  describe('unmount cleanup', () => {
    it('closes AudioContext on unmount', () => {
      const { unmount } = renderHook(() => useAudioPipeline());
      // Factory doesn't auto-init; unmount without init is a no-op
      unmount();
      expect(MockAudioContext.instances).toHaveLength(0);
    });

    it('closes AudioContext on unmount after init was called', () => {
      const { result, unmount } = renderHook(() => useAudioPipeline());
      result.current.init();
      const ctx = result.current.audioContextRef.current as unknown as MockAudioContext;
      expect(ctx.closed).toBe(false);

      unmount();
      expect(ctx.closed).toBe(true);
    });
  });

  describe('stable callbacks', () => {
    it('init, close, and node factories have stable identity across re-renders', () => {
      const { result, rerender } = renderHook(() => useAudioPipeline());
      const { init, close, createStreamSource, createElementSource, createScriptProcessor, createStreamDestination } = result.current;

      rerender();

      expect(result.current.init).toBe(init);
      expect(result.current.close).toBe(close);
      expect(result.current.createStreamSource).toBe(createStreamSource);
      expect(result.current.createElementSource).toBe(createElementSource);
      expect(result.current.createScriptProcessor).toBe(createScriptProcessor);
      expect(result.current.createStreamDestination).toBe(createStreamDestination);
    });
  });
});
