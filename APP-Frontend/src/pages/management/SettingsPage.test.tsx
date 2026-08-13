import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import SettingsPage from './SettingsPage';
import i18n from '../../i18n';
import { useSettingsStore } from '@/store/settingsStore';
import { useAudioStore } from '@/store/audioStore';
import { useCaptureStore } from '@/store/captureStore';
import { STORAGE_KEYS } from '@/api/base';

/**
 * SettingsPage 五区块渲染冒烟 + 交互单测（GN-004 观察项补强：此前无测试看守设置页内容）。
 * healthApi 打桩避免真实网络；fetch 仅在后端地址保存用例中按桩返回。
 */
vi.mock('@/api/clients/health', () => ({
  healthApi: {
    getLiveClientStatus: vi.fn().mockResolvedValue({ status: 'disconnected', connected: false }),
    disconnectLiveClient: vi.fn().mockResolvedValue(undefined),
    getHealth: vi.fn().mockResolvedValue({ status: 'ok' }),
  },
}));

vi.mock('@/api/clients/config', () => ({
  configApi: {
    getConfig: vi.fn().mockResolvedValue({ status: 'success', config: {} }),
    getGraphConfig: vi.fn().mockResolvedValue({ status: 'success', config: {} }),
    updateConfig: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('@/api/clients/graph', () => ({
  graphApi: {
    getGraphHealthV2: vi.fn().mockResolvedValue({ database: 'unknown', semantic: 'unknown', overall: 'unknown' }),
    getGraphStatsV2: vi.fn().mockResolvedValue({ node_count: 0, edge_count: 0 }),
  },
}));

vi.mock('@/api/clients/service', () => ({
  serviceApi: {
    getServiceLogs: vi.fn().mockResolvedValue({ logs: '' }),
    startService: vi.fn().mockResolvedValue({ status: 'started' }),
    stopService: vi.fn().mockResolvedValue({ status: 'stopped' }),
    restartService: vi.fn().mockResolvedValue({ status: 'restarted' }),
  },
}));

vi.mock('@/api/clients/cxfc', () => ({
  cxfcApi: {
    getCxfcPlugins: vi.fn().mockResolvedValue([]),
    getCxfcSkills: vi.fn().mockResolvedValue([]),
    discoverCxfcPlugins: vi.fn().mockResolvedValue({ remote: [] }),
    connectCxfcPlugin: vi.fn().mockResolvedValue({ status: 'success', plugin_id: 'p1' }),
    disconnectCxfcPlugin: vi.fn().mockResolvedValue({ status: 'success' }),
    refreshCxfcPlugin: vi.fn().mockResolvedValue({ status: 'success' }),
  },
}));

describe('SettingsPage 五区块', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  beforeEach(() => {
    localStorage.clear();
    useSettingsStore.getState().setAvatarType('none');
    useAudioStore.setState({
      micEnabled: false,
      ttsVolume: 1,
      micGain: 1,
      danmakuVoiceEnabled: false,
    });
    useCaptureStore.setState({
      screenActive: false,
      cameraActive: false,
      visionEnabled: false,
      frameMode: 'interval',
      frameIntervalSec: 5,
    });
  });

  afterEach(() => {
    cleanup(); // vitest globals:false，RTL 自动清理不生效，需显式卸载
    vi.unstubAllGlobals();
  });

  it('渲染五个配置区块标题且不含占位文案', async () => {
    render(<SettingsPage />);
    expect(screen.getByRole('heading', { name: '虚拟形象' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '直播' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '后端地址' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '音频' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '视觉采集' })).toBeInTheDocument();
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
    // 直播区块异步查询（已打桩）回落到未连接态
    expect(await screen.findByText('未连接')).toBeInTheDocument();
  });

  it('渲染新增五个配置区块（LLM/向量/图/服务/插件）标题', async () => {
    render(<SettingsPage />);
    expect(screen.getByRole('heading', { name: '语言模型' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '向量存储' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '图数据库' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '后端服务' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'CXFC 插件' })).toBeInTheDocument();
  });

  it('LLM 区块展示默认模型与推理参数并支持保存', async () => {
    const { configApi } = await import('@/api/clients/config');
    render(<SettingsPage />);
    // 默认模型区块存在
    expect(screen.getByText('默认模型')).toBeInTheDocument();
    expect(screen.getByText('模型参数')).toBeInTheDocument();
    // 等待后端健康探测完成、保存按钮可用后触发保存
    const saveBtn = (await screen.findAllByRole('button', { name: '保存配置' }))[0];
    await waitFor(() => expect(saveBtn).toBeEnabled());
    fireEvent.click(saveBtn);
    await waitFor(() => expect(configApi.updateConfig).toHaveBeenCalled());
  });

  it('向量区块展示后端与嵌入字段并支持保存', async () => {
    const { configApi } = await import('@/api/clients/config');
    render(<SettingsPage />);
    expect(screen.getByText('向量后端')).toBeInTheDocument();
    expect(screen.getByText('集合名称')).toBeInTheDocument();
    // 向量区块为第二个保存按钮（LLM/向量/图）
    const saveBtn = (await screen.findAllByRole('button', { name: '保存配置' }))[1];
    await waitFor(() => expect(saveBtn).toBeEnabled());
    fireEvent.click(saveBtn);
    await waitFor(() => expect(configApi.updateConfig).toHaveBeenCalled());
  });

  it('服务区块展示运行状态与管理按钮', async () => {
    render(<SettingsPage />);
    expect(screen.getByText('端口')).toBeInTheDocument();
    expect(screen.getByText('服务日志')).toBeInTheDocument();
    // 待后端健康探测完成后展示重启/停止而非启动
    expect(await screen.findByRole('button', { name: '重启' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '停止' })).toBeInTheDocument();
  });

  it('插件区块展示空态提示', async () => {
    render(<SettingsPage />);
    expect(screen.getByText('暂无已连接的插件')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '扫描局域网' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '连接插件' })).toBeInTheDocument();
  });

  it('切换头像类型即时写入 settingsStore 并显示对应参数区', () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('button', { name: 'Live2D' }));
    expect(useSettingsStore.getState().avatarType).toBe('live2d');
    expect(useSettingsStore.getState().live2d.enabled).toBe(true);
    expect(screen.getByText('Live2D 参数')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'VRM 3D' }));
    expect(useSettingsStore.getState().avatarType).toBe('vrm');
    expect(useSettingsStore.getState().vrm.enabled).toBe(true);
    expect(useSettingsStore.getState().live2d.enabled).toBe(false);
    expect(screen.getByText('VRM 参数')).toBeInTheDocument();
  });

  it('音频控件读写 audioStore', () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('switch', { name: '麦克风上行' }));
    expect(useAudioStore.getState().micEnabled).toBe(true);

    fireEvent.change(screen.getByRole('slider', { name: 'TTS 音量' }), {
      target: { value: '0.5' },
    });
    expect(useAudioStore.getState().ttsVolume).toBe(0.5);

    fireEvent.change(screen.getByRole('slider', { name: '麦克风增益' }), {
      target: { value: '1.5' },
    });
    expect(useAudioStore.getState().micGain).toBe(1.5);

    fireEvent.click(screen.getByRole('switch', { name: '弹幕语音播报' }));
    expect(useAudioStore.getState().danmakuVoiceEnabled).toBe(true);
  });

  it('视觉采集：主动视觉总开关默认关，切换后写入 captureStore', () => {
    render(<SettingsPage />);
    // 总开关默认关闭
    expect(useCaptureStore.getState().visionEnabled).toBe(false);
    expect(screen.getByText(/总开关/)).toBeInTheDocument();

    const master = screen.getAllByRole('button', { name: '开启' })[0]; // 主动视觉总开关
    fireEvent.click(master);
    expect(useCaptureStore.getState().visionEnabled).toBe(true);
  });

  it('视觉采集开关仅写 captureStore 会话态并展示 petNote 提示', () => {
    render(<SettingsPage />);
    expect(
      screen.getByText(/实际采集由桌宠窗执行/),
    ).toBeInTheDocument();

    const turnOnButtons = screen.getAllByRole('button', { name: '开启' });
    expect(turnOnButtons).toHaveLength(3); // 主动视觉总开关 + 屏幕共享 + 摄像头
    fireEvent.click(turnOnButtons[1]); // 屏幕共享
    expect(useCaptureStore.getState().screenActive).toBe(true);
    expect(useCaptureStore.getState().cameraActive).toBe(false);

    // 帧节奏：默认定时抽帧，切手动后间隔滑块隐藏
    fireEvent.click(screen.getByRole('button', { name: '手动点发' }));
    expect(useCaptureStore.getState().frameMode).toBe('manual');
    expect(screen.queryByRole('slider', { name: '抽帧间隔（秒）' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '定时抽帧' }));
    fireEvent.change(screen.getByRole('slider', { name: '抽帧间隔（秒）' }), {
      target: { value: '10' },
    });
    expect(useCaptureStore.getState().frameIntervalSec).toBe(10);
  });

  it('后端地址保存：探测通过后写入 localStorage 并提示生效', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('{"status":"ok"}', { status: 200 })),
    );
    render(<SettingsPage />);
    const input = screen.getByRole('textbox', { name: '后端地址' });
    fireEvent.change(input, { target: { value: 'http://192.168.1.100:8100' } });
    fireEvent.click(screen.getByRole('button', { name: '保存并测试连接' }));
    expect(await screen.findByText('已保存，连接正常')).toBeInTheDocument();
    expect(localStorage.getItem(STORAGE_KEYS.backendUrl)).toBe('http://192.168.1.100:8100');
  });

  it('前端启动设置：浏览器模式下显示不可用且不调用 Electron API', async () => {
    delete (window as { electronAPI?: unknown }).electronAPI;
    render(<SettingsPage />);
    expect(screen.getByRole('heading', { name: '前端启动设置' })).toBeInTheDocument();
    expect(screen.getByText(/浏览器模式不可用/)).toBeInTheDocument();

    // 浏览器模式点击开关不触发任何 Electron IPC
    const switchBtn = screen.getByRole('switch', { name: '前端自启动' });
    fireEvent.click(switchBtn);
    expect((window as { electronAPI?: unknown }).electronAPI).toBeUndefined();
  });

  it('前端启动设置：桌面模式下读取并更新自启动/管理员权限开关', async () => {
    const electronApi = {
      getStartupSettings: vi
        .fn()
        .mockResolvedValue({ supported: true, autoStart: false, runAsAdmin: false, isAdmin: true }),
      setAutoStart: vi
        .fn()
        .mockResolvedValue({ supported: true, autoStart: true, runAsAdmin: false, isAdmin: true }),
      setRunAsAdmin: vi
        .fn()
        .mockResolvedValue({ supported: true, autoStart: false, runAsAdmin: true, isAdmin: false }),
    };
    Object.defineProperty(window, 'electronAPI', { value: electronApi, configurable: true });
    render(<SettingsPage />);

    // 读取当前状态
    await waitFor(() => expect(electronApi.getStartupSettings).toHaveBeenCalled());

    // 切换自启动
    const autoSwitch = screen.getByRole('switch', { name: '前端自启动' });
    expect(autoSwitch).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(autoSwitch);
    await waitFor(() => expect(electronApi.setAutoStart).toHaveBeenCalledWith(true));

    // 切换管理员权限：返回未提权 → 提示重启生效
    const adminSwitch = screen.getByRole('switch', { name: '管理员权限启动' });
    fireEvent.click(adminSwitch);
    await waitFor(() => expect(electronApi.setRunAsAdmin).toHaveBeenCalledWith(true));
    expect(await screen.findByText(/重启应用后以管理员权限运行/)).toBeInTheDocument();

    delete (window as { electronAPI?: unknown }).electronAPI;
  });
});
