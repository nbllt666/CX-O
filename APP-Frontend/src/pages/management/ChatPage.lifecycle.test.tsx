import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChatPage from './ChatPage';
import { chatApi, type StreamChunk } from '@/api/clients/chat';
import { agentsApi } from '@/api/clients/agents';
import { useChatStore } from '@/store/chatStore';
import i18n from '@/i18n';

vi.mock('@/api/clients/agents', () => ({ agentsApi: { getAgents: vi.fn() } }));
vi.mock('@/api/clients/chat', () => ({ chatApi: { getChatHistory: vi.fn(), sendMessageStream: vi.fn() } }));
const markdownRender = vi.hoisted(() => vi.fn((content: string) => content));
vi.mock('./MarkdownContent', () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{markdownRender(content)}</div>,
}));

class Socket {
  static instances: Socket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  send = vi.fn();
  constructor() { Socket.instances.push(this); }
  close() { this.readyState = Socket.CLOSED; }
  open() { this.readyState = Socket.OPEN; this.onopen?.(); }
  emit(data: unknown) { this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) })); }
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const mockedChat = vi.mocked(chatApi);
const AGENTS = [{ id: 'a1', name: '代理甲', is_default: true }, { id: 'a2', name: '代理乙' }];
const input = () => screen.getByPlaceholderText(/输入消息/);
const lastSocket = () => Socket.instances[Socket.instances.length - 1];
function send(text: string) {
  fireEvent.change(input(), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: '发送' }));
}
async function ready() {
  const view = render(<ChatPage />);
  await screen.findByText('代理甲');
  await act(async () => {});
  return view;
}

