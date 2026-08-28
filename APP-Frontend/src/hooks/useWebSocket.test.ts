/**
 * useWebSocket 服务端干净关闭回调集成测试（第四轮体检 G 组 M2）。
 *
 * 场景：服务端干净关闭（close code=1000）只派发 close 事件、不派发 error 事件——
 * caller 的 onDisconnect 必须被调用（PetPage 依赖它复位 isLoading / asrMsgIdRef，
 * 否则页面加载态永久卡死）。WebSocket 全局以 Mock 替身注入。
 *
 * 另含 D6/D9 新增路由用例：voice.speaker 回调、cluster_event toast、事件存档。
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';

import { useWebSocket } from './useWebSocket';
import { useToastStore } from '../store/toastStore';
import { useEventsStore } from '../store/eventsStore';

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

/** 打开一条 Mock WS 连接并返回它（D6/D9 用例共用） */
async function openMockWs() {
  renderHook(() => useWebSocket({ agentId: 'agent-d6d9' }));
  await act(async () => {});
  const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
  await act(async () => {
    ws.open();
  });
  return ws;
}

/** 经 Mock WS 下发一条服务端 JSON 消息 */
async function serverSend(ws: MockWebSocket, payload: unknown) {
  await act(async () => {
    ws.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }));
  });
}

describe('useWebSocket voice.speaker 路由（D6）', () => {
  it('收到 voice.speaker：onSpeaker 回调触发并收到解析后的说话人数据', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    const onSpeaker = vi.fn();

    renderHook(() => useWebSocket({ agentId: 'agent-d6', onSpeaker }));
    await act(async () => {});
    const ws = MockWebSocket.instances[MockWebSocket.instances.length - 1];
    await act(async () => {
      ws.open();
    });
    await serverSend(ws, {
      type: 'voice.speaker',
      data: {
        speaker_status: 'ready',
        speaker_id: 'spk_1',
        speaker_name: '小明',
        speaker_registered: true,
        speaker_conf: 0.93,
      },
    });

    expect(onSpeaker).toHaveBeenCalledTimes(1);
    expect(onSpeaker).toHaveBeenCalledWith({
      speakerId: 'spk_1',
      speakerName: '小明',
      speakerRegistered: true,
      speakerConf: 0.93,
    });
  });
});

describe('useWebSocket 广播事件消费（D9）', () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
    useEventsStore.setState({ events: [] });
  });

  it('cluster_event 切换/故障类弹 toast（node_joined 不弹）；autonomy_cost_alert 直接弹；skill_triggered 入事件存档', async () => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    const ws = await openMockWs();

    // 集群切换/故障类主题 → 弹 toast
    await serverSend(ws, {
      type: 'cluster_event',
      data: { topic: 'cluster.failover_started', node_id: 'n1', data: { from_node: 'peer-a' } },
    });
    expect(useToastStore.getState().toasts).toHaveLength(1);
    expect(useToastStore.getState().toasts[0]?.kind).toBe('cluster');
    expect(useToastStore.getState().toasts[0]?.topic).toBe('cluster.failover_started');

    // 拓扑加入类主题 → 不弹（防刷屏）
    await serverSend(ws, {
      type: 'cluster_event',
      data: { topic: 'cluster.node_joined', data: { endpoint: 'peer-b' } },
    });
    expect(useToastStore.getState().toasts).toHaveLength(1);

    // 成本告警 → 直接弹
    await serverSend(ws, {
      type: 'autonomy_cost_alert',
      data: { usage_ratio: 0.9, daily_used: 900, limit: 1000, date: '2026-08-28' },
    });
    expect(useToastStore.getState().toasts).toHaveLength(2);
    expect(useToastStore.getState().toasts[1]?.kind).toBe('cost');

    // skill_triggered → 入有界事件存档（不做 UI）
    await serverSend(ws, {
      type: 'skill_triggered',
      data: { skill_name: 'demo', event_type: 'trigger' },
    });
    expect(useEventsStore.getState().events).toHaveLength(1);
    expect(useEventsStore.getState().events[0]?.type).toBe('skill_triggered');
    expect(useToastStore.getState().toasts).toHaveLength(2);
  });
});
