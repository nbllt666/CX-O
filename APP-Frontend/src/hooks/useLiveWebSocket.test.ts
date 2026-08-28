/**
 * useLiveWebSocket sessionId 守卫回归测试（第四轮体检 G 组 M3）。
 *
 * 场景：sessionIdRef 同步与守卫合并前，顶部 ref-sync effect 先行同步使守卫
 * 比较恒为 false（死分支），sessionId 变更永远不会触发重连。修复后变更必须
 * 经 transportReconnect 重建带新 session_id 的连接。WebSocket 以 Mock 注入。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

import { useLiveWebSocket } from './useLiveWebSocket';

const READY_STATE = { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 } as const;

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = READY_STATE.CONNECTING;
  static OPEN = READY_STATE.OPEN;
  static CLOSING = READY_STATE.CLOSING;
  static CLOSED = READY_STATE.CLOSED;

  url: string;
  readyState: number = READY_STATE.CONNECTING;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  send = vi.fn();
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

function lastInstance(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

/** 消化 transportReconnect 内部 50ms 重连定时器 */
async function flushDelay(ms = 70): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('useLiveWebSocket sessionId 变更重连（M3）', () => {
  it('sessionId 变更时重建连接且新 URL 携带新 session_id', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);

    const { rerender } = renderHook(
      ({ sid }: { sid?: string }) => useLiveWebSocket({ sessionId: sid }),
      { initialProps: { sid: undefined as string | undefined } },
    );
    await flushDelay();

    // 初始连接不带 session_id
    const first = lastInstance();
    expect(first.url).toContain('/ws/live');
    expect(first.url).not.toContain('session_id');

    // sessionId 变更 → 守卫放行 → 断开 + 延迟重建
    rerender({ sid: 'room-1' });
    await flushDelay();

    const second = lastInstance();
    expect(second).not.toBe(first);
    expect(second.url).toContain('session_id=room-1');
  });

  it('sessionId 未变化时不触发重连', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);

    const { rerender } = renderHook(
      ({ sid }: { sid?: string }) => useLiveWebSocket({ sessionId: sid }),
      { initialProps: { sid: 'room-keep' as string | undefined } },
    );
    await flushDelay();
    const count = MockWebSocket.instances.length;

    // 相同值 rerender（如父组件无关状态更新导致）：守卫相等不动作
    rerender({ sid: 'room-keep' });
    await flushDelay();

    expect(MockWebSocket.instances.length).toBe(count);
  });
});

describe('useLiveWebSocket interrupt 消息路由（D5）', () => {
  it('收到 type=interrupt 时触发 onInterrupt 并透传 data', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);

    const onInterrupt = vi.fn();
    renderHook(() => useLiveWebSocket({ onInterrupt }));
    await flushDelay();

    // 建连 + 打开
    const ws = lastInstance();
    await act(async () => {
      ws.onopen?.(new Event('open'));
    });

    // 模拟后端 ASR 打断判定命中推送（live_client.py: {"type":"interrupt","data":{...}}）
    await act(async () => {
      ws.onmessage?.(
        new MessageEvent('message', {
          data: JSON.stringify({
            type: 'interrupt',
            data: { source: 'asr', text: '停一下', decision: 'barge_in' },
          }),
        }),
      );
    });

    expect(onInterrupt).toHaveBeenCalledTimes(1);
    expect(onInterrupt).toHaveBeenCalledWith({
      source: 'asr',
      text: '停一下',
      decision: 'barge_in',
    });
  });

  it('interrupt 消息缺 data 时不触发回调（与 tts_end 同口径防误触）', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);

    const onInterrupt = vi.fn();
    renderHook(() => useLiveWebSocket({ onInterrupt }));
    await flushDelay();

    const ws = lastInstance();
    await act(async () => {
      ws.onopen?.(new Event('open'));
    });
    await act(async () => {
      ws.onmessage?.(new MessageEvent('message', { data: JSON.stringify({ type: 'interrupt' }) }));
    });

    expect(onInterrupt).not.toHaveBeenCalled();
  });
});