beforeEach(async () => {
  vi.clearAllMocks();
  Socket.instances = [];
  vi.stubGlobal('WebSocket', Socket);
  await i18n.changeLanguage('zh-CN');
  useChatStore.setState({ agents: [], currentAgentId: null, isLoadingAgents: false });
  vi.mocked(agentsApi.getAgents).mockResolvedValue(AGENTS);
  mockedChat.getChatHistory.mockResolvedValue({ messages: [] });
  mockedChat.sendMessageStream.mockResolvedValue(undefined);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('聊天会话异步边界', () => {
  it('实际后端 SSE error 的 message 字段显示为错误而非 unknown 或完成', async () => {
    mockedChat.sendMessageStream.mockImplementationOnce(async (_text, onChunk) => {
      onChunk({ type: 'session', session_id: 'agent-a1' });
      onChunk({ type: 'error', message: '流式聊天处理失败，请稍后重试' });
    });
    await ready();
    await act(async () => send('失败请求'));
    expect(screen.getByText(/流式聊天处理失败，请稍后重试/)).toBeVisible();
    expect(screen.queryByText(/unknown|响应已完成/)).not.toBeInTheDocument();
    expect(screen.queryByTitle('停止')).not.toBeInTheDocument();
  });

  it('历史未返回时按钮和 Enter 均不可发送，历史到达后可正常发送', async () => {
    const history = deferred<Awaited<ReturnType<typeof chatApi.getChatHistory>>>();
    mockedChat.getChatHistory.mockReturnValue(history.promise);
    await ready();
    fireEvent.change(input(), { target: { value: '新问题' } });
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled();
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(mockedChat.sendMessageStream).not.toHaveBeenCalled();
    await act(async () => history.resolve({ messages: [{ id: 'old', role: 'assistant', content: '历史回复', created_at: '2026-10-10T10:00:00Z' }] }));
    expect(screen.getByRole('button', { name: '发送' })).toBeEnabled();
    await act(async () => send('新问题'));
    expect(screen.getByText('历史回复')).toBeVisible();
    expect(screen.getByText('新问题')).toBeVisible();
    expect(mockedChat.sendMessageStream).toHaveBeenCalledOnce();
  });

  it.each(['resolve', 'reject'] as const)('SSE 切 Agent 会中止旧流，迟到内容和 %s 不污染新流，卸载也中止', async (ending) => {
    const old = deferred<void>();
    const fresh = deferred<void>();
    let emitOld!: (chunk: StreamChunk) => void;
    let emitFresh!: (chunk: StreamChunk) => void;
    let oldSignal!: AbortSignal;
    let freshSignal!: AbortSignal;
    mockedChat.sendMessageStream
      .mockImplementationOnce((_text, onChunk, _agent, _images, signal) => {
        emitOld = onChunk; oldSignal = signal!; return old.promise;
      })
      .mockImplementationOnce((_text, onChunk, _agent, _images, signal) => {
        emitFresh = onChunk; freshSignal = signal!; return fresh.promise;
      });
    const view = await ready();
    send('甲问题');
    expect(screen.getByTitle('停止')).toBeVisible();
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'a2' } });
    await act(async () => {});
    expect(oldSignal.aborted).toBe(true);
    expect(screen.queryByTitle('停止')).not.toBeInTheDocument();
    send('乙问题');
    await act(async () => {
      emitFresh({ type: 'content', content: '乙的回复' });
      emitOld({ type: 'content', content: '旧流残留' });
      emitOld({ type: 'done' });
      if (ending === 'resolve') old.resolve(); else old.reject(new Error('旧流失败'));
    });
    expect(screen.getByText('乙的回复')).toBeVisible();
    expect(screen.queryByText('旧流残留')).not.toBeInTheDocument();
    expect(screen.queryByText('甲问题')).not.toBeInTheDocument();
    expect(screen.getByTitle('停止')).toBeVisible();
    view.unmount();
    expect(freshSignal.aborted).toBe(true);
    await act(async () => fresh.resolve());
  });

  it('WS 生成中切 Agent 清理 loading，旧 socket 的消息/错误/open 无法污染新连接', async () => {
    await ready();
    const old = lastSocket();
    act(() => old.open());
    send('甲问题');
    const lateMessage = old.onmessage!;
    const lateError = old.onerror!;
    const lateOpen = old.onopen!;
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'a2' } });
    await act(async () => {});
    expect(screen.queryByTitle('停止')).not.toBeInTheDocument();
    await waitFor(() => expect(lastSocket()).not.toBe(old));
    const fresh = lastSocket();
    act(() => fresh.open());
    send('乙问题');
    act(() => {
      fresh.emit({ type: 'content', content: '乙的回复' });
      lateMessage(new MessageEvent('message', { data: JSON.stringify({ type: 'content', content: '旧残留' }) }));
      lateMessage(new MessageEvent('message', { data: JSON.stringify({ type: 'done' }) }));
      lateError(); lateOpen();
    });
    expect(screen.getByText('乙的回复')).toBeVisible();
    expect(screen.queryByText(/旧残留/)).not.toBeInTheDocument();
    expect(screen.getByTitle('停止')).toBeVisible();
    act(() => fresh.emit({ type: 'done' }));
    expect(screen.queryByTitle('停止')).not.toBeInTheDocument();
    expect(fresh.send.mock.calls.map(([data]) => JSON.parse(data))).toContainEqual(expect.objectContaining({ type: 'config', agent_id: 'a2' }));
  });

  it('梦境插入后回复继续更新；50 条历史在 20 次流更新中不重渲染', async () => {
    mockedChat.getChatHistory.mockResolvedValue({ messages: Array.from({ length: 50 }, (_, index) => ({
      id: `history-${index}`, role: 'assistant', content: `历史-${index}`, created_at: '2026-10-10T10:00:00Z',
    })) });
    await ready();
    const ws = lastSocket();
    act(() => ws.open());
    send('继续');
    const historyRenders = () => markdownRender.mock.calls.filter(([content]) => content.startsWith('历史-')).length;
    const before = historyRenders();
    act(() => ws.emit({ type: 'dream.surface', data: { content: '梦境插入' } }));
    for (let i = 0; i < 20; i += 1) act(() => ws.emit({ type: 'content', content: '续' }));
    expect(screen.getByText('续'.repeat(20))).toBeVisible();
    expect(screen.getByText('（梦境）梦境插入')).toBeVisible();
    act(() => ws.emit({ type: 'done' }));
    expect(historyRenders()).toBe(before);
    expect(before).toBe(50);
    console.log(`[O02] history=50, streamUpdates=20, additionalHistoryRenders=${historyRenders() - before}, avoidedAtLeast=1000`);
  });

  it.each(['error', 'disconnect', 'done', 'content', 'chat_response'] as const)(
    'SSE 生成不受当前 WS 的 %s 干扰，独立梦境仍可展示',
    async (event) => {
      const stream = deferred<void>();
      let emit!: (chunk: StreamChunk) => void;
      mockedChat.sendMessageStream.mockImplementationOnce((_text, onChunk) => {
        emit = onChunk;
        return stream.promise;
      });
      await ready();
      const ws = lastSocket();
      send('SSE 问题');
      act(() => emit({ type: 'content', content: '正在回答' }));
      act(() => {
        // 独立推送由仍有效的连接投递；关闭后的旧 socket 不能继续发消息。
        ws.emit({ type: 'dream.surface', data: { content: '独立梦境' } });
        if (event === 'error') ws.onerror?.();
        else if (event === 'disconnect') ws.onclose?.();
        else ws.emit({ type: event, content: '其他通道内容' });
      });
      expect(screen.getByText('正在回答')).toBeVisible();
      expect(screen.queryByText(/其他通道内容|WebSocket connection error/)).not.toBeInTheDocument();
      expect(screen.getByText('（梦境）独立梦境')).toBeVisible();
      expect(screen.getByTitle('停止')).toBeVisible();
      await act(async () => {
        emit({ type: 'content', content: '完成' });
        stream.resolve();
      });
      expect(screen.getByText('正在回答完成')).toBeVisible();
      expect(screen.queryByTitle('停止')).not.toBeInTheDocument();
      act(() => ws.onerror?.());
      expect(screen.getByText('正在回答完成')).toBeVisible();
    },
  );
});
