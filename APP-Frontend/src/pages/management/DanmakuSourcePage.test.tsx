import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import DanmakuSourcePage from './DanmakuSourcePage';
import i18n from '../../i18n';
import type { LiveDanmakuData } from '@/hooks/useLiveWebSocket';

/**
 * DanmakuSourcePage 冒烟 + 事件驱动测试（SubTask 8.2，OBS 弹幕源）：
 * useLiveWebSocket 打桩捕获 onDanmaku，校验弹幕流链路复用。
 */
const liveWs = vi.hoisted(() => ({
  onDanmaku: undefined as ((d: LiveDanmakuData) => void) | undefined,
}));

vi.mock('@/hooks/useLiveWebSocket', () => ({
  useLiveWebSocket: (options: { onDanmaku?: (d: LiveDanmakuData) => void }) => {
    liveWs.onDanmaku = options.onDanmaku;
    return {
      isConnected: true,
      connectionCount: 1,
      sendMessage: vi.fn(),
      sendAudio: vi.fn(),
      disconnect: vi.fn(),
      reconnect: vi.fn(),
    };
  },
}));

describe('DanmakuSourcePage 弹幕源页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    liveWs.onDanmaku = undefined;
  });

  it('渲染 OBS 提示，弹幕事件驱动列表', () => {
    render(<DanmakuSourcePage />);
    expect(screen.getByText(/弹幕源 · OBS 浏览器源/)).toBeInTheDocument();

    act(() => {
      liveWs.onDanmaku?.({ id: 'd1', content: '来自弹幕源的弹幕' });
    });
    expect(screen.getByText('来自弹幕源的弹幕')).toBeInTheDocument();
  });
});
