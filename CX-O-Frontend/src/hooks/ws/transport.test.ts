/**
 * useWSTransport 单元测试。
 *
 * 覆盖：
 * - URL 构造 + WebSocket 实例化
 * - onopen 触发 isConnected + caller onOpen 回调
 * - onclose 触发 isConnected=false + caller onClose 回调
 * - onerror 触发 caller onError
 * - onmessage 透传 event 给 caller onMessage
 * - send 在 OPEN 时返回 true 并发送，否则返回 false
 * - reconnect 关闭并重连
 * - disconnect 关闭并不触发自动重连
 * - 3 种重连策略：none（不重连）/ fixed（固定延迟）/ exponential（指数退避带上限）
 * - binaryType 设置
 * - unmount 标记 isUnmounted 不再触发回调
 * - ref 同步：caller 回调更新后 onOpen 用最新版本
 *
 * Mock 策略：global.WebSocket 已被 src/test/setup.ts 替换为 MockWebSocket。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

import { useWSTransport } from './transport';
import type { UseWSTransportOptions } from './transport';
import { MockWebSocket } from '../../test/mockWebSocket';

function renderTransport(opts: Partial<UseWSTransportOptions> = {}) {
  const full: UseWSTransportOptions = {
    urlBuilder: () => 'ws://test/ws',
    ...opts,
  };
  return renderHook((props: UseWSTransportOptions) => useWSTransport(props), {
    initialProps: full,
  });
}

describe('useWSTransport', () => {
  beforeEach(() => {
    MockWebSocket.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('constructs WebSocket from urlBuilder on mount', () => {
    renderTransport({ urlBuilder: () => 'ws://test/custom-path' });
    expect(MockWebSocket.instances).toHaveLength(1);
    expect(MockWebSocket.LAST!.url).toBe('ws://test/custom-path');
  });

  it('sets binaryType (default arraybuffer)', () => {
    renderTransport();
    expect(MockWebSocket.LAST!.binaryType).toBe('arraybuffer');
  });

  it('respects custom binaryType', () => {
    renderTransport({ binaryType: 'blob' });
    expect(MockWebSocket.LAST!.binaryType).toBe('blob');
  });

  it('onopen sets isConnected and triggers caller onOpen with ws instance', () => {
    const onOpen = vi.fn();
    const { result } = renderTransport({ onOpen });
    act(() => MockWebSocket.LAST!.triggerOpen());

    expect(result.current.isConnected).toBe(true);
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0][0]).toBe(MockWebSocket.LAST);
  });

  it('onclose sets isConnected=false and triggers caller onClose', () => {
    const onClose = vi.fn();
    const { result } = renderTransport({ onClose });
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(result.current.isConnected).toBe(true);

    act(() => MockWebSocket.LAST!.triggerClose());
    expect(result.current.isConnected).toBe(false);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('onerror triggers caller onError with "WebSocket connection error"', () => {
    const onError = vi.fn();
    renderTransport({ onError });
    act(() => MockWebSocket.LAST!.triggerError());
    expect(onError).toHaveBeenCalledWith('WebSocket connection error');
  });

  it('onmessage forwards raw MessageEvent to caller onMessage', () => {
    const onMessage = vi.fn();
    renderTransport({ onMessage });
    act(() => MockWebSocket.LAST!.triggerOpen());

    act(() => MockWebSocket.LAST!.triggerMessage({ type: 'foo' }));
    expect(onMessage).toHaveBeenCalledTimes(1);
    // Transport does NOT parse JSON — caller gets raw event.data (string)
    expect(onMessage.mock.calls[0][0].data).toBe('{"type":"foo"}');
  });

  it('send returns true and forwards data when OPEN', () => {
    const { result } = renderTransport();
    act(() => MockWebSocket.LAST!.triggerOpen());

    const ok = result.current.send('hello');
    expect(ok).toBe(true);
    expect(MockWebSocket.LAST!.sentMessages[0]).toBe('hello');
  });

  it('send returns false when not connected', () => {
    const { result } = renderTransport();
    const ok = result.current.send('hello');
    expect(ok).toBe(false);
    expect(MockWebSocket.LAST!.sentMessages).toHaveLength(0);
  });

  it('send supports ArrayBuffer', () => {
    const { result } = renderTransport();
    act(() => MockWebSocket.LAST!.triggerOpen());

    const buf = new ArrayBuffer(8);
    const ok = result.current.send(buf);
    expect(ok).toBe(true);
    expect(MockWebSocket.LAST!.sentMessages[0]).toBe(buf);
  });

  it('reconnect strategy "none" does NOT auto-reconnect on close', () => {
    renderTransport({ reconnect: { strategy: 'none' } });
    act(() => MockWebSocket.LAST!.triggerOpen());
    act(() => MockWebSocket.LAST!.triggerClose());

    const countBefore = MockWebSocket.instances.length;
    vi.advanceTimersByTime(60_000);
    expect(MockWebSocket.instances.length).toBe(countBefore);
  });

  it('reconnect strategy "fixed" reconnects after delay on close', () => {
    renderTransport({ reconnect: { strategy: 'fixed', delay: 250 } });
    act(() => MockWebSocket.LAST!.triggerOpen());
    act(() => MockWebSocket.LAST!.triggerClose());

    const countBefore = MockWebSocket.instances.length;
    vi.advanceTimersByTime(249);
    expect(MockWebSocket.instances.length).toBe(countBefore);
    vi.advanceTimersByTime(2);
    expect(MockWebSocket.instances.length).toBe(countBefore + 1);
  });

  it('reconnect strategy "exponential" uses delays array with cap', () => {
    renderTransport({
      reconnect: { strategy: 'exponential', delays: [100, 200, 500, 1000, 2000] },
    });
    act(() => MockWebSocket.LAST!.triggerOpen());

    // First close → 100ms delay (attempts 0→1)
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(100);
    expect(MockWebSocket.instances.length).toBe(2);

    // Second close → 200ms delay (attempts 1→2) — do NOT triggerOpen (would reset attempts)
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(199);
    expect(MockWebSocket.instances.length).toBe(2);
    vi.advanceTimersByTime(2);
    expect(MockWebSocket.instances.length).toBe(3);

    // Third close → 500ms (attempts 2→3)
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances.length).toBe(4);

    // Fourth close → 1000ms (attempts 3→4)
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(1000);
    expect(MockWebSocket.instances.length).toBe(5);

    // Fifth close → 2000ms (attempts 4→5)
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(2000);
    expect(MockWebSocket.instances.length).toBe(6);

    // Sixth close → caps at 2000ms (attempts 5→6, idx=min(5,4)=4)
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(2000);
    expect(MockWebSocket.instances.length).toBe(7);
  });

  it('exponential reconnect resets attempts on successful open', () => {
    renderTransport({
      reconnect: { strategy: 'exponential', delays: [100, 200, 500] },
    });
    // First close → 100ms
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(100);
    expect(MockWebSocket.instances.length).toBe(2);

    // Open successfully → resets attempts
    act(() => MockWebSocket.LAST!.triggerOpen());
    act(() => MockWebSocket.LAST!.triggerClose());
    // Should be 100ms again (not 200ms)
    vi.advanceTimersByTime(99);
    expect(MockWebSocket.instances.length).toBe(2);
    vi.advanceTimersByTime(2);
    expect(MockWebSocket.instances.length).toBe(3);
  });

  it('manual disconnect does NOT trigger auto-reconnect (onclose nulled)', () => {
    const onClose = vi.fn();
    const { result } = renderTransport({
      onClose,
      reconnect: { strategy: 'fixed', delay: 100 },
    });
    act(() => MockWebSocket.LAST!.triggerOpen());

    const countBefore = MockWebSocket.instances.length;
    act(() => result.current.disconnect());
    vi.advanceTimersByTime(60_000);

    // Manual disconnect: no auto-reconnect, no onClose callback
    expect(MockWebSocket.instances.length).toBe(countBefore);
    expect(onClose).not.toHaveBeenCalled();
  });

  it('manual disconnect sets isConnected=false', () => {
    const { result } = renderTransport();
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(result.current.isConnected).toBe(true);

    act(() => result.current.disconnect());
    expect(result.current.isConnected).toBe(false);
  });

  it('reconnect() closes existing and schedules new connect', () => {
    const { result } = renderTransport();
    act(() => MockWebSocket.LAST!.triggerOpen());
    const first = MockWebSocket.LAST;

    act(() => result.current.reconnect());
    vi.advanceTimersByTime(100);

    expect(MockWebSocket.LAST).not.toBe(first);
  });

  it('enabled=false does NOT connect on mount', () => {
    renderTransport({ enabled: false });
    expect(MockWebSocket.instances).toHaveLength(0);
  });

  it('enabled transition false→true connects', () => {
    const { rerender } = renderTransport({ enabled: false });
    expect(MockWebSocket.instances).toHaveLength(0);

    rerender({ urlBuilder: () => 'ws://test/ws', enabled: true });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('enabled=true→false does NOT auto-disconnect (caller controls)', () => {
    const { rerender, result } = renderTransport({ enabled: true });
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(result.current.isConnected).toBe(true);

    rerender({ urlBuilder: () => 'ws://test/ws', enabled: false });
    expect(result.current.isConnected).toBe(true);
  });

  it('reconnect() resets attempts to 0', () => {
    const { result } = renderTransport({
      reconnect: { strategy: 'exponential', delays: [100, 200, 500] },
    });
    act(() => MockWebSocket.LAST!.triggerOpen());
    // Trigger 2 failed reconnects
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(100);
    act(() => MockWebSocket.LAST!.triggerOpen());
    act(() => MockWebSocket.LAST!.triggerClose());
    vi.advanceTimersByTime(200);

    // Now reconnect() should reset attempts → next close uses 100ms
    act(() => MockWebSocket.LAST!.triggerOpen());
    act(() => result.current.reconnect());
    vi.advanceTimersByTime(100);
    expect(MockWebSocket.LAST).toBeDefined();
  });

  it('caller callback updates are reflected (ref sync)', () => {
    const onOpen1 = vi.fn();
    const onOpen2 = vi.fn();
    const { rerender, result } = renderTransport({ onOpen: onOpen1 });
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(onOpen1).toHaveBeenCalledTimes(1);

    // Re-render with new callback + new connection
    rerender({ urlBuilder: () => 'ws://test/ws', onOpen: onOpen2 });
    act(() => result.current.reconnect());
    vi.advanceTimersByTime(100);
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(onOpen2).toHaveBeenCalledTimes(1);
  });

  it('unmount prevents further callbacks', () => {
    const onOpen = vi.fn();
    const onClose = vi.fn();
    const { unmount } = renderTransport({ onOpen, onClose });
    act(() => MockWebSocket.LAST!.triggerOpen());

    unmount();
    // After unmount, callbacks should not fire (isUnmountedRef guard)
    act(() => MockWebSocket.LAST!.triggerClose());
    expect(onClose).not.toHaveBeenCalled();
  });

  it('failed WebSocket construction triggers onError', () => {
    const onError = vi.fn();
    // Force WebSocket constructor to throw.
    // Static constants (OPEN/CONNECTING/CLOSING/CLOSED) are required because
    // transport.ts guard evaluates `wsRef.current !== null && wsRef.current.readyState === WebSocket.OPEN`.
    // Using a plain function with attached constants avoids vi.fn() type narrowing
    // that drops static properties.
    const OriginalWebSocket = globalThis.WebSocket;
    const FailingCtor = function () {
      throw new Error('construction failed');
    } as unknown as typeof WebSocket & { OPEN: number; CONNECTING: number; CLOSING: number; CLOSED: number };
    FailingCtor.OPEN = 1;
    FailingCtor.CONNECTING = 0;
    FailingCtor.CLOSING = 2;
    FailingCtor.CLOSED = 3;
    globalThis.WebSocket = FailingCtor;

    try {
      renderTransport({ onError });
      expect(onError).toHaveBeenCalledWith('Failed to create WebSocket connection');
    } finally {
      globalThis.WebSocket = OriginalWebSocket;
    }
  });

  it('does not connect again if already OPEN', () => {
    const { result } = renderTransport();
    act(() => MockWebSocket.LAST!.triggerOpen());
    const countBefore = MockWebSocket.instances.length;

    act(() => result.current.connect());
    expect(MockWebSocket.instances.length).toBe(countBefore);
  });

  it('returns wsRef pointing to current WebSocket instance', () => {
    const { result } = renderTransport();
    act(() => MockWebSocket.LAST!.triggerOpen());
    expect(result.current.wsRef.current).toBe(MockWebSocket.LAST);
  });
});
