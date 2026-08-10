import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import LiveOverlayPage from './LiveOverlayPage';
import i18n from '../../i18n';
import type { LiveDanmakuData } from '@/hooks/useLiveWebSocket';

/**
 * LiveOverlayPage 冒烟 + 关键交互测试（SubTask 8.2，管理窗预览形态）：
 * useLiveWebSocket 打桩（捕获 onDanmaku / onStreamContent）；
 * PetAvatar 打桩（避免加载 Live2D 运行时）。
 */
const liveWs = vi.hoisted(() => ({
  onDanmaku: undefined as ((d: LiveDanmakuData) => void) | undefined,
  onStreamContent: undefined as ((c: string) => void) | undefined,
}));

vi.mock('@/hooks/useLiveWebSocket', () => ({
  useLiveWebSocket: (options: {
    onDanmaku?: (d: LiveDanmakuData) => void;
    onStreamContent?: (c: string) => void;
  }) => {
    liveWs.onDanmaku = options.onDanmaku;
    liveWs.onStreamContent = options.onStreamContent;
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

vi.mock('@/components/pet/PetAvatar', () => ({
  PetAvatar: () => <div data-testid="pet-avatar" />,
}));

describe('LiveOverlayPage 直播分屏页（管理窗预览）', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  beforeEach(() => {
    // 让 SubtitleDisplay 打字机逐字在一次回调内完成（jsdom 无可靠 rAF）
    let fakeNow = performance.now();
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      fakeNow += 100_000;
      cb(fakeNow);
      return 0;
    });
    vi.stubGlobal('cancelAnimationFrame', () => {});
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    liveWs.onDanmaku = undefined;
    liveWs.onStreamContent = undefined;
  });

  it('渲染头像区/弹幕区/音频区/字幕分屏布局与控制条', () => {
    render(<LiveOverlayPage />);

    // 管理窗预览形态：显示顶部控制条与分区标注
    expect(screen.getByText('直播分屏')).toBeInTheDocument();
    expect(screen.getByText('预览背景')).toBeInTheDocument();
    expect(screen.getByText('头像区')).toBeInTheDocument();
    expect(screen.getByText('弹幕区')).toBeInTheDocument();
    expect(screen.getByText('音频状态')).toBeInTheDocument();
    expect(screen.getByTestId('pet-avatar')).toBeInTheDocument();
  });

  it('背景切换按钮在「预览/透明」间切换', () => {
    render(<LiveOverlayPage />);

    const toggle = screen.getByText('预览背景');
    act(() => toggle.click());
    expect(screen.getByText('透明背景')).toBeInTheDocument();
  });

  it('弹幕与字幕事件驱动渲染', () => {
    render(<LiveOverlayPage />);

    act(() => {
      liveWs.onDanmaku?.({ id: 'd1', content: '分屏弹幕' });
    });
    expect(screen.getByText('分屏弹幕')).toBeInTheDocument();

    act(() => {
      liveWs.onStreamContent?.('分屏字幕内容');
    });
    // 字幕打字机完成
    expect(screen.getByText('分屏字幕内容')).toBeInTheDocument();
  });
});
