import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import AudioPanelPage from './AudioPanelPage';
import i18n from '../../i18n';
import { useAudioStore } from '@/store/audioStore';
import { audioApi } from '@/api/clients/audio';
import type { TTSSyncData } from '@/hooks/useLiveWebSocket';

/**
 * AudioPanelPage 冒烟 + 关键交互测试（SubTask 7.4）：
 * useLiveWebSocket 整体打桩（可控连接态/回调捕获）；
 * jsdom 无 navigator.mediaDevices，麦克风开启走优雅降级分支。
 */
const liveWs = vi.hoisted(() => ({
  isConnected: true,
  sendAudio: vi.fn(),
  onTTSSync: undefined as ((data: TTSSyncData) => void) | undefined,
  onTTSEnd: undefined as (() => void) | undefined,
}));

vi.mock('@/hooks/useLiveWebSocket', () => ({
  useLiveWebSocket: (options: {
    onTTSSync?: (data: TTSSyncData) => void;
    onTTSEnd?: () => void;
  }) => {
    liveWs.onTTSSync = options.onTTSSync;
    liveWs.onTTSEnd = options.onTTSEnd;
    return {
      isConnected: liveWs.isConnected,
      sendAudio: liveWs.sendAudio,
      sendMessage: vi.fn(),
      disconnect: vi.fn(),
      reconnect: vi.fn(),
    };
  },
}));

vi.mock('@/api/clients/audio', () => ({
  audioApi: {
    getAudioConfig: vi.fn(),
  },
}));
const mockedAudioApi = vi.mocked(audioApi);

describe('AudioPanelPage 音频面板页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
    mockedAudioApi.getAudioConfig.mockResolvedValue({});
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockedAudioApi.getAudioConfig.mockResolvedValue({});
    liveWs.isConnected = true;
    liveWs.onTTSSync = undefined;
    liveWs.onTTSEnd = undefined;
    useAudioStore.setState({ micGain: 1, ttsVolume: 1, micEnabled: false });
  });

  it('渲染页头、状态行与三个功能区块', () => {
    render(<AudioPanelPage />);

    expect(screen.getByText('音频面板')).toBeInTheDocument();
    expect(screen.getByText(/麦克风输入 · TTS 播放/)).toBeInTheDocument();
    // Live WS 状态行
    expect(screen.getByText(/已连接/)).toBeInTheDocument();
    expect(screen.getByText(/同步：已同步/)).toBeInTheDocument();
    // 三区块
    expect(screen.getByText('麦克风输入')).toBeInTheDocument();
    expect(screen.getByText('音频输出')).toBeInTheDocument();
    expect(screen.getByText('回声消除 (AEC)')).toBeInTheDocument();
    // AEC 初始未激活
    expect(screen.getByText(/未激活/)).toBeInTheDocument();
    // 非占位页
    expect(screen.queryByText(/页面建设中/)).not.toBeInTheDocument();
  });

  it('WS 未连接时展示断开与等待同步', () => {
    liveWs.isConnected = false;
    render(<AudioPanelPage />);

    expect(screen.getByText(/未连接/)).toBeInTheDocument();
    expect(screen.getByText(/同步：等待连接/)).toBeInTheDocument();
  });

  it('TTS 同步事件驱动播放指示出现与消失', () => {
    render(<AudioPanelPage />);

    act(() => {
      liveWs.onTTSSync?.({
        playback_id: 'pb-1',
        server_ts: 1000,
        text: '你好，这是一段测试播报',
        duration: 2.5,
      });
    });
    expect(screen.getByText('正在播放 TTS：')).toBeInTheDocument();
    expect(screen.getByText('你好，这是一段测试播报')).toBeInTheDocument();
    expect(screen.getByText(/同步：播放中/)).toBeInTheDocument();

    act(() => {
      liveWs.onTTSEnd?.();
    });
    expect(screen.queryByText('正在播放 TTS：')).not.toBeInTheDocument();
    expect(screen.getByText(/同步：就绪/)).toBeInTheDocument();
  });

  it('jsdom 无 mediaDevices 时开启麦克风显示优雅降级横幅', () => {
    render(<AudioPanelPage />);

    fireEvent.click(screen.getByText('开启麦克风'));
    expect(
      screen.getByText('当前环境不支持麦克风采集（无 mediaDevices）'),
    ).toBeInTheDocument();
  });

  it('挂载时消费 audioApi.getAudioConfig 并展示标量配置项', async () => {
    mockedAudioApi.getAudioConfig.mockResolvedValue({ engine: 'qwen3', sampleRate: 16000 });
    render(<AudioPanelPage />);

    expect(await screen.findByText('音频配置')).toBeInTheDocument();
    expect(screen.getByText('engine')).toBeInTheDocument();
    expect(screen.getByText('qwen3')).toBeInTheDocument();
    expect(screen.getByText('sampleRate')).toBeInTheDocument();
    expect(mockedAudioApi.getAudioConfig).toHaveBeenCalledTimes(1);
  });
});