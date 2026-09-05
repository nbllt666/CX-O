import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import DreamPage from './DreamPage';
import i18n from '../../i18n';
import { dreamApi } from '@/api/clients/dream';
import { physioApi } from '@/api/clients/physio';
import type {
  DreamConfig,
  DreamStatusActive,
  PhysioConfig,
  PhysioStatus,
  PhysioStatusActive,
} from '@/api/types';

/**
 * DreamPage 生理信号区块测试（spec Task 6）：
 * - dreamApi / physioApi 整体打桩，避免真实网络；
 * - window.ble 按测试可控注入/移除，覆盖：未启用、不可用（非 Electron）、
 *   未配对徽章、扫描→连接（持久化指纹）、配置保存、一键清除基线、后端离线全页错误态。
 */
vi.mock('@/api/clients/dream', () => ({
  dreamApi: {
    getStatus: vi.fn(),
    getList: vi.fn(),
    trigger: vi.fn(),
    confirm: vi.fn(),
    reject: vi.fn(),
    purgeSession: vi.fn(),
    purge: vi.fn(),
    getConfig: vi.fn(),
    updateConfig: vi.fn(),
  },
}));

vi.mock('@/api/clients/physio', () => ({
  physioApi: {
    getStatus: vi.fn(),
    getSleep: vi.fn(),
    getDevices: vi.fn(),
    forgetDevice: vi.fn(),
    getConfig: vi.fn(),
    updateConfig: vi.fn(),
    clear: vi.fn(),
  },
}));

const mockedDream = vi.mocked(dreamApi);
const mockedPhysio = vi.mocked(physioApi);

const DREAM_STATUS_IDLE: DreamStatusActive = {
  status: 'idle',
  enabled: true,
  last_session_at: null,
  stats: { sessions: 0, generated: 0, approved: 0, rejected: 0, purges: 0 },
};

const DREAM_CONFIG: DreamConfig = {
  enabled: true,
  model: 'test-model',
  dream_temperature: 0.9,
  candidates_per_session: 3,
  material_window_days: 7,
  max_material_items: 5,
  min_lucidity: 0.6,
  dream_ttl_hours: 24,
  purge_threshold: 0.5,
  confirmed_importance: 0.7,
  surface_on_wake: true,
  surface_probability: 0.3,
  max_surface_per_day: 5,
  schedule: {
    wake_time: '08:00',
    sleep_time: '02:00',
    golden_start: '19:00',
    golden_end: '23:00',
    diary_time: '02:00',
    quiet_windows: [],
  },
  trigger: {
    emotion_enabled: false,
    emotion_threshold: 0.7,
    emotion_window_hours: 24,
    emotion_min_events: 1,
    probability: 1.0,
  },
};

const PHYSIO_STATUS_ACTIVE: PhysioStatusActive = {
  status: 'active',
  enabled: true,
  collector: { backend: 'noble', device_fingerprint: 'fp-real-1', device_name_hint: 'Mi' },
  estimator: { base_hr: 70, hr_sleep_confidence: 0.8, window_size: 10 },
};

const PHYSIO_STATUS_DISABLED: PhysioStatus = { status: 'disabled' };

const PHYSIO_CONFIG_ENABLED: PhysioConfig = {
  enabled: true,
  backend: 'noble',
  device_name_hint: 'Mi',
  device_fingerprint: 'fp-real-1',
  scan_timeout_sec: 15,
  reconnect_interval_sec: 30,
  base_drop_ratio: 0.88,
  base_drop_confirm_min: 5,
  hr_stability_threshold: 6,
  base_hr_learning: true,
  store_raw_hr: false,
};

const PHYSIO_CONFIG_DISABLED: PhysioConfig = { ...PHYSIO_CONFIG_ENABLED, enabled: false };

/** window.ble 打桩（Task 5 暴露的 contextBridge API 面） */
function createBleMock() {
  return {
    scan: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn(),
    getStatus: vi.fn(),
    onNotify: vi.fn(() => () => {}),
    onStatus: vi.fn(() => () => {}),
  };
}

function installBleMock() {
  const ble = createBleMock();
  Object.defineProperty(window, 'ble', { value: ble, configurable: true, writable: true });
  return ble;
}

function removeBleMock() {
  // jsdom 下 window.ble 默认不存在 → 模拟非 Electron 浏览器模式
  delete (window as { ble?: unknown }).ble;
}

