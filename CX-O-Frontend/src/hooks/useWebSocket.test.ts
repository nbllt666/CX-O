/**
 * useWebSocket 单元测试。
 *
 * 覆盖：
 * - 初始连接（构造 WebSocket + onopen + 启动 ping）
 * - sendMessage 发送 {type:'chat_stream', message, agent_id} 平铺格式；带图返回 false 强制 HTTP 回退
 * - cancelGeneration 发送 {type:'cancel'}
 * - onmessage 路由：pong/alarm/stream/tts_chunk/response/error/content/tool_call/done/cancelled/external_event
 * - TTS 双流式：onTTSChunk 触发 + onTTSPlayingChange 切换
 * - interruptTTS 立即停止
 * - sendDualStream 复用 voice.dual_stream action
 * - sendRaw 直发原始对象
 * - 错误路径：未连接 sendMessage 触发 onError
 * - disconnect 关闭连接并清空 ping
 * - 重连（reconnect）触发新连接
 * - agentId 变更触发断开重连
 *
 * Mock 策略：global.WebSocket 已被 src/test/setup.ts 替换为 MockWebSocket，
 * 测试用 `MockWebSocket.LAST` 主动触发事件。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useWebSocket } from './useWebSocket';
import type { WebSocketOptions } from './useWebSocket';
import { MockWebSocket } from '../test/mockWebSocket';
import { VoiceActions } from '../constants/actions';

const DEFAULT_OPTS: WebSocketOptions = {
  agentId: 'agent-1',
};

function renderWs(overrides: Partial<WebSocketOptions> = {}) {
  const opts = { ...DEFAULT_OPTS, ...overrides };
  return renderHook((props: WebSocketOptions) => useWebSocket(props), {
    initialProps: opts,
  });
}

describe('useWebSocket', () => {
  beforeEach(() => {
    MockWebSocket.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('constructs WebSocket and sends config on open', () => {
    const onConnect = vi.fn();
    renderWs({ onConnect });

    expect(MockWebSocket.instances).toHaveLength(1);
    const ws = MockWebSocket.LAST!;
    expect(ws.url).toContain('/ws');

    act(() => ws.triggerOpen());

    expect(onConnect).toHaveBeenCalledTimes(1);
    const configMsg = ws.lastSentAsJson<{ type: string; agent_id: string; timeout: number }>();
    expect(configMsg.type).toBe('config');
    expect(configMsg.agent_id).toBe('agent-1');
  });

  it('starts ping interval after open (30s)', () => {
    renderWs();

    const ws = MockWebSocket.LAST!;
    act(() => ws.triggerOpen());

    expect(ws.sentMessages.length).toBe(1);
    vi.advanceTimersByTime(30_000);
    expect(ws.sentMessages.length).toBe(2);
    const ping = ws.lastSentAsJson<{ type: string }>();
    expect(ping.type).toBe('ping');

    vi.advanceTimersByTime(30_000);
    expect(ws.sentMessages.length).toBe(3);
  });

  // 后端协议（CXHMS backend/core/websocket/handlers.py）：平铺格式，handler 直接读 message 顶层字段
  it('sendMessage sends flat {type:"chat_stream", message, agent_id} for plain text', () => {
    const { result } = renderWs();
    act(() => MockWebSocket.LAST!.triggerOpen());

    let sent: boolean | undefined;
    act(() => {
      sent = result.current.sendMessage('hello');
    });

    expect(sent).toBe(true);
    const msg = MockWebSocket.LAST!.lastSentAsJson<{
      type: string;
      message: string;
      agent_id: string;
      action?: string;
      request_id?: string;
      data?: unknown;
    }>();
    expect(msg.type).toBe('chat_stream');
    expect(msg.message).toBe('hello');
    expect(msg.agent_id).toBe('agent-1');
    // 平铺格式：不得再出现 action/request_id/data 包装
    expect(msg.action).toBeUndefined();
    expect(msg.request_id).toBeUndefined();
    expect(msg.data).toBeUndefined();
    expect(result.current.isGenerating).toBe(true);
  });

  // 带图片消息：WS 后端 chat_stream 不支持 images，sendMessage 返回 false，
  // 由 caller（ChatPage）回退到 HTTP /api/chat/stream（该端点支持 images）。
  // 必须在 setIsGenerating(true) 之前返回，否则 isGenerating 永久卡住。
  it('sendMessage with images returns false without sending or setting isGenerating', () => {
    const { result } = renderWs();
    act(() => MockWebSocket.LAST!.triggerOpen());

    const before = MockWebSocket.LAST!.sentMessages.length;
    let sent: boolean | undefined;
    act(() => {
      sent = result.current.sendMessage('hello', ['img1.png']);
    });

    expect(sent).toBe(false);
    expect(MockWebSocket.LAST!.sentMessages.length).toBe(before);
    expect(result.current.isGenerating).toBe(false);
  });

  // 有意契约：未连接时 sendMessage 返回 false 且不触发 onError，
  // 由 caller（ChatPage）依据返回值走 HTTP fallback；onError 会与 fallback 的
  // loading 状态管理冲突（见 useWebSocket.ts sendMessage 注释）。
  // 与 sendDualStream（未连接时触发 onError）属两条发送路径的不同契约。
  it('sendMessage when not connected returns false without onError', () => {
    const onError = vi.fn();
    const { result } = renderWs({ onError });

    let sent: boolean | undefined;
    act(() => {
      sent = result.current.sendMessage('foo');
    });
    expect(sent).toBe(false);
    expect(onError).not.toHaveBeenCalled();
    expect(result.current.isGenerating).toBe(false);
  });

  it('cancelGeneration sends {type:"cancel"}', () => {
    const { result } = renderWs();
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => result.current.cancelGeneration());
    const msg = MockWebSocket.LAST!.lastSentAsJson<{ type: string }>();
    expect(msg.type).toBe('cancel');
  });

  it('cancelGeneration is no-op when disconnected', () => {
    const { result } = renderWs();
    const before = MockWebSocket.LAST!.sentMessages.length;
    act(() => result.current.cancelGeneration());
    expect(MockWebSocket.LAST!.sentMessages.length).toBe(before);
  });

  it('pong message is ignored', () => {
    const onMessage = vi.fn();
    renderWs({ onMessage });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => MockWebSocket.LAST!.triggerMessage({ type: 'pong' }));
    expect(onMessage).not.toHaveBeenCalled();
  });

  it('alarm message triggers onAlarm with triggered_at', () => {
    const onAlarm = vi.fn();
    renderWs({ onAlarm });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() =>
      MockWebSocket.LAST!.triggerMessage({
        type: 'alarm',
        message: 'wakeup',
        triggered_at: '2026-07-02T10:00:00Z',
      }),
    );
    expect(onAlarm).toHaveBeenCalledWith('wakeup', '2026-07-02T10:00:00Z');
  });

  it('stream content routes to onMessage as content', () => {
    const onMessage = vi.fn();
    renderWs({ onMessage });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'stream',
        data: { content: 'hello' },
      });
    });
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'content', content: 'hello' }));
  });

  it('stream is_final routes to done and clears isGenerating', () => {
    const onMessage = vi.fn();
    const { result } = renderWs({ onMessage });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'stream',
        data: { content: 'hello' },
        is_final: true,
      });
    });
    expect(result.current.isGenerating).toBe(false);
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'done' }));
  });

  it('tts_chunk triggers onTTSChunk + onTTSPlayingChange(true)', async () => {
    const onTTSChunk = vi.fn();
    const onTTSPlayingChange = vi.fn();
    const { result } = renderWs({ onTTSChunk, onTTSPlayingChange });
    act(() => MockWebSocket.LAST!.triggerOpen());

    const audioBase64 = btoa('pcm-bytes');
    await act(async () => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'stream',
        action: VoiceActions.TTS_CHUNK,
        data: { audio_data: audioBase64, text_segment: 'hi', session_id: 'sess-1' },
        is_final: false,
      });
      // Flush microtask chain for decodeAudioData + processQueue
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(onTTSChunk).toHaveBeenCalledWith(audioBase64, false, 'hi', 'sess-1');
    expect(result.current.isTTSPlaying).toBe(true);
    expect(onTTSPlayingChange).toHaveBeenCalledWith(true);
  });

  it('interruptTTS stops playback immediately', async () => {
    const onTTSPlayingChange = vi.fn();
    const { result } = renderWs({ onTTSPlayingChange });
    act(() => MockWebSocket.LAST!.triggerOpen());

    await act(async () => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'stream',
        action: VoiceActions.TTS_CHUNK,
        data: { audio_data: btoa('x') },
        is_final: false,
      });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.isTTSPlaying).toBe(true);

    act(() => result.current.interruptTTS());
    expect(result.current.isTTSPlaying).toBe(false);
    expect(onTTSPlayingChange).toHaveBeenCalledWith(false);
  });

  it('response error clears isGenerating and triggers onError', () => {
    const onError = vi.fn();
    const { result } = renderWs({ onError });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'response',
        status: 'error',
        error: { code: 'X', message: 'boom' },
      });
    });
    expect(result.current.isGenerating).toBe(false);
    expect(onError).toHaveBeenCalledWith('boom');
  });

  it('response error with string error uses it directly', () => {
    const onError = vi.fn();
    renderWs({ onError });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'response',
        status: 'error',
        error: 'string-error',
      });
    });
    expect(onError).toHaveBeenCalledWith('string-error');
  });

  it('error message clears isGenerating and triggers onError', () => {
    const onError = vi.fn();
    const { result } = renderWs({ onError });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({ type: 'error', error: 'fail' });
    });
    expect(result.current.isGenerating).toBe(false);
    expect(onError).toHaveBeenCalledWith('fail');
  });

  it('content/tool_call/tool_result/done/cancelled/thinking/tool_start all forward to onMessage', () => {
    const onMessage = vi.fn();
    renderWs({ onMessage });
    act(() => MockWebSocket.LAST!.triggerOpen());

    for (const type of ['content', 'tool_call', 'tool_result', 'done', 'cancelled', 'thinking', 'tool_start']) {
      act(() => MockWebSocket.LAST!.triggerMessage({ type, data: { foo: 'bar' } }));
    }
    expect(onMessage).toHaveBeenCalledTimes(7);
  });

  it('external_event forwards to onExternalEvent and onMessage', () => {
    const onExternalEvent = vi.fn();
    const onMessage = vi.fn();
    renderWs({ onExternalEvent, onMessage });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'external_event',
        data: { source: 'system', event: 'reload' },
      });
    });
    expect(onExternalEvent).toHaveBeenCalledWith({ source: 'system', event: 'reload' });
    expect(onMessage).toHaveBeenCalled();
  });

  it('unknown message type forwards to onMessage', () => {
    const onMessage = vi.fn();
    renderWs({ onMessage });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => MockWebSocket.LAST!.triggerMessage({ type: 'weird_type', data: {} }));
    expect(onMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'weird_type' }));
  });

  it('malformed JSON in onmessage is caught and does not throw', () => {
    const onError = vi.fn();
    renderWs({ onError });
    act(() => MockWebSocket.LAST!.triggerOpen());

    expect(() => {
      act(() => MockWebSocket.LAST!.triggerMessage('not-json'));
    }).not.toThrow();
  });

  it('sendDualStream sends voice.dual_stream action with payload', () => {
    const { result } = renderWs();
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      result.current.sendDualStream({ type: 'init', session_id: 's1', agent_id: 'a1', request_id: 'r1' });
    });
    const msg = MockWebSocket.LAST!.lastSentAsJson<{ action: string; data: unknown }>();
    expect(msg.action).toBe(VoiceActions.DUAL_STREAM);
  });

  it('sendDualStream when not connected triggers onError', () => {
    const onError = vi.fn();
    const { result } = renderWs({ onError });

    act(() => {
      result.current.sendDualStream({ type: 'init', session_id: 's', agent_id: 'a', request_id: 'r' });
    });
    expect(onError).toHaveBeenCalledWith('WebSocket is not connected');
  });

  it('sendRaw is no-op when disconnected', () => {
    const { result } = renderWs();
    const before = MockWebSocket.LAST!.sentMessages.length;
    act(() => result.current.sendRaw({ foo: 'bar' }));
    expect(MockWebSocket.LAST!.sentMessages.length).toBe(before);
  });

  it('sendRaw sends stringified object when connected', () => {
    const { result } = renderWs();
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => result.current.sendRaw({ foo: 'bar' }));
    expect(JSON.parse(MockWebSocket.LAST!.lastSentAsString())).toEqual({ foo: 'bar' });
  });

  it('disconnect closes WebSocket and clears ping', () => {
    const onDisconnect = vi.fn();
    const { result } = renderWs({ onDisconnect });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => result.current.disconnect());
    expect(MockWebSocket.LAST!.closed).toBe(true);
    const sentBefore = MockWebSocket.LAST!.sentMessages.length;
    vi.advanceTimersByTime(60_000);
    expect(MockWebSocket.LAST!.sentMessages.length).toBe(sentBefore);
  });

  it('onclose sets isConnected false and triggers onDisconnect', () => {
    const onDisconnect = vi.fn();
    const { result } = renderWs({ onDisconnect });
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(result.current.isConnected).toBe(true);

    act(() => MockWebSocket.LAST!.triggerClose());
    expect(result.current.isConnected).toBe(false);
    expect(onDisconnect).toHaveBeenCalled();
  });

  it('onerror triggers onError', () => {
    const onError = vi.fn();
    renderWs({ onError });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => MockWebSocket.LAST!.triggerError());
    expect(onError).toHaveBeenCalledWith('WebSocket connection error');
  });

  it('reconnect closes existing and opens new WebSocket', () => {
    const { result } = renderWs();
    act(() => MockWebSocket.LAST!.triggerOpen());
    const first = MockWebSocket.LAST;

    act(() => result.current.reconnect());
    vi.advanceTimersByTime(200);

    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
    expect(MockWebSocket.LAST).not.toBe(first);
  });

  it('agentId change triggers disconnect + reconnect', () => {
    const { rerender } = renderWs({ agentId: 'agent-A' });
    act(() => MockWebSocket.LAST!.triggerOpen());
    const first = MockWebSocket.LAST;

    rerender({ agentId: 'agent-B' });
    vi.advanceTimersByTime(200);

    expect(MockWebSocket.LAST).not.toBe(first);
  });

  it('empty agentId does NOT connect on mount (preserves original guard)', () => {
    renderWs({ agentId: '' });
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it('agentId empty→non-empty triggers connect (enabled transition)', () => {
    const { rerender } = renderWs({ agentId: '' });
    expect(MockWebSocket.instances).toHaveLength(0);

    rerender({ agentId: 'agent-new' });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('agentId non-empty→empty triggers disconnect', () => {
    const { rerender, result } = renderWs({ agentId: 'agent-x' });
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(result.current.isConnected).toBe(true);

    rerender({ agentId: '' });
    expect(result.current.isConnected).toBe(false);
  });

  it('partial ASR message triggers onPartial', () => {
    const onPartial = vi.fn();
    renderWs({ onPartial });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: VoiceActions.PARTIAL,
        data: { text: 'hello', session_id: 'sess-x' },
      });
    });
    expect(onPartial).toHaveBeenCalledWith('hello', 'sess-x');
  });

  it('prefill_started triggers onPrefillStarted', () => {
    const onPrefillStarted = vi.fn();
    renderWs({ onPrefillStarted });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: VoiceActions.PREFILL_STARTED,
        data: { partial_text: 'thinking...', session_id: 'sess-y' },
      });
    });
    expect(onPrefillStarted).toHaveBeenCalledWith('thinking...', 'sess-y');
  });

  it('unmount disposes TTS player', async () => {
    const onTTSPlayingChange = vi.fn();
    const { result, unmount } = renderWs({ onTTSPlayingChange });
    act(() => MockWebSocket.LAST!.triggerOpen());

    await act(async () => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'stream',
        action: VoiceActions.TTS_CHUNK,
        data: { audio_data: btoa('x') },
        is_final: false,
      });
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.isTTSPlaying).toBe(true);
    expect(onTTSPlayingChange).toHaveBeenCalledWith(true);

    act(() => unmount());
    // dispose() → interrupt() → setPlaying(false) → onPlayingChange(false)
    // React won't re-render the unmounted component, so check the callback.
    expect(onTTSPlayingChange).toHaveBeenCalledWith(false);
  });
});
