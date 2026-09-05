import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import CxfcPage from './CxfcPage';
import i18n from '../../i18n';
import { cxfcApi } from '@/api/clients/cxfc';
import type { CxfcPlugin, CxfcSkill } from '@/api/types';

/**
 * CxfcPage 冒烟 + 关键交互测试（enhance-cxfc-admin-and-integrate-dream Task 2）：
 * cxfcApi 整体打桩，避免真实网络；覆盖四区块渲染（插件总览含 transport 徽章与心跳状态、
 * 工具/技能按 plugin_id 分组、relay 目标列表）、网关测试器成功与错误态、加载失败重试。
 */
vi.mock('@/api/clients/cxfc', () => ({
  cxfcApi: {
    getCxfcPlugins: vi.fn(),
    getCxfcSkills: vi.fn(),
    connectCxfcPlugin: vi.fn(),
    disconnectCxfcPlugin: vi.fn(),
    refreshCxfcPlugin: vi.fn(),
    discoverCxfcPlugins: vi.fn(),
    relayRegister: vi.fn(),
    relayTargets: vi.fn(),
    relayResult: vi.fn(),
    embeddedRegister: vi.fn(),
    memorySearch: vi.fn(),
    memoryWrite: vi.fn(),
    memoryStats: vi.fn(),
    memoryGet: vi.fn(),
    physioReport: vi.fn(),
    physioStatus: vi.fn(),
    physioSleep: vi.fn(),
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
    capabilities: ['weather'],
    status: 'connected',
    transport: 'relay',
    last_seen: '2026-09-04T10:00:00Z',
    tools: [{ name: 'get_weather' }],
    skills: [],
  },
  {
    plugin_id: 'music-plugin',
    name: '音乐插件',
    capabilities: [],
    status: 'disconnected',
    transport: 'embedded',
    last_seen: null,
    tools: [],
    skills: [],
  },
];

const SAMPLE_SKILLS: CxfcSkill[] = [
  {
    name: 'weather_skill',
    description: '查天气',
    trigger_keywords: ['天气'],
    trigger_events: [],
    auto_inject: false,
    source_plugin_id: 'weather-plugin',
  },
  {
    name: 'orphan_skill',
    trigger_keywords: [],
    trigger_events: [],
    auto_inject: false,
    source_plugin_id: 'ghost-plugin',
  },
  {
    name: 'anonymous_skill',
    trigger_keywords: [],
    trigger_events: [],
    auto_inject: false,
    source_plugin_id: '',
  },
];

const SAMPLE_RELAY_TARGETS = [
  { plugin_id: 'weather-plugin', name: '天气转接', transport: 'relay', active: true },
  { plugin_id: 'legacy-plugin', name: '旧版转接', transport: 'relay', active: false },
];

describe('CxfcPage CXFC 管理页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  function mockHappyPath() {
    mocked.getCxfcPlugins.mockResolvedValue(SAMPLE_PLUGINS);
    mocked.getCxfcSkills.mockResolvedValue(SAMPLE_SKILLS);
    mocked.relayTargets.mockResolvedValue({ targets: SAMPLE_RELAY_TARGETS });
  }

  it('渲染插件总览：transport 徽章与心跳状态（正常/离线 + 最近心跳）', async () => {
    mockHappyPath();

    render(<CxfcPage />);

    expect(await screen.findByText('天气插件')).toBeInTheDocument();
    expect(screen.getByText('音乐插件')).toBeInTheDocument();
    expect(screen.getByText('插件总览')).toBeInTheDocument();
    // transport 徽章（relay/embedded）
    expect(screen.getByText('前端转接')).toBeInTheDocument();
    expect(screen.getByText('嵌入式')).toBeInTheDocument();
    // 心跳状态徽章：connected -> 正常，disconnected -> 离线
    expect(screen.getByText(/心跳:正常/)).toBeInTheDocument();
    expect(screen.getByText(/心跳:离线/)).toBeInTheDocument();
    // last_seen 为 null 时回退「无记录」
    expect(screen.getByText(/无记录/)).toBeInTheDocument();
  });

  it('工具与技能清单按 plugin_id 分组（含未归组技能兜底组）', async () => {
    mockHappyPath();

    render(<CxfcPage />);

    expect(await screen.findByText('工具与技能清单')).toBeInTheDocument();
    // 已注册插件组：weather-plugin（工具 get_weather + 技能 weather_skill）
    expect(screen.getByText('weather-plugin')).toBeInTheDocument();
    expect(screen.getByText('get_weather')).toBeInTheDocument();
    expect(screen.getByText('weather_skill')).toBeInTheDocument();
    // 未注册插件的技能按 source_plugin_id 原样分组（ghost-plugin）
    expect(screen.getByText('ghost-plugin')).toBeInTheDocument();
    expect(screen.getByText('orphan_skill')).toBeInTheDocument();
    // source_plugin_id 为空的技能归入「未分组技能」兜底组
    expect(screen.getByText('未分组技能')).toBeInTheDocument();
    expect(screen.getByText('anonymous_skill')).toBeInTheDocument();
  });

  it('relay 目标列表展示活跃/待命徽章；拉取失败时区块内可见错误提示', async () => {
    mockHappyPath();

    render(<CxfcPage />);
    expect(await screen.findByText('天气转接')).toBeInTheDocument();
    expect(screen.getByText('旧版转接')).toBeInTheDocument();
    expect(screen.getByText('活跃')).toBeInTheDocument();
    expect(screen.getByText('待命')).toBeInTheDocument();

    // relay 拉取失败：主视图不受阻断，区块内显示红色错误提示
    cleanup();
    mocked.getCxfcPlugins.mockResolvedValue([]);
    mocked.getCxfcSkills.mockResolvedValue([]);
    mocked.relayTargets.mockRejectedValueOnce(new Error('relay down'));

    render(<CxfcPage />);
    expect(await screen.findByText('relay 目标拉取失败')).toBeInTheDocument();
  });

  it('网关测试器：执行 memoryStats 调用并展示响应 JSON', async () => {
    mockHappyPath();
    mocked.memoryStats.mockResolvedValue({ total_memories: 42 });

    render(<CxfcPage />);
    expect(await screen.findByText('记忆/生理网关测试器')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '执行调用' }));

    expect(await screen.findByText(/total_memories/)).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();
    expect(mocked.memoryStats).toHaveBeenCalledTimes(1);
  });

  it('网关测试器错误态红色可见（非静默）：调用抛错显示「调用失败」+ 消息', async () => {
    mockHappyPath();
    mocked.memoryStats.mockRejectedValueOnce(new Error('401 未授权'));

    render(<CxfcPage />);
    expect(await screen.findByText('记忆/生理网关测试器')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '执行调用' }));

    expect(await screen.findByText(/调用失败: 401 未授权/)).toBeInTheDocument();
  });

  it('网关测试器：参数非合法 JSON 时提示错误且不发起调用', async () => {
    mockHappyPath();

    render(<CxfcPage />);
    expect(await screen.findByText('记忆/生理网关测试器')).toBeInTheDocument();

    const paramsBox = screen.getByLabelText('请求参数（JSON）');
    fireEvent.change(paramsBox, { target: { value: '{invalid' } });
    fireEvent.click(screen.getByRole('button', { name: '执行调用' }));

    expect(await screen.findByText(/参数不是合法 JSON/)).toBeInTheDocument();
    expect(mocked.memoryStats).not.toHaveBeenCalled();
  });

  it('主数据加载失败显示错误态，点击重试重新拉取', async () => {
    mocked.getCxfcPlugins.mockRejectedValueOnce(new Error('network down'));
    mocked.getCxfcSkills.mockResolvedValue([]);
    mocked.relayTargets.mockResolvedValue({ targets: [] });

    render(<CxfcPage />);
    expect(await screen.findByText('加载失败，请检查后端连接后重试')).toBeInTheDocument();

    mockHappyPath();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('天气插件')).toBeInTheDocument();
  });
});