function mockDreamActive() {
  mockedDream.getStatus.mockResolvedValue(DREAM_STATUS_IDLE);
  mockedDream.getConfig.mockResolvedValue(DREAM_CONFIG);
  mockedDream.getList.mockResolvedValue({ items: [], total: 0 });
}

function mockPhysioActive() {
  mockedPhysio.getStatus.mockResolvedValue(PHYSIO_STATUS_ACTIVE);
  mockedPhysio.getConfig.mockResolvedValue(PHYSIO_CONFIG_ENABLED);
  mockedPhysio.getDevices.mockResolvedValue({ devices: [] });
}

function mockPhysioDisabled() {
  mockedPhysio.getStatus.mockResolvedValue(PHYSIO_STATUS_DISABLED);
  mockedPhysio.getConfig.mockResolvedValue(PHYSIO_CONFIG_DISABLED);
  mockedPhysio.getDevices.mockResolvedValue({ devices: [] });
}

describe('DreamPage 生理信号区块', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    removeBleMock();
  });

  it('physio 未启用时显示「生理信号未启用」引导与未启用徽章', async () => {
    mockDreamActive();
    mockPhysioDisabled();

    render(<DreamPage />);

    expect(await screen.findByText('生理信号未启用')).toBeInTheDocument();
    // 生理信号区块徽章 = 未启用
    expect(screen.getByText('生理信号')).toBeInTheDocument();
  });

  it('window.ble 缺失（非 Electron）时显示「不可用」提示，配置编辑仍可用', async () => {
    mockDreamActive();
    mockPhysioActive();
    removeBleMock();

    render(<DreamPage />);

    expect(
      await screen.findByText(/当前环境不支持手环采集/),
    ).toBeInTheDocument();
    // 配置编辑仍可用
    expect(screen.getByRole('button', { name: '保存配置' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '一键清除基线' })).toBeInTheDocument();
  });

  it('physio 启用 + 手环未连接时徽章为「未配对」', async () => {
    mockDreamActive();
    mockPhysioActive();
    const ble = installBleMock();
    ble.getStatus.mockResolvedValue({ status: 'idle', fingerprint: null, deviceName: null });

    render(<DreamPage />);

    expect(await screen.findByText('设备配对')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '扫描设备' })).toBeInTheDocument();
    // 未配对徽章
    expect(screen.getAllByText('未配对').length).toBeGreaterThan(0);
  });

  it('扫描 → 选择连接 → 持久化设备指纹并刷新', async () => {
    mockDreamActive();
    mockPhysioActive();
    const ble = installBleMock();
    ble.getStatus.mockResolvedValue({ status: 'idle', fingerprint: null, deviceName: null });
    ble.scan.mockResolvedValue({
      ok: true,
      status: 'idle',
      devices: [
        {
          deviceId: 'dev-1',
          name: 'Mi Band 8',
          address: 'AA:BB:CC:DD',
          fingerprint: 'fp-real-1',
          rssi: -55,
          serviceUuids: ['180d'],
          hasHeartRate: true,
        },
      ],
    });
    ble.connect.mockResolvedValue({ ok: true, status: 'connected' });
    mockedPhysio.updateConfig.mockResolvedValue(PHYSIO_CONFIG_ENABLED);

    render(<DreamPage />);
    expect(await screen.findByRole('button', { name: '扫描设备' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '扫描设备' }));
    expect(await screen.findByText('Mi Band 8')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '连接' }));
    await waitFor(() => {
      expect(ble.connect).toHaveBeenCalledWith('dev-1');
      // 连接后持久化配对：device_fingerprint 写入配置
      expect(mockedPhysio.updateConfig).toHaveBeenCalledWith(
        expect.objectContaining({ device_fingerprint: 'fp-real-1' }),
      );
    });
  });

  it('保存 physio 配置调 updateConfig 后刷新状态', async () => {
    mockDreamActive();
    mockPhysioActive();
    installBleMock();
    mockedPhysio.updateConfig.mockResolvedValue({
      ...PHYSIO_CONFIG_ENABLED,
      base_drop_ratio: 0.85,
    });

    render(<DreamPage />);
    expect(await screen.findByRole('button', { name: '保存配置' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '保存配置' }));
    await waitFor(() => {
      expect(mockedPhysio.updateConfig).toHaveBeenCalled();
    });
    expect(await screen.findByText('配置已保存')).toBeInTheDocument();
  });

  it('一键清除基线需确认后调用 clear', async () => {
    mockDreamActive();
    mockPhysioActive();
    installBleMock();
    mockedPhysio.clear.mockResolvedValue({ ok: true, cleared: true });
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(<DreamPage />);
    expect(await screen.findByRole('button', { name: '一键清除基线' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '一键清除基线' }));
    await waitFor(() => {
      expect(confirmSpy).toHaveBeenCalled();
      expect(mockedPhysio.clear).toHaveBeenCalled();
    });
    confirmSpy.mockRestore();
  });

  it('后端离线（physio getStatus 返回 null）→ 全页错误态 + 重试', async () => {
    mockDreamActive();
    mockedPhysio.getStatus.mockResolvedValue(null);
    mockedPhysio.getConfig.mockResolvedValue(null);
    mockedPhysio.getDevices.mockResolvedValue(null);

    render(<DreamPage />);

    expect(
      await screen.findByText('加载失败，请检查后端连接后重试'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument();
  });
});

