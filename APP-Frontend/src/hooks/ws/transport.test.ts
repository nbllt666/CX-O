/**
 * useWSTransport 传输层单测（第四轮体检 G 组 L6 + M2 底座）。
 *
 * Mock WebSocket 模拟 readyState 流转，覆盖：
 * - L6a：connect 守卫对 CLOSING 半关闭态的拦截（防新旧 socket 并存）
 * - L6b：迟到旧 socket onclose 的身份校验（不污染新连接状态/不重复回调与重连调度）
 * - M2 底座：服务端干净关闭（code=1000）仅经 close 事件触发 caller onClose
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

import { useWSTransport } from './transport';

const READY_STATE = { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 } as const;

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = READY_STATE.CONNECTING;
  static OPEN = READY_STATE.OPEN;
  static CLOSING = READY_STATE.CLOSING;
  static CLOSED = READY_STATE.CLOSED;

  url: string;
  binaryType: string | undefined;
  readyState: number = READY_STATE.CONNECTING;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: Event) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    if (this.readyState === READY_STATE.CLOSED || this.readyState === READY_STATE.CLOSING) return;
    // 真实浏览器：readyState 先变 CLOSED，close 事件在后续任务派发——本 mock 不自动派发，
    // 由用例显式调用 serverClose()/lateClose() 控制事件时序
    this.readyState = READY_STATE.CLOSED;
  });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  /** 模拟连接建立成功 */
  open(): void {
    this.readyState = READY_STATE.OPEN;
    this.onopen?.(new Event('open'));
  }

  /** 模拟服务端关闭并派发 close 事件（可选携带 code，如 1000 干净关闭） */
  serverClose(code = 1000): void {
    this.readyState = READY_STATE.CLOSED;
    const ev = Object.assign(new Event('close'), { code, wasClean: true });
    this.onclose?.(ev as unknown as Event);
  }
}

function lastInstance(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe('useWSTransport connect 守卫与 onclose 身份校验（L6）', () => {
  it('L6a: socket 处于 CLOSING 半关闭态时 connect 不新建', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    const { result } = renderHook(() =>
      useWSTransport({ urlBuilder: () => 'ws://test/ws', reconnect: { strategy: 'none' } }),
    );
    await act(async () => {});

    const first = lastInstance();
    first.open();
    // 半关闭态（close 已发起但尚未彻底关闭）
    first.readyState = READY_STATE.CLOSING;
    const before = MockWebSocket.instances.length;
    result.current.connect();

    expect(MockWebSocket.instances.length).toBe(before);
    expect(lastInstance().readyState).toBe(READY_STATE.CLOSING);
  });

  it('L6b: 迟到的旧 socket onclose 不污染新连接、不重复触发 onClose 与重连调度', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useWSTransport({
        urlBuilder: () => 'ws://test/ws',
        reconnect: { strategy: 'fixed', delay: 30 },
        onClose,
      }),
    );
    await act(async () => {});

    const old = lastInstance();
    await act(async () => {
      old.open();
    });
    expect(result.current.isConnected).toBe(true);

    // 模拟「readyState 已 CLOSED 但 close 事件未派发」的真实窗口内新建后继连接：
    old.close(); // readyState → CLOSED（不派发事件）
    result.current.connect(); // 守卫见 CLOSED 放行 → 新建
    const fresh = lastInstance();
    expect(fresh).not.toBe(old);
    await act(async () => {
      fresh.open();
    });

    // 迟到的旧 socket close 事件此刻到达
    old.serverClose(1006);

    // 身份校验拦截：新连接状态不被污染、onClose 不被重复触发、无叠加重连定时器效果
    expect(result.current.isConnected).toBe(true);
    expect(onClose).not.toHaveBeenCalled();

    // 新连接自身正常关闭时，闭环仍然工作
    await act(async () => {
      fresh.serverClose(1000);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(result.current.isConnected).toBe(false);
  });
});

describe('useWSTransport 服务端干净关闭回调语义（M2 底座）', () => {
  it('M2: 服务端干净关闭(code=1000) 仅经 close 事件触发 caller onClose 并按策略重连', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    const onError = vi.fn();
    const onClose = vi.fn();
    const { result } = renderHook(() =>
      useWSTransport({
        urlBuilder: () => 'ws://test/ws',
        reconnect: { strategy: 'fixed', delay: 25 },
        onClose,
        onError,
      }),
    );
    await act(async () => {});

    const ws = lastInstance();
    await act(async () => {
      ws.open();
    });
    expect(result.current.isConnected).toBe(true);

    // 服务端干净关闭：不应走 error 分支
    await act(async () => {
      ws.serverClose(1000);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onError).not.toHaveBeenCalled();
    expect(result.current.isConnected).toBe(false);

    // fixed 重连按 delay 到期后建立新连接
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(MockWebSocket.instances.length).toBeGreaterThanOrEqual(2);
    expect(lastInstance()).not.toBe(ws);
  });
});
