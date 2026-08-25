import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import AcpPage from './AcpPage';
import i18n from '../../i18n';
import { agentsApi } from '@/api/clients/agents';
import type { AcpAgentRow, AcpMessage } from '@/api/types';

/**
 * AcpPage 冒烟 + 关键交互测试（SubTask 7.1）：
 * agentsApi ACP 方法整体打桩；覆盖统计渲染、代理列表、状态切换、
 * 消息面板选择与发送、加载失败重试。
 */
vi.mock('@/api/clients/agents', () => ({
  agentsApi: {
    getAcpStats: vi.fn(),
    getAcpAgents: vi.fn(),
    createAcpAgent: vi.fn(),
    updateAcpAgent: vi.fn(),
    deleteAcpAgent: vi.fn(),
    getAcpMessages: vi.fn(),
    sendAcpMessage: vi.fn(),
  },
}));

const mocked = vi.mocked(agentsApi);

const SAMPLE_AGENTS: AcpAgentRow[] = [
  {
    id: 'peer-1',
    name: '远端小助手',
    description: '局域网对端',
    capabilities: ['chat', 'search'],
    status: 'active',
  },
  {
    id: 'peer-2',
    name: '备用代理',
    description: '',
    capabilities: [],
    status: 'inactive',
  },
];

const SAMPLE_MESSAGES: AcpMessage[] = [
  {
    id: 'm1',
    type: 'chat',
    from_agent_id: 'local',
    from_agent_name: '本机',
    to_agent_id: 'peer-1',
    to_group_id: null,
    content: { text: '你好' },
    timestamp: '2026-08-07T10:00:00Z',
    is_read: true,
    is_sent: true,
    metadata: {},
  },
];

describe('AcpPage ACP 页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染统计行与代理列表', async () => {
    mocked.getAcpStats.mockResolvedValue({
      total_agents: 2,
      active_agents: 1,
      total_messages: 5,
    });
    mocked.getAcpAgents.mockResolvedValue(SAMPLE_AGENTS);

    render(<AcpPage />);

    expect(await screen.findByText('远端小助手')).toBeInTheDocument();
    expect(screen.getByText('备用代理')).toBeInTheDocument();
    expect(screen.getByText('代理总数')).toBeInTheDocument();
    expect(screen.getByText('活跃代理')).toBeInTheDocument();
    expect(screen.getByText('消息总数')).toBeInTheDocument();
    expect(screen.getByText('chat')).toBeInTheDocument();
    expect(screen.getByText('活跃')).toBeInTheDocument();
    expect(screen.getByText('停用')).toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('加载失败显示错误态，点击重试重新拉取', async () => {
    mocked.getAcpStats.mockResolvedValue({
      total_agents: 0,
      active_agents: 0,
      total_messages: 0,
    });
    mocked.getAcpAgents.mockRejectedValueOnce(new Error('network down'));

    render(<AcpPage />);

    expect(
      await screen.findByText('加载失败，请检查后端连接后重试'),
    ).toBeInTheDocument();

    mocked.getAcpAgents.mockResolvedValue(SAMPLE_AGENTS);
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('远端小助手')).toBeInTheDocument();
  });

  it('切换启停调用 updateAcpAgent 并传入反转状态', async () => {
    mocked.getAcpStats.mockResolvedValue({
      total_agents: 2,
      active_agents: 1,
      total_messages: 0,
    });
    mocked.getAcpAgents.mockResolvedValue(SAMPLE_AGENTS);
    mocked.updateAcpAgent.mockResolvedValue(undefined);

    render(<AcpPage />);
    expect(await screen.findByText('远端小助手')).toBeInTheDocument();

    const toggleButtons = screen.getAllByRole('button', { name: '切换启停' });
    fireEvent.click(toggleButtons[0]);
    await waitFor(() => {
      expect(mocked.updateAcpAgent).toHaveBeenCalledWith('peer-1', { status: 'inactive' });
    });
  });

  it('选择代理后加载消息，可发送 ACP 消息', async () => {
    mocked.getAcpStats.mockResolvedValue({
      total_agents: 1,
      active_agents: 1,
      total_messages: 1,
    });
    mocked.getAcpAgents.mockResolvedValue([SAMPLE_AGENTS[0]]);
    mocked.getAcpMessages.mockResolvedValue({
      status: 'success',
      messages: SAMPLE_MESSAGES,
      total: 1,
    });
    mocked.sendAcpMessage.mockResolvedValue({
      status: 'success',
      message_id: 'm2',
      message: 'ok',
    });

    render(<AcpPage />);
    fireEvent.click(await screen.findByText('远端小助手'));

    // 消息历史加载
    expect(await screen.findByText('你好')).toBeInTheDocument();
    expect(mocked.getAcpMessages).toHaveBeenCalledWith('peer-1', 50);

    // 发送消息
    fireEvent.change(screen.getByLabelText(/向 远端小助手 发送/), {
      target: { value: '测试消息' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送' }));
    await waitFor(() => {
      expect(mocked.sendAcpMessage).toHaveBeenCalledWith('peer-1', '测试消息');
    });
  });
});
