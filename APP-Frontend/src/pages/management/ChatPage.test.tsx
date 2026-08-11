import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import ChatPage from './ChatPage';
import i18n from '../../i18n';
import { agentsApi } from '@/api/clients/agents';
import { chatApi } from '@/api/clients/chat';

/**
 * ChatPage 对话页核心场景测试（Task 8 功能增强）：
 * - Markdown 渲染：assistant 历史消息正文渲染为 Markdown（加粗/代码块/表格）
 * - ToolCall 状态链：tool_call → tool_start → tool_result 驱动状态徽章 + 参数/结果折叠
 * - Thinking 折叠：流式 thinking 默认收起，点击展开
 * mock 面：agentsApi / chatApi / useWebSocket（WS 置为未连接，走 HTTP SSE 链路）。
 */
vi.mock('@/api/clients/agents', () => ({
  agentsApi: { getAgents: vi.fn() },
}));

vi.mock('@/api/clients/chat', () => ({
  chatApi: { getChatHistory: vi.fn(), sendMessageStream: vi.fn() },
}));

const mockWs = vi.hoisted(() => ({
  isConnected: false,
  sendMessage: vi.fn(),
  cancelGeneration: vi.fn(),
}));

vi.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: () => ({
    isConnected: mockWs.isConnected,
    isGenerating: false,
    isTTSPlaying: false,
    sendMessage: mockWs.sendMessage,
    cancelGeneration: mockWs.cancelGeneration,
    disconnect: vi.fn(),
    reconnect: vi.fn(),
    sendDualStream: vi.fn(),
    interruptTTS: vi.fn(),
    sendRaw: vi.fn(),
    getTTSAnalyser: () => null,
    setTTSVolume: vi.fn(),
  }),
}));

const mockedAgents = vi.mocked(agentsApi);
const mockedChat = vi.mocked(chatApi);

const AGENT = { id: 'a1', name: '测试代理', is_default: true };

describe('ChatPage 对话页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  async function renderReady() {
    mockedAgents.getAgents.mockResolvedValue([AGENT]);
    render(<ChatPage />);
    // fetchAgents 异步完成后 currentAgentId 就位，历史加载 effect 触发
    await screen.findByText('测试代理');
  }

  it('assistant 历史消息正文渲染为 Markdown（加粗 / 代码块 / 表格）', async () => {
    mockedChat.getChatHistory.mockResolvedValue({
      messages: [
        {
          id: 'h1',
          role: 'assistant',
          content:
            '**加粗文字** 与 `行内代码`\n\n```ts\nconst x = 1;\n```\n\n| A | B |\n|---|---|\n| 1 | 2 |',
          created_at: '2026-08-07 10:00:00',
        },
      ],
    });

    await renderReady();

    expect(await screen.findByText('加粗文字')).toBeInTheDocument();
    expect(screen.getByText('const x = 1;')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('ToolCall 状态链：tool_call/tool_start/tool_result 渲染状态徽章与参数结果折叠', async () => {
    mockedChat.getChatHistory.mockResolvedValue({ messages: [] });
    mockedChat.sendMessageStream.mockImplementation(async (_msg, onChunk) => {
      onChunk({ type: 'tool_call', tool_call: { id: 'tc1', name: 'search', arguments: { q: 'x' } } });
      onChunk({ type: 'tool_start', tool_name: 'search' });
      onChunk({ type: 'tool_result', tool_name: 'search', result: { count: 2 } });
      onChunk({ type: 'content', content: '查询完成' });
    });

    await renderReady();

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: '查一下' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    // 工具调用在 ThinkingProcess 折叠块内，先展开
    const thinkBtn = await screen.findByRole('button', { name: /思考过程/ });
    fireEvent.click(thinkBtn);

    expect(await screen.findByText('search')).toBeInTheDocument();
    expect(screen.getByText('完成')).toBeInTheDocument();

    // 展开工具条目，展示参数/结果折叠区
    fireEvent.click(screen.getByText('search'));
    expect(screen.getByText('参数')).toBeInTheDocument();
    expect(screen.getByText('结果')).toBeInTheDocument();
  });

  it('Thinking 折叠：流式 thinking 默认收起，点击后展开', async () => {
    mockedChat.getChatHistory.mockResolvedValue({ messages: [] });
    mockedChat.sendMessageStream.mockImplementation(async (_msg, onChunk) => {
      onChunk({ type: 'thinking', content: '先想再想' });
      onChunk({ type: 'content', content: '正文' });
    });

    await renderReady();

    fireEvent.change(screen.getByPlaceholderText(/输入消息/), { target: { value: 'hi' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    const thinkBtn = await screen.findByRole('button', { name: /思考过程/ });
    // 默认收起：思考文本不在 DOM
    expect(screen.queryByText('先想再想')).not.toBeInTheDocument();

    fireEvent.click(thinkBtn);
    expect(await screen.findByText('先想再想')).toBeInTheDocument();
  });
});