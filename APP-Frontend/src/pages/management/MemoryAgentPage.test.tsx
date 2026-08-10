import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import MemoryAgentPage from './MemoryAgentPage';
import i18n from '../../i18n';
import { agentsApi } from '@/api/clients/agents';
import { chatApi } from '@/api/clients/chat';

/**
 * MemoryAgentPage 冒烟 + 关键交互测试（SubTask 7.3）：
 * agentsApi / chatApi 整体打桩；覆盖历史加载、空态示例、
 * 流式发送（content/thinking/tool_call/done 归约）、清空对话。
 */
vi.mock('@/api/clients/agents', () => ({
  agentsApi: {
    getAgentContext: vi.fn(),
    clearAgentContext: vi.fn(),
  },
}));

vi.mock('@/api/clients/chat', () => ({
  chatApi: {
    sendMemoryAgentMessageStream: vi.fn(),
  },
}));

const mockedAgents = vi.mocked(agentsApi);
const mockedChat = vi.mocked(chatApi);

describe('MemoryAgentPage 记忆代理页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('加载历史消息并渲染 user/assistant 气泡', async () => {
    mockedAgents.getAgentContext.mockResolvedValue({
      recent_messages: [
        { role: 'user', content: '搜索工作记忆', created_at: '2026-08-07 10:00:00' },
        { role: 'assistant', content: '找到 3 条相关记忆', created_at: '2026-08-07 10:00:05' },
        { role: 'system', content: '系统消息应被过滤', created_at: '2026-08-07 10:00:06' },
      ],
    });

    render(<MemoryAgentPage />);

    expect(await screen.findByText('搜索工作记忆')).toBeInTheDocument();
    expect(screen.getByText('找到 3 条相关记忆')).toBeInTheDocument();
    expect(screen.queryByText('系统消息应被过滤')).not.toBeInTheDocument();
    expect(mockedAgents.getAgentContext).toHaveBeenCalledWith('memory-agent');
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('无历史时渲染空态与示例指令', async () => {
    mockedAgents.getAgentContext.mockResolvedValue({ recent_messages: [] });

    render(<MemoryAgentPage />);

    expect(await screen.findByText('记忆管理助手')).toBeInTheDocument();
    expect(screen.getByText('示例指令：')).toBeInTheDocument();
    expect(screen.getByText(/搜索关于工作的记忆/)).toBeInTheDocument();
  });

  it('发送消息：流式 content 累积渲染，done 收尾', async () => {
    mockedAgents.getAgentContext.mockResolvedValue({ recent_messages: [] });
    mockedChat.sendMemoryAgentMessageStream.mockImplementation(async (_msg, onChunk) => {
      onChunk({ type: 'content', content: '已删除' });
      onChunk({ type: 'content', content: '记忆 123' });
      onChunk({ type: 'done' });
    });

    render(<MemoryAgentPage />);
    expect(await screen.findByText('记忆管理助手')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/输入指令/), { target: { value: '删除记忆 123' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('删除记忆 123')).toBeInTheDocument();
    expect(await screen.findByText('已删除记忆 123')).toBeInTheDocument();
    expect(mockedChat.sendMemoryAgentMessageStream).toHaveBeenCalledWith(
      '删除记忆 123',
      expect.any(Function),
    );
  });

  it('工具调用事件渲染工具链徽章', async () => {
    mockedAgents.getAgentContext.mockResolvedValue({ recent_messages: [] });
    mockedChat.sendMemoryAgentMessageStream.mockImplementation(async (_msg, onChunk) => {
      onChunk({ type: 'tool_call', tool_call: { id: 'tc1', name: 'search_memories' } });
      onChunk({ type: 'tool_start', tool_name: 'search_memories' });
      onChunk({ type: 'tool_result', tool_name: 'search_memories', result: { count: 2 } });
      onChunk({ type: 'content', content: '查询完成' });
      onChunk({ type: 'done' });
    });

    render(<MemoryAgentPage />);
    expect(await screen.findByText('记忆管理助手')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/输入指令/), { target: { value: '查一下' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('search_memories')).toBeInTheDocument();
    expect(await screen.findByText('查询完成')).toBeInTheDocument();
  });

  it('清空对话：清空消息列表并调用 clearAgentContext', async () => {
    mockedAgents.getAgentContext.mockResolvedValue({
      recent_messages: [
        { role: 'user', content: '旧消息', created_at: '2026-08-07 09:00:00' },
      ],
    });
    mockedAgents.clearAgentContext.mockResolvedValue(undefined);

    render(<MemoryAgentPage />);
    expect(await screen.findByText('旧消息')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '清空对话' }));
    await waitFor(() => {
      expect(mockedAgents.clearAgentContext).toHaveBeenCalledWith('memory-agent');
    });
    expect(screen.queryByText('旧消息')).not.toBeInTheDocument();
    // 清空后回到空态
    expect(await screen.findByText('记忆管理助手')).toBeInTheDocument();
  });

  it('发送失败渲染错误气泡', async () => {
    mockedAgents.getAgentContext.mockResolvedValue({ recent_messages: [] });
    mockedChat.sendMemoryAgentMessageStream.mockRejectedValue(new Error('stream down'));

    render(<MemoryAgentPage />);
    expect(await screen.findByText('记忆管理助手')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/输入指令/), { target: { value: '测试' } });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));

    expect(await screen.findByText('发送失败，请稍后重试')).toBeInTheDocument();
  });
});
