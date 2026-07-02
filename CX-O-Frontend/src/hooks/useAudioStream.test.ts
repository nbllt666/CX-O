/**
 * useAudioStream 行为锁定测试（M6 基线）。
 *
 * 目的：在 M6 重构（抽取 useAudioPipeline 工厂）之前钉住 hook 的外部行为。
 * 重构后此文件不改一行，全 PASS 即行为等价。
 *
 * 覆盖：startStreaming / stopStreaming（半双工）、startDualStream / stopDualStream（双流式）、
 * ScriptProcessor 采集 + processAudioChunk 推送、handleVoiceMessage 路由、resetStream、unmount。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useAudioStream } from './useAudioStream';
import { VoiceActions } from '../constants/actions';
import { MockAudioContext } from '../test/mockWebSocket';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function renderStream(options: Parameters<typeof useAudioStream>[0]) {
  return renderHook(() => useAudioStream(options));
}

describe('useAudioStream', () => {
  beforeEach(() => {
    MockAudioContext.reset();
  });

  describe('initial state', () => {
    it('isStreaming, isSpeaking, isDualStreaming are false', () => {
      const { result } = renderStream({ wsSend: vi.fn() });
      expect(result.current.isStreaming).toBe(false);
      expect(result.current.isSpeaking).toBe(false);
      expect(result.current.isDualStreaming).toBe(false);
    });

    it('exposes all API methods', () => {
      const { result } = renderStream({ wsSend: vi.fn() });
      expect(typeof result.current.startStreaming).toBe('function');
      expect(typeof result.current.stopStreaming).toBe('function');
      expect(typeof result.current.resetStream).toBe('function');
      expect(typeof result.current.startDualStream).toBe('function');
      expect(typeof result.current.stopDualStream).toBe('function');
      expect(typeof result.current.handleVoiceMessage).toBe('function');
    });
  });

  describe('startStreaming (half-duplex)', () => {
    it('creates AudioContext with sampleRate=16000 by default', async () => {
      const { result } = renderStream({ wsSend: vi.fn() });
      await act(async () => {
        await result.current.startStreaming();
      });
      expect(MockAudioContext.instances).toHaveLength(1);
      expect(MockAudioContext.LAST!.ctorOptions).toEqual({ sampleRate: 16000 });
    });

    it('creates analyser with fftSize=256', async () => {
      const { result } = renderStream({ wsSend: vi.fn() });
      await act(async () => {
        await result.current.startStreaming();
      });
      expect(MockAudioContext.LAST!.lastAnalyser!.fftSize).toBe(256);
    });

    it('creates ScriptProcessor with bufferSize=4096', async () => {
      const { result } = renderStream({ wsSend: vi.fn() });
      await act(async () => {
        await result.current.startStreaming();
      });
      expect(MockAudioContext.LAST!.lastScriptProcessor).not.toBeNull();
      expect(MockAudioContext.LAST!.lastScriptProcessor!.bufferSize).toBe(4096);
    });

    it('sets isStreaming to true', async () => {
      const { result } = renderStream({ wsSend: vi.fn() });
      await act(async () => {
        await result.current.startStreaming();
      });
      expect(result.current.isStreaming).toBe(true);
    });

    it('sends asr_stream audio chunks via wsSend when interval fires', async () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend, chunkInterval: 100 });
      await act(async () => {
        await result.current.startStreaming();
      });

      const sp = MockAudioContext.LAST!.lastScriptProcessor!;
      act(() => {
        sp.triggerAudioProcess(new Float32Array([0.5, -0.5, 0.3, -0.3]));
      });
      act(() => {
        vi.advanceTimersByTime(100);
      });

      const sent = wsSend.mock.calls.find(
        (c) => (c[0] as { action: string }).action === 'asr_stream',
      );
      expect(sent).toBeDefined();
      const data = (sent![0] as { data: { audio: string } }).data;
      expect(typeof data.audio).toBe('string');
      expect(data.audio.length).toBeGreaterThan(0);
    });
  });

  describe('stopStreaming', () => {
    it('sets isStreaming to false and closes context', async () => {
      const { result } = renderStream({ wsSend: vi.fn() });
      await act(async () => {
        await result.current.startStreaming();
      });
      const ctx = MockAudioContext.LAST!;

      act(() => {
        result.current.stopStreaming();
      });
      expect(result.current.isStreaming).toBe(false);
      expect(ctx.closed).toBe(true);
    });

    it('stops the chunk interval (no further wsSend)', async () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend, chunkInterval: 100 });
      await act(async () => {
        await result.current.startStreaming();
      });
      act(() => {
        result.current.stopStreaming();
      });
      const callsBefore = wsSend.mock.calls.length;
      act(() => {
        vi.advanceTimersByTime(1000);
      });
      expect(wsSend.mock.calls.length).toBe(callsBefore);
    });
  });

  describe('resetStream', () => {
    it('sends asr_stream with reset=true', () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend });
      act(() => {
        result.current.resetStream();
      });
      expect(wsSend).toHaveBeenCalledWith({
        action: 'asr_stream',
        data: { reset: true },
      });
    });
  });

  describe('startDualStream', () => {
    it('sends init message with session_id / agent_id / request_id', async () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend, chunkInterval: 100 });
      await act(async () => {
        await result.current.startDualStream('s1', 'a1', 'r1');
      });
      const initCall = wsSend.mock.calls.find((c) => {
        const d = c[0] as { action: string; data: { init?: boolean } };
        return d.action === VoiceActions.DUAL_STREAM && d.data.init === true;
      });
      expect(initCall).toBeDefined();
      const data = (initCall![0] as {
        data: { session_id: string; agent_id: string; request_id: string };
      }).data;
      expect(data.session_id).toBe('s1');
      expect(data.agent_id).toBe('a1');
      expect(data.request_id).toBe('r1');
      expect(result.current.isDualStreaming).toBe(true);
    });

    it('includes engine and voice when provided', async () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend, chunkInterval: 100 });
      await act(async () => {
        await result.current.startDualStream('s1', 'a1', 'r1', {
          engine: 'orpheus',
          voice: 'tara',
        });
      });
      const initCall = wsSend.mock.calls.find((c) => {
        const d = c[0] as { action: string; data: { init?: boolean } };
        return d.action === VoiceActions.DUAL_STREAM && d.data.init === true;
      });
      const data = (initCall![0] as { data: { engine?: string; voice?: string } }).data;
      expect(data.engine).toBe('orpheus');
      expect(data.voice).toBe('tara');
    });

    it('sends dual_stream audio chunks when interval fires', async () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend, chunkInterval: 100 });
      await act(async () => {
        await result.current.startDualStream('s1', 'a1', 'r1');
      });
      const sp = MockAudioContext.LAST!.lastScriptProcessor!;
      act(() => {
        sp.triggerAudioProcess(new Float32Array([0.5, -0.5]));
      });
      act(() => {
        vi.advanceTimersByTime(100);
      });
      const audioCall = wsSend.mock.calls.find((c) => {
        const d = c[0] as { action: string; data: { type?: string } };
        return d.action === VoiceActions.DUAL_STREAM && d.data.type === 'audio';
      });
      expect(audioCall).toBeDefined();
      const data = (audioCall![0] as {
        data: { session_id: string; agent_id: string; request_id: string; audio: string };
      }).data;
      expect(data.session_id).toBe('s1');
      expect(data.agent_id).toBe('a1');
      expect(data.request_id).toBe('r1');
      expect(typeof data.audio).toBe('string');
    });
  });

  describe('stopDualStream', () => {
    it('sends end message with session info', async () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend, chunkInterval: 100 });
      await act(async () => {
        await result.current.startDualStream('s1', 'a1', 'r1');
      });
      act(() => {
        result.current.stopDualStream();
      });
      const endCall = wsSend.mock.calls.find((c) => {
        const d = c[0] as { action: string; data: { end?: boolean } };
        return d.action === VoiceActions.DUAL_STREAM && d.data.end === true;
      });
      expect(endCall).toBeDefined();
      const data = (endCall![0] as {
        data: { session_id: string; agent_id: string; request_id: string };
      }).data;
      expect(data.session_id).toBe('s1');
      expect(data.agent_id).toBe('a1');
      expect(data.request_id).toBe('r1');
      expect(result.current.isDualStreaming).toBe(false);
    });

    it('closes AudioContext', async () => {
      const { result } = renderStream({ wsSend: vi.fn(), chunkInterval: 100 });
      await act(async () => {
        await result.current.startDualStream('s1', 'a1', 'r1');
      });
      const ctx = MockAudioContext.LAST!;
      act(() => {
        result.current.stopDualStream();
      });
      expect(ctx.closed).toBe(true);
    });
  });

  describe('handleVoiceMessage', () => {
    it('routes PARTIAL to onPartial', () => {
      const onPartial = vi.fn();
      const { result } = renderStream({ wsSend: vi.fn(), onPartial });
      act(() => {
        result.current.handleVoiceMessage({
          type: VoiceActions.PARTIAL,
          data: { text: 'hello', session_id: 's1' },
        });
      });
      expect(onPartial).toHaveBeenCalledWith('hello', 's1');
    });

    it('routes PREFILL_STARTED to onPrefillStarted (partial_text field)', () => {
      const onPrefillStarted = vi.fn();
      const { result } = renderStream({ wsSend: vi.fn(), onPrefillStarted });
      act(() => {
        result.current.handleVoiceMessage({
          type: VoiceActions.PREFILL_STARTED,
          data: { partial_text: 'thinking', session_id: 's1' },
        });
      });
      expect(onPrefillStarted).toHaveBeenCalledWith('thinking', 's1');
    });

    it('routes PREFILL_STARTED with text field fallback', () => {
      const onPrefillStarted = vi.fn();
      const { result } = renderStream({ wsSend: vi.fn(), onPrefillStarted });
      act(() => {
        result.current.handleVoiceMessage({
          type: VoiceActions.PREFILL_STARTED,
          data: { text: 'fallback', session_id: 's1' },
        });
      });
      expect(onPrefillStarted).toHaveBeenCalledWith('fallback', 's1');
    });

    it('routes TTS_CHUNK to onTTSChunk', () => {
      const onTTSChunk = vi.fn();
      const { result } = renderStream({ wsSend: vi.fn(), onTTSChunk });
      act(() => {
        result.current.handleVoiceMessage({
          type: VoiceActions.TTS_CHUNK,
          data: { audio_data: 'base64audio', text_segment: 'hello', session_id: 's1' },
          is_final: true,
        });
      });
      expect(onTTSChunk).toHaveBeenCalledWith('base64audio', true, 'hello', 's1');
    });

    it('does nothing for unknown message type', () => {
      const onPartial = vi.fn();
      const { result } = renderStream({ wsSend: vi.fn(), onPartial });
      act(() => {
        result.current.handleVoiceMessage({
          type: 'unknown.type' as never,
          data: { text: 'hello' },
        });
      });
      expect(onPartial).not.toHaveBeenCalled();
    });

    it('does nothing for null message', () => {
      const onPartial = vi.fn();
      const { result } = renderStream({ wsSend: vi.fn(), onPartial });
      act(() => {
        result.current.handleVoiceMessage(null as never);
      });
      expect(onPartial).not.toHaveBeenCalled();
    });
  });

  describe('custom config', () => {
    it('uses custom sampleRate when provided', async () => {
      const { result } = renderStream({
        wsSend: vi.fn(),
        config: { sampleRate: 8000 },
      });
      await act(async () => {
        await result.current.startStreaming();
      });
      expect(MockAudioContext.LAST!.ctorOptions).toEqual({ sampleRate: 8000 });
    });

    it('uses custom chunkInterval when provided', async () => {
      const wsSend = vi.fn();
      const { result } = renderStream({ wsSend, chunkInterval: 200 });
      await act(async () => {
        await result.current.startStreaming();
      });
      const sp = MockAudioContext.LAST!.lastScriptProcessor!;
      act(() => {
        sp.triggerAudioProcess(new Float32Array([0.5, -0.5]));
      });
      act(() => {
        vi.advanceTimersByTime(100);
      });
      // Should NOT have sent audio yet (interval is 200ms)
      const sentBefore = wsSend.mock.calls.filter(
        (c) => (c[0] as { action: string }).action === 'asr_stream',
      ).length;
      act(() => {
        vi.advanceTimersByTime(100);
      });
      const sentAfter = wsSend.mock.calls.filter(
        (c) => (c[0] as { action: string }).action === 'asr_stream',
      ).length;
      expect(sentAfter).toBeGreaterThan(sentBefore);
    });
  });

  describe('unmount', () => {
    it('triggers stopStreaming on unmount', async () => {
      const { result, unmount } = renderStream({ wsSend: vi.fn() });
      await act(async () => {
        await result.current.startStreaming();
      });
      const ctx = MockAudioContext.LAST!;
      act(() => unmount());
      expect(ctx.closed).toBe(true);
    });
  });
});
