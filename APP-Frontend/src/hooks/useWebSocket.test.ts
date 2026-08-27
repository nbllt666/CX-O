/**
 * useWebSocket 服务端干净关闭回调集成测试（第四轮体检 G 组 M2）。
 *
 * 场景：服务端干净关闭（close code=1000）只派发 close 事件、不派发 error 事件——
 * caller 的 onDisconnect 必须被调用（PetPage 依赖它复位 isLoading / asrMsgIdRef，
 * 否则页面加载态永久卡死）。WebSocket 全局以 Mock 替身注入。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

import { useWebSocket } from './useWebSocket';

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

  open(): void {
    this.readyState = READY_STATE.OPEN;
    this.onopen?.(new Event('open'));
  }

  serverClose(code = 1000): void {
    this.readyState = READY_STATE.CLOSED;
    const ev = Object.assign(new Event('close'), { code, wasClean: true });
    this.onclose?.(ev as unknown as Event);
  }
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('useWebSocket onDisconnect 回调（M2）', () => {
  it('服务端干净关闭(code=1000)：onDisconnect 被调用且不走 error 分支', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    const onError = vi.fn();
    const onDisconnect = vi.fn();

    renderHook(() =>
      useWebSocket({
        agentId: 'agent-m2',
        timeout: 60,
        onDisconnect,
        onError,
      }),
    );
    await act(async () => {});

    // 连接指向聊天 WS 通道并成功建立
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    expect(ws).toBeDefined();
    expect(ws.url).toContain('/ws');
    await act(async () => {
      ws.open();
    });

    // 服务端干净关闭：仅派发 close(1000)
    await act(async () => {
      ws.serverClose(1000);
    });

    expect(onDisconnect).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
  });
});
