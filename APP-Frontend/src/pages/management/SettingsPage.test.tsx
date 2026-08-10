import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
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
      frameMode: 'interval',
      frameIntervalSec: 5,
    });
  });

  afterEach(() => {
    cleanup(); // vitest globals:false，RTL 自动清理不生效，需显式卸载
    vi.unstubAllGlobals();
  });

  it('渲染五区块标题且不含占位文案', async () => {
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

  it('视觉采集开关仅写 captureStore 会话态并展示 petNote 提示', () => {
    render(<SettingsPage />);
    expect(
      screen.getByText(/实际采集由桌宠窗执行/),
    ).toBeInTheDocument();

    const turnOnButtons = screen.getAllByRole('button', { name: '开启' });
    expect(turnOnButtons).toHaveLength(2);
    fireEvent.click(turnOnButtons[0]); // 屏幕共享
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
});
