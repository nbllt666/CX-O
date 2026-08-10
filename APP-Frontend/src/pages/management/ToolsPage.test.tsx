import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import ToolsPage from './ToolsPage';
import i18n from '../../i18n';
import { toolsApi } from '@/api/clients/tools';
import type { Tool, ToolStats } from '@/api/types';

/**
 * ToolsPage 冒烟 + 关键交互测试（SubTask 7.2）：
 * toolsApi 整体打桩；覆盖统计渲染、类型筛选、启停切换、
 * 测试弹窗 JSON 参数解析与结果展示、自定义工具删除、加载失败重试。
 */
vi.mock('@/api/clients/tools', () => ({
  toolsApi: {
    getTools: vi.fn(),
    getToolsStats: vi.fn(),
    testTool: vi.fn(),
    updateTool: vi.fn(),
    deleteTool: vi.fn(),
  },
}));

const mocked = vi.mocked(toolsApi);

const SAMPLE_TOOLS: Record<string, Tool> = {
  calculator: {
    id: 'calculator',
    name: '计算器',
    description: '四则运算',
    type: 'builtin',
    status: 'active',
    config: {},
    created_at: '2026-08-01 00:00:00',
    use_count: 42,
    parameters: {
      properties: {
        expression: { type: 'string' },
      },
    },
  },
  web_search: {
    id: 'web_search',
    name: '网页搜索',
    description: 'MCP 搜索',
    type: 'mcp',
    status: 'inactive',
    config: {},
    created_at: '2026-08-02 00:00:00',
    use_count: 7,
  },
  my_custom: {
    id: 'my_custom',
    name: '自定义工具',
    description: '',
    type: 'custom',
    status: 'active',
    config: {},
    created_at: '2026-08-03 00:00:00',
    use_count: 0,
  },
};

const SAMPLE_STATS: ToolStats = {
  total_tools: 3,
  enabled_tools: 2,
  builtin_tools: 1,
  custom_tools: 1,
  active_tools: 2,
  mcp_tools: 1,
  total_calls: 49,
};

describe('ToolsPage 工具页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染统计行与工具卡片（含类型徽章与参数摘要）', async () => {
    mocked.getTools.mockResolvedValue({ tools: SAMPLE_TOOLS });
    mocked.getToolsStats.mockResolvedValue(SAMPLE_STATS);

    render(<ToolsPage />);

    expect(await screen.findByText('计算器')).toBeInTheDocument();
    expect(screen.getByText('网页搜索')).toBeInTheDocument();
    expect(screen.getByText('自定义工具')).toBeInTheDocument();
    expect(screen.getByText('总工具数')).toBeInTheDocument();
    expect(screen.getByText('活跃工具')).toBeInTheDocument();
    expect(screen.getByText('MCP 工具')).toBeInTheDocument();
    expect(screen.getByText('总调用次数')).toBeInTheDocument();
    // 参数 schema 摘要（expression: string）
    expect(screen.getAllByText(/expression: string/).length).toBeGreaterThanOrEqual(1);
    // 调用次数
    expect(screen.getByText('调用 42 次')).toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('类型筛选：切到 MCP 仅显示 MCP 工具', async () => {
    mocked.getTools.mockResolvedValue({ tools: SAMPLE_TOOLS });
    mocked.getToolsStats.mockResolvedValue(SAMPLE_STATS);

    render(<ToolsPage />);
    expect(await screen.findByText('计算器')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'MCP' }));
    expect(screen.queryByText('计算器')).not.toBeInTheDocument();
    expect(screen.getByText('网页搜索')).toBeInTheDocument();
  });

  it('启停切换调用 updateTool 反转状态', async () => {
    mocked.getTools.mockResolvedValue({ tools: SAMPLE_TOOLS });
    mocked.getToolsStats.mockResolvedValue(SAMPLE_STATS);
    mocked.updateTool.mockResolvedValue(SAMPLE_TOOLS.calculator);

    render(<ToolsPage />);
    expect(await screen.findByText('计算器')).toBeInTheDocument();

    const toggleButtons = screen.getAllByRole('button', { name: '启停切换' });
    fireEvent.click(toggleButtons[0]);
    await waitFor(() => {
      expect(mocked.updateTool).toHaveBeenCalledWith('calculator', { status: 'inactive' });
    });
  });

  it('测试弹窗：JSON 参数解析后调用 testTool 并展示结果', async () => {
    mocked.getTools.mockResolvedValue({ tools: SAMPLE_TOOLS });
    mocked.getToolsStats.mockResolvedValue(SAMPLE_STATS);
    mocked.testTool.mockResolvedValue({ result: { value: 3 } });

    render(<ToolsPage />);
    expect(await screen.findByText('计算器')).toBeInTheDocument();

    const testButtons = screen.getAllByRole('button', { name: '测试' });
    fireEvent.click(testButtons[0]);
    // 弹窗出现
    expect(await screen.findByText(/测试工具/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('调用参数（JSON）'), {
      target: { value: '{"expression":"1+2"}' },
    });
    fireEvent.click(screen.getByRole('button', { name: '执行' }));

    await waitFor(() => {
      expect(mocked.testTool).toHaveBeenCalledWith('calculator', { expression: '1+2' });
    });
    // 结果展示
    expect(await screen.findByText(/"value": 3/)).toBeInTheDocument();
  });

  it('非法 JSON 参数提示且不发起调用', async () => {
    mocked.getTools.mockResolvedValue({ tools: SAMPLE_TOOLS });
    mocked.getToolsStats.mockResolvedValue(SAMPLE_STATS);

    render(<ToolsPage />);
    expect(await screen.findByText('计算器')).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: '测试' })[0]);
    fireEvent.change(screen.getByLabelText('调用参数（JSON）'), {
      target: { value: '{bad json' },
    });
    fireEvent.click(screen.getByRole('button', { name: '执行' }));

    expect(await screen.findByText('参数不是合法 JSON')).toBeInTheDocument();
    expect(mocked.testTool).not.toHaveBeenCalled();
  });

  it('仅自定义工具显示删除按钮，确认后调用 deleteTool', async () => {
    mocked.getTools.mockResolvedValue({ tools: SAMPLE_TOOLS });
    mocked.getToolsStats.mockResolvedValue(SAMPLE_STATS);
    mocked.deleteTool.mockResolvedValue(undefined);
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<ToolsPage />);
    expect(await screen.findByText('自定义工具')).toBeInTheDocument();

    const deleteButtons = screen.getAllByRole('button', { name: '删除' });
    expect(deleteButtons).toHaveLength(1);
    fireEvent.click(deleteButtons[0]);
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(mocked.deleteTool).toHaveBeenCalledWith('my_custom');
    });
    confirmSpy.mockRestore();
  });

  it('加载失败显示错误态，点击重试重新拉取', async () => {
    mocked.getTools.mockRejectedValueOnce(new Error('network down'));
    mocked.getToolsStats.mockResolvedValue(SAMPLE_STATS);

    render(<ToolsPage />);
    expect(
      await screen.findByText('加载失败，请检查后端连接后重试'),
    ).toBeInTheDocument();

    mocked.getTools.mockResolvedValue({ tools: SAMPLE_TOOLS });
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('计算器')).toBeInTheDocument();
  });
});
