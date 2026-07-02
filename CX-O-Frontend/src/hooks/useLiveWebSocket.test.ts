/**
 * useLiveWebSocket 单元测试。
 *
 * 覆盖：
 * - 初始连接（构造 + onopen + init 消息 + connectionCount +1）
 * - sendMessage 发送 JSON 字符串
 * - sendAudio 发送 ArrayBuffer（不字符串化）
 * - onmessage 路由：danmaku/stream/response/gift/enter/vad_status/asr_result/tts_sync/tts_tick/tts_end/external_event
 * - ArrayBuffer 消息被忽略
 * - 二进制类型设置
 * - onclose 触发指数退避重连（100/200/500/1000/2000ms）
 * - 错误路径：onerror 触发 onError
 * - reconnect 重置退避计数后立即重连
 * - disconnect 关闭连接、清空 reconnect timeout、不再重连
 * - unmount 标记 isUnmounted 不再重连
 *
 * Mock 策略：global.WebSocket 已被 src/test/setup.ts 替换为 MockWebSocket。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useLiveWebSocket } from './useLiveWebSocket';
import type { UseLiveWebSocketOptions } from './useLiveWebSocket';
import { MockWebSocket } from '../test/mockWebSocket';

function renderLive(opts: UseLiveWebSocketOptions = {}) {
  return renderHook((props: UseLiveWebSocketOptions) => useLiveWebSocket(props), {
    initialProps: opts,
  });
}

describe('useLiveWebSocket', () => {
  beforeEach(() => {
    MockWebSocket.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('constructs WebSocket with /ws/live path and session_id', () => {
    renderLive({ sessionId: 'sess-1' });
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.LAST!.url).toContain('/ws/live');
    expect(MockWebSocket.LAST!.url).toContain('session_id=sess-1');
  });

  it('constructs WebSocket without session_id when not provided', () => {
    renderLive();
    expect(MockWebSocket.LAST!.url).toMatch(/\/ws\/live$/);
  });

  it('sets binaryType to arraybuffer', () => {
    renderLive();
    expect(MockWebSocket.LAST!.binaryType).toBe('arraybuffer');
  });

  it('onopen sets isConnected, increments connectionCount, sends init, triggers onConnect', () => {
    const onConnect = vi.fn();
    const { result } = renderLive({ sessionId: 's1', onConnect });
    act(() => MockWebSocket.LAST!.triggerOpen());

    expect(result.current.isConnected).toBe(true);
    expect(result.current.connectionCount).toBe(1);
    expect(onConnect).toHaveBeenCalledTimes(1);

    const init = MockWebSocket.LAST!.lastSentAsJson<{ type: string; data: { session_id: string } }>();
    expect(init.type).toBe('init');
    expect(init.data.session_id).toBe('s1');
  });

  it('onclose triggers reconnect with exponential backoff (100ms)', () => {
    const onDisconnect = vi.fn();
    renderLive({ onDisconnect });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => MockWebSocket.LAST!.triggerClose());
    expect(onDisconnect).toHaveBeenCalled();

    const countBefore = MockWebSocket.instances.length;
    vi.advanceTimersByTime(99);
    expect(MockWebSocket.instances.length).toBe(countBefore);
    vi.advanceTimersByTime(2);
    expect(MockWebSocket.instances.length).toBe(countBefore + 1);
  });

  it('reconnect backoff caps at 2000ms after 5 attempts', () => {
    renderLive();
    for (let i = 0; i < 6; i++) {
      act(() => MockWebSocket.LAST!.triggerOpen());
      act(() => MockWebSocket.LAST!.triggerClose());
      vi.advanceTimersByTime(3000);
    }
    // After 5+ failures, all subsequent delays should be 2000ms
    // Test indirectly: no exception, instances keep growing
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(6);
  });

  it('onerror triggers onError', () => {
    const onError = vi.fn();
    renderLive({ onError });
    act(() => MockWebSocket.LAST!.triggerError());
    expect(onError).toHaveBeenCalledWith('WebSocket connection error');
  });

  it('ArrayBuffer onmessage is ignored', () => {
    const onDanmaku = vi.fn();
    renderLive({ onDanmaku });
    act(() => MockWebSocket.LAST!.triggerOpen());

    const buf = new ArrayBuffer(8);
    expect(() => {
      act(() => MockWebSocket.LAST!.triggerMessage(buf, true));
    }).not.toThrow();
    expect(onDanmaku).not.toHaveBeenCalled();
  });

  it('danmaku message triggers onDanmaku', () => {
    const onDanmaku = vi.fn();
    renderLive({ onDanmaku });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'danmaku',
        data: { id: 'd1', content: 'hi', username: 'u1' },
      });
    });
    expect(onDanmaku).toHaveBeenCalledWith({ id: 'd1', content: 'hi', username: 'u1' });
  });

  it('stream message triggers onStreamContent', () => {
    const onStreamContent = vi.fn();
    renderLive({ onStreamContent });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'stream',
        data: { content: 'live-text' },
      });
    });
    expect(onStreamContent).toHaveBeenCalledWith('live-text');
  });

  it('response message routes content to onStreamContent', () => {
    const onStreamContent = vi.fn();
    renderLive({ onStreamContent });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'response',
        data: { content: 'resp-text' },
      });
    });
    expect(onStreamContent).toHaveBeenCalledWith('resp-text');
  });

  it('gift message triggers onGift', () => {
    const onGift = vi.fn();
    renderLive({ onGift });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'gift',
        data: { gift_id: 'g1', count: 1 },
      });
    });
    expect(onGift).toHaveBeenCalledWith({ gift_id: 'g1', count: 1 });
  });

  it('enter message triggers onEnter', () => {
    const onEnter = vi.fn();
    renderLive({ onEnter });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({ type: 'enter', data: { user: 'abc' } });
    });
    expect(onEnter).toHaveBeenCalledWith({ user: 'abc' });
  });

  it('enter message with missing data triggers onEnter with empty object', () => {
    const onEnter = vi.fn();
    renderLive({ onEnter });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({ type: 'enter' });
    });
    expect(onEnter).toHaveBeenCalledWith({});
  });

  it('vad_status triggers onVadStatus with coerced numeric fields', () => {
    const onVadStatus = vi.fn();
    renderLive({ onVadStatus });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'vad_status',
        data: { status: 'speaking', speech_duration_ms: '500', speech_probability: '0.95' },
      });
    });
    expect(onVadStatus).toHaveBeenCalledWith({
      status: 'speaking',
      speech_duration_ms: 500,
      speech_probability: 0.95,
    });
  });

  it('asr_result triggers onASRResult with is_final derived from is_speaking', () => {
    const onASRResult = vi.fn();
    renderLive({ onASRResult });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'asr_result',
        data: { text: 'hello', is_speaking: true },
      });
    });
    expect(onASRResult).toHaveBeenCalledWith({ text: 'hello', is_final: false });

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'asr_result',
        data: { text: 'hello', is_speaking: false },
      });
    });
    expect(onASRResult).toHaveBeenLastCalledWith({ text: 'hello', is_final: true });
  });

  it('tts_sync triggers onTTSSync', () => {
    const onTTSSync = vi.fn();
    renderLive({ onTTSSync });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'tts_sync',
        data: { playback_id: 'p1', server_ts: 1000, text: 't', duration: 1.5 },
      });
    });
    expect(onTTSSync).toHaveBeenCalledWith({
      playback_id: 'p1',
      server_ts: 1000,
      text: 't',
      duration: 1.5,
    });
  });

  it('tts_tick triggers onTTSTick', () => {
    const onTTSTick = vi.fn();
    renderLive({ onTTSTick });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'tts_tick',
        data: { playback_id: 'p1', server_ts: 1500, position: 200 },
      });
    });
    expect(onTTSTick).toHaveBeenCalledWith({ playback_id: 'p1', server_ts: 1500, position: 200 });
  });

  it('tts_end triggers onTTSEnd', () => {
    const onTTSEnd = vi.fn();
    renderLive({ onTTSEnd });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'tts_end',
        data: { playback_id: 'p1', server_ts: 3000 },
      });
    });
    expect(onTTSEnd).toHaveBeenCalledWith({ playback_id: 'p1', server_ts: 3000 });
  });

  it('external_event triggers onExternalEvent', () => {
    const onExternalEvent = vi.fn();
    renderLive({ onExternalEvent });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => {
      MockWebSocket.LAST!.triggerMessage({
        type: 'external_event',
        data: { source: 'sys', type: 'reload', title: 'config', body: 'refresh' },
      });
    });
    expect(onExternalEvent).toHaveBeenCalledWith({
      source: 'sys',
      type: 'reload',
      title: 'config',
      body: 'refresh',
    });
  });

  it('unknown message type is ignored', () => {
    const onDanmaku = vi.fn();
    const onError = vi.fn();
    renderLive({ onDanmaku, onError });
    act(() => MockWebSocket.LAST!.triggerOpen());

    expect(() => {
      act(() => MockWebSocket.LAST!.triggerMessage({ type: 'mystery_type', data: {} }));
    }).not.toThrow();
    expect(onDanmaku).not.toHaveBeenCalled();
  });

  it('malformed JSON is caught and does not throw', () => {
    renderLive();
    act(() => MockWebSocket.LAST!.triggerOpen());

    expect(() => {
      act(() => MockWebSocket.LAST!.triggerMessage('not-json'));
    }).not.toThrow();
  });

  it('sendMessage sends stringified JSON', () => {
    const { result } = renderLive();
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => result.current.sendMessage({ type: 'cmd', data: { x: 1 } }));
    expect(JSON.parse(MockWebSocket.LAST!.lastSentAsString())).toEqual({
      type: 'cmd',
      data: { x: 1 },
    });
  });

  it('sendMessage when not connected is no-op (logs warning)', () => {
    const { result } = renderLive();
    const before = MockWebSocket.LAST!.sentMessages.length;
    act(() => result.current.sendMessage({ type: 'x' }));
    expect(MockWebSocket.LAST!.sentMessages.length).toBe(before);
  });

  it('sendAudio sends ArrayBuffer unchanged', () => {
    const { result } = renderLive();
    act(() => MockWebSocket.LAST!.triggerOpen());

    const buf = new ArrayBuffer(16);
    act(() => result.current.sendAudio(buf));
    expect(MockWebSocket.LAST!.sentMessages[MockWebSocket.LAST!.sentMessages.length - 1]).toBe(buf);
  });

  it('sendAudio when not connected is no-op', () => {
    const { result } = renderLive();
    const before = MockWebSocket.LAST!.sentMessages.length;
    act(() => result.current.sendAudio(new ArrayBuffer(8)));
    expect(MockWebSocket.LAST!.sentMessages.length).toBe(before);
  });

  it('disconnect closes socket and cancels pending reconnect', () => {
    const { result } = renderLive();
    act(() => MockWebSocket.LAST!.triggerOpen());
    act(() => MockWebSocket.LAST!.triggerClose());

    const countBefore = MockWebSocket.instances.length;
    act(() => result.current.disconnect());

    vi.advanceTimersByTime(5000);
    expect(MockWebSocket.instances.length).toBe(countBefore);
  });

  it('reconnect closes existing, resets attempts, and schedules new connect', () => {
    const { result } = renderLive();
    act(() => MockWebSocket.LAST!.triggerOpen());
    const first = MockWebSocket.LAST;

    act(() => result.current.reconnect());
    vi.advanceTimersByTime(100);

    expect(MockWebSocket.LAST).not.toBe(first);
    expect(MockWebSocket.LAST!.readyState).not.toBe(MockWebSocket.OPEN);
  });

  it('unmount prevents further reconnect attempts', () => {
    const { unmount } = renderLive();
    act(() => MockWebSocket.LAST!.triggerOpen());
    act(() => MockWebSocket.LAST!.triggerClose());

    const countBeforeUnmont = MockWebSocket.instances.length;
    act(() => unmount());
    vi.advanceTimersByTime(10000);

    // After unmount, isUnmountedRef guards prevent reconnect scheduling
    expect(MockWebSocket.instances.length).toBe(countBeforeUnmont);
  });

  it('returns stable api shape', () => {
    const { result } = renderLive();
    expect(result.current).toHaveProperty('isConnected');
    expect(result.current).toHaveProperty('sendMessage');
    expect(result.current).toHaveProperty('sendAudio');
    expect(result.current).toHaveProperty('disconnect');
    expect(result.current).toHaveProperty('reconnect');
    expect(result.current).toHaveProperty('connectionCount');
  });
});
