import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import AgentsPage from './AgentsPage';
import i18n from '../../i18n';
import { agentsApi } from '@/api/clients/agents';
import type { Agent } from '@/api/types';

/**
 * AgentsPage 冒烟 + 关键交互测试（SubTask 7.1）：
 * agentsApi 整体打桩，避免真实网络；覆盖统计渲染、列表渲染、
 * 新建弹窗提交、克隆与删除调用、加载失败重试。
 */
vi.mock('@/api/clients/agents', () => ({
  agentsApi: {
    getAgents: vi.fn(),
    getAvailableModels: vi.fn(),
    createAgent: vi.fn(),
    updateAgent: vi.fn(),
    cloneAgent: vi.fn(),
    deleteAgent: vi.fn(),
  },
}));

const mocked = vi.mocked(agentsApi);

const SAMPLE_AGENTS: Agent[] = [
  {
    id: 'default',
    name: '主代理',
    description: '默认对话代理',
    is_default: true,
    model: 'main',
    temperature: 0.7,
    memory_scene: 'chat',
    updated_at: '2026-08-07 10:00:00',
  },
  {
    id: 'coder',
    name: '编程助手',
    description: '写代码',
    is_default: false,
    model: 'gpt-x',
    temperature: 0.3,
    memory_scene: 'task',
    updated_at: '2026-08-06 09:00:00',
  },
];

describe('AgentsPage 代理页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染统计行与代理卡片列表', async () => {
    mocked.getAgents.mockResolvedValue(SAMPLE_AGENTS);
    mocked.getAvailableModels.mockResolvedValue({ models: ['main', 'gpt-x'] });

    render(<AgentsPage />);

    // 统计：2 个代理、2 个模型、默认代理名
    // 「主代理」同时出现在统计行默认值与列表卡片标题，用 findAllByText 断言
    expect((await screen.findAllByText('主代理')).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('编程助手')).toBeInTheDocument();
    expect(screen.getByText('代理总数')).toBeInTheDocument();
    expect(screen.getByText('默认代理')).toBeInTheDocument();
    expect(screen.getByText('可用模型')).toBeInTheDocument();
    // 默认徽章仅出现在默认代理卡片上
    expect(screen.getAllByText('默认').length).toBeGreaterThanOrEqual(1);
    // 非默认代理有删除按钮；默认代理无删除按钮（只有编辑/克隆 2 个操作 + 页面级按钮）
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('加载失败显示错误态，点击重试重新拉取', async () => {
    mocked.getAgents.mockRejectedValueOnce(new Error('network down'));
    mocked.getAvailableModels.mockResolvedValue({ models: [] });

    render(<AgentsPage />);

    expect(
      await screen.findByText('加载失败，请检查后端连接后重试'),
    ).toBeInTheDocument();

    mocked.getAgents.mockResolvedValue(SAMPLE_AGENTS);
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect((await screen.findAllByText('主代理')).length).toBeGreaterThanOrEqual(1);
  });

  it('新建弹窗填写名称后提交调用 createAgent', async () => {
    mocked.getAgents.mockResolvedValue([]);
    mocked.getAvailableModels.mockResolvedValue({ models: ['main'] });
    mocked.createAgent.mockResolvedValue(SAMPLE_AGENTS[0]);

    render(<AgentsPage />);
    // 空列表态
    expect(await screen.findByText('暂无代理，点击右上角新建')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /新建代理/ }));
    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '测试代理' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(mocked.createAgent).toHaveBeenCalledWith(
        expect.objectContaining({ name: '测试代理' }),
      );
    });
  });

  it('新建弹窗含语音快速记忆开关且随提交下发', async () => {
    mocked.getAgents.mockResolvedValue([]);
    mocked.getAvailableModels.mockResolvedValue({ models: ['main'] });
    mocked.createAgent.mockResolvedValue(SAMPLE_AGENTS[0]);

    render(<AgentsPage />);
    await screen.findByText('暂无代理，点击右上角新建');
    fireEvent.click(screen.getByRole('button', { name: /新建代理/ }));

    // 开关默认关闭
    const sw = screen.getByRole('switch', { name: '语音快速记忆' });
    expect(sw.getAttribute('aria-checked')).toBe('false');
    // 打开开关
    fireEvent.click(sw);
    expect(sw.getAttribute('aria-checked')).toBe('true');

    fireEvent.change(screen.getByLabelText('名称'), { target: { value: '语音代理' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(mocked.createAgent).toHaveBeenCalledWith(
        expect.objectContaining({ name: '语音代理', voice_memory_fast: true }),
      );
    });
  });

  it('克隆与删除调用对应 API（删除需确认）', async () => {
    mocked.getAgents.mockResolvedValue(SAMPLE_AGENTS);
    mocked.getAvailableModels.mockResolvedValue({ models: [] });
    mocked.cloneAgent.mockResolvedValue({ ...SAMPLE_AGENTS[1], id: 'coder-copy' });
    mocked.deleteAgent.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<AgentsPage />);
    expect(await screen.findByText('编程助手')).toBeInTheDocument();

    // 克隆（两张卡片各有克隆按钮，取第一个即默认代理的）
    const cloneButtons = screen.getAllByRole('button', { name: '克隆' });
    fireEvent.click(cloneButtons[0]);
    await waitFor(() => {
      expect(mocked.cloneAgent).toHaveBeenCalledWith('default');
    });

    // 删除：默认代理无删除按钮，仅非默认代理有
    const deleteButtons = screen.getAllByRole('button', { name: '删除' });
    expect(deleteButtons).toHaveLength(1);
    fireEvent.click(deleteButtons[0]);
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(mocked.deleteAgent).toHaveBeenCalledWith('coder');
    });
    confirmSpy.mockRestore();
  });
});
