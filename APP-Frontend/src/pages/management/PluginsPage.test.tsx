import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import PluginsPage from './PluginsPage';
import i18n from '../../i18n';
import { cxfcApi } from '@/api/clients/cxfc';
import type { CxfcDiscoveredPlugin, CxfcPlugin, CxfcSkill } from '@/api/types';

/**
 * PluginsPage 冒烟 + 关键交互测试（SubTask 7.2）：
 * cxfcApi 整体打桩，避免真实网络；覆盖统计渲染、插件/技能/发现三 Tab、
 * 局域网扫描与一键连接、断开确认、加载失败重试。
 */
vi.mock('@/api/clients/cxfc', () => ({
  cxfcApi: {
    getCxfcPlugins: vi.fn(),
    getCxfcSkills: vi.fn(),
    connectCxfcPlugin: vi.fn(),
    disconnectCxfcPlugin: vi.fn(),
    refreshCxfcPlugin: vi.fn(),
    discoverCxfcPlugins: vi.fn(),
  },
}));

const mocked = vi.mocked(cxfcApi);

const SAMPLE_PLUGINS: CxfcPlugin[] = [
  {
    plugin_id: 'weather-plugin',
    host: '192.168.1.10',
    port: 8081,
    name: '天气插件',
    version: '1.2.0',
    capabilities: ['weather', 'forecast'],
    status: 'connected',
    tools: [{ name: 'get_weather' }, { name: 'get_forecast' }],
    skills: [{ name: 'weather_skill' }],
  },
  {
    plugin_id: 'music-plugin',
    host: '192.168.1.11',
    port: 8082,
    name: '音乐插件',
    capabilities: [],
    status: 'disconnected',
    tools: [],
    skills: [],
  },
];

const SAMPLE_SKILLS: CxfcSkill[] = [
  {
    name: 'weather_skill',
    description: '查天气',
    trigger_keywords: ['天气', '下雨'],
    trigger_events: [],
    auto_inject: true,
    source_plugin_id: 'weather-plugin',
  },
];

const SAMPLE_DISCOVERED: CxfcDiscoveredPlugin[] = [
  { host: '192.168.1.20', port: 8083, name: '远端插件', capabilities: ['ocr'], version: '0.9' },
];

describe('PluginsPage 插件页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('渲染统计行与插件列表（含状态徽章与提供工具）', async () => {
    mocked.getCxfcPlugins.mockResolvedValue(SAMPLE_PLUGINS);
    mocked.getCxfcSkills.mockResolvedValue(SAMPLE_SKILLS);

    render(<PluginsPage />);

    expect(await screen.findByText('天气插件')).toBeInTheDocument();
    expect(screen.getByText('音乐插件')).toBeInTheDocument();
    expect(screen.getByText('已连接插件')).toBeInTheDocument();
    expect(screen.getByText('总插件数')).toBeInTheDocument();
    expect(screen.getByText('提供工具')).toBeInTheDocument();
    // 状态徽章
    expect(screen.getByText('已连接')).toBeInTheDocument();
    expect(screen.getByText('已断开')).toBeInTheDocument();
    // 提供工具 chips
    expect(screen.getByText('get_weather')).toBeInTheDocument();
    // 能力标签
    expect(screen.getByText('weather')).toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('Skills Tab 展示技能（触发关键词 + 自动注入徽章）', async () => {
    mocked.getCxfcPlugins.mockResolvedValue(SAMPLE_PLUGINS);
    mocked.getCxfcSkills.mockResolvedValue(SAMPLE_SKILLS);

    render(<PluginsPage />);
    expect(await screen.findByText('天气插件')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
    expect(await screen.findByText('weather_skill')).toBeInTheDocument();
    expect(screen.getByText('自动注入')).toBeInTheDocument();
    expect(screen.getByText('天气')).toBeInTheDocument();
  });

  it('扫描局域网后展示发现列表，点击连接调用 connectCxfcPlugin', async () => {
    mocked.getCxfcPlugins.mockResolvedValue([]);
    mocked.getCxfcSkills.mockResolvedValue([]);
    mocked.discoverCxfcPlugins.mockResolvedValue({ remote: SAMPLE_DISCOVERED });
    mocked.connectCxfcPlugin.mockResolvedValue({ status: 'ok', plugin_id: 'remote-1' });

    render(<PluginsPage />);
    // 空列表态
    expect(await screen.findByText('暂无插件，可扫描局域网或手动连接')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /扫描局域网/ }));
    expect(await screen.findByText('远端插件')).toBeInTheDocument();
    expect(mocked.discoverCxfcPlugins).toHaveBeenCalledWith(true);

    fireEvent.click(screen.getByRole('button', { name: /^连接$/ }));
    await waitFor(() => {
      expect(mocked.connectCxfcPlugin).toHaveBeenCalledWith('192.168.1.20', 8083);
    });
  });

  it('断开插件需确认，确认后调用 disconnectCxfcPlugin', async () => {
    mocked.getCxfcPlugins.mockResolvedValue(SAMPLE_PLUGINS);
    mocked.getCxfcSkills.mockResolvedValue([]);
    mocked.disconnectCxfcPlugin.mockResolvedValue({ status: 'ok' });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<PluginsPage />);
    expect(await screen.findByText('天气插件')).toBeInTheDocument();

    const disconnectButtons = screen.getAllByRole('button', { name: '断开' });
    fireEvent.click(disconnectButtons[0]);
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(mocked.disconnectCxfcPlugin).toHaveBeenCalledWith('weather-plugin');
    });
    confirmSpy.mockRestore();
  });

  it('加载失败显示错误态，点击重试重新拉取', async () => {
    mocked.getCxfcPlugins.mockRejectedValueOnce(new Error('network down'));
    mocked.getCxfcSkills.mockResolvedValue([]);

    render(<PluginsPage />);
    expect(
      await screen.findByText('加载失败，请检查后端连接后重试'),
    ).toBeInTheDocument();

    mocked.getCxfcPlugins.mockResolvedValue(SAMPLE_PLUGINS);
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('天气插件')).toBeInTheDocument();
  });
});
