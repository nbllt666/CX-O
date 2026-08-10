import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import LiveConsolePage from './LiveConsolePage';
import i18n from '../../i18n';
import { healthApi } from '@/api/clients/health';
import type { LiveDanmakuData } from '@/hooks/useLiveWebSocket';

/**
 * LiveConsolePage 冒烟 + 关键交互测试（SubTask 8.1）：
 * useLiveWebSocket 整体打桩（捕获 onDanmaku 回调、可控连接态）；
 * healthApi 打桩（getHealth / getLiveClientStatus / disconnectLiveClient）。
 */
const liveWs = vi.hoisted(() => ({
  isConnected: true,
  connectionCount: 3,
  disconnect: vi.fn(),
  reconnect: vi.fn(),
  onDanmaku: undefined as ((d: LiveDanmakuData) => void) | undefined,
}));

vi.mock('@/hooks/useLiveWebSocket', () => ({
  useLiveWebSocket: (options: { onDanmaku?: (d: LiveDanmakuData) => void }) => {
    liveWs.onDanmaku = options.onDanmaku;
    return {
      isConnected: liveWs.isConnected,
      connectionCount: liveWs.connectionCount,
      sendMessage: vi.fn(),
      sendAudio: vi.fn(),
      disconnect: liveWs.disconnect,
      reconnect: liveWs.reconnect,
    };
  },
}));

vi.mock('@/api/clients/health', () => ({
  healthApi: {
    getHealth: vi.fn(),
    getLiveClientStatus: vi.fn(),
    disconnectLiveClient: vi.fn(),
  },
}));
const mockedHealth = vi.mocked(healthApi);

describe('LiveConsolePage 直播控制台页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  beforeEach(() => {
    mockedHealth.getHealth.mockResolvedValue({ status: 'ok', database: { status: 'ok' } });
    mockedHealth.getLiveClientStatus.mockResolvedValue({ status: 'connected' });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    liveWs.isConnected = true;
    liveWs.connectionCount = 3;
    liveWs.onDanmaku = undefined;
    liveWs.disconnect.mockClear();
    liveWs.reconnect.mockClear();
  });

  it('渲染页头、状态总览与推流信息', async () => {
    render(<LiveConsolePage />);

    expect(await screen.findByText('直播控制台')).toBeInTheDocument();
    expect(screen.getByText('直播状态总览')).toBeInTheDocument();
    expect(screen.getByText('推流信息')).toBeInTheDocument();
    expect(screen.getByText('弹幕统计')).toBeInTheDocument();
    expect(screen.getByText('控制操作')).toBeInTheDocument();
    // Live WS 连接态与直播客户端均显示「已连接」
    expect(screen.getAllByText('已连接').length).toBeGreaterThan(0);
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('正常')).toBeInTheDocument();
  });

  it('连接态按钮：已连接时点击断开、未连接时点击连接', () => {
    render(<LiveConsolePage />);

    const btn = screen.getByText('断开');
    fireEvent.click(btn);
    expect(liveWs.disconnect).toHaveBeenCalledTimes(1);

    liveWs.isConnected = false;
    render(<LiveConsolePage />);
    fireEvent.click(screen.getByText('连接'));
    expect(liveWs.reconnect).toHaveBeenCalledTimes(1);
  });

  it('弹幕累计、开关切换与清屏交互', () => {
    render(<LiveConsolePage />);

    // 默认弹幕开：append 计入累计
    act(() => {
      liveWs.onDanmaku?.({ id: 'd1', content: '第一条弹幕' });
    });
    expect(screen.getByText('1')).toBeInTheDocument();

    // 弹幕开关：开 → 关
    fireEvent.click(screen.getByText('弹幕开'));
    expect(screen.getByText('弹幕关')).toBeInTheDocument();

    // 清屏：累计归零
    fireEvent.click(screen.getByText('清屏'));
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('后端查询失败时优雅降级展示「查询失败」', async () => {
    mockedHealth.getHealth.mockRejectedValue(new Error('down'));
    mockedHealth.getLiveClientStatus.mockRejectedValue(new Error('down'));
    render(<LiveConsolePage />);

    expect(await screen.findAllByText('查询失败')).not.toHaveLength(0);
  });
});