/** 按测试 id 取 trigger 数字/开关输入框 */
function getTriggerInput(testId: string): HTMLInputElement {
  return screen.getByTestId(testId) as HTMLInputElement;
}

describe('DreamPage 情绪触发（trigger）配置', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    removeBleMock();
  });

  it('配置加载后渲染 trigger 字段（mock 返回值回显）', async () => {
    mockDreamActive();
    mockPhysioDisabled();

    render(<DreamPage />);

    expect(await screen.findByTestId('dream-config-trigger-emotion-enabled')).toBeInTheDocument();
    expect(getTriggerInput('dream-config-trigger-emotion-enabled').checked).toBe(false);
    expect(getTriggerInput('dream-config-trigger-emotion-threshold').value).toBe('0.7');
    expect(getTriggerInput('dream-config-trigger-emotion-window-hours').value).toBe('24');
    expect(getTriggerInput('dream-config-trigger-emotion-min-events').value).toBe('1');
    expect(getTriggerInput('dream-config-trigger-probability').value).toBe('1');
    // 分组标题渲染
    expect(screen.getByText('情绪触发条件')).toBeInTheDocument();
  });

  it('修改 trigger 字段后保存 → updateConfig 载荷包含更新后的 trigger 子节', async () => {
    mockDreamActive();
    mockPhysioDisabled();
    mockedDream.updateConfig.mockResolvedValue(DREAM_CONFIG);

    render(<DreamPage />);
    expect(await screen.findByTestId('dream-config-trigger-emotion-enabled')).toBeInTheDocument();

    fireEvent.click(getTriggerInput('dream-config-trigger-emotion-enabled'));
    fireEvent.change(getTriggerInput('dream-config-trigger-emotion-threshold'), {
      target: { value: '0.85' },
    });
    fireEvent.change(getTriggerInput('dream-config-trigger-probability'), {
      target: { value: '0.5' },
    });

    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(mockedDream.updateConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          trigger: expect.objectContaining({
            emotion_enabled: true,
            emotion_threshold: 0.85,
            emotion_window_hours: 24,
            emotion_min_events: 1,
            probability: 0.5,
          }),
        }),
      );
    });
  });

  it('旧响应无 trigger 子节时字段显示契约默认值且保存不崩溃', async () => {
    mockedDream.getStatus.mockResolvedValue(DREAM_STATUS_IDLE);
    mockedDream.getConfig.mockResolvedValue({
      ...DREAM_CONFIG,
      trigger: undefined,
    } as unknown as DreamConfig);
    mockedDream.getList.mockResolvedValue({ items: [], total: 0 });
    mockedDream.updateConfig.mockResolvedValue(DREAM_CONFIG);
    mockPhysioDisabled();

    render(<DreamPage />);

    expect(await screen.findByTestId('dream-config-trigger-emotion-enabled')).toBeInTheDocument();
    expect(getTriggerInput('dream-config-trigger-emotion-enabled').checked).toBe(false);
    expect(getTriggerInput('dream-config-trigger-emotion-threshold').value).toBe('0.7');
    expect(getTriggerInput('dream-config-trigger-emotion-window-hours').value).toBe('24');
    expect(getTriggerInput('dream-config-trigger-emotion-min-events').value).toBe('1');
    expect(getTriggerInput('dream-config-trigger-probability').value).toBe('1');

    // 保存不崩溃，载荷携带回退后的默认 trigger 子节
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => {
      expect(mockedDream.updateConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          trigger: expect.objectContaining({
            emotion_enabled: false,
            emotion_threshold: 0.7,
            probability: 1,
          }),
        }),
      );
    });
  });
});
