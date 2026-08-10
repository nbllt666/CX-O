import { describe, it, expect, beforeAll, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, act } from '@testing-library/react';
import SubtitleSourcePage from './SubtitleSourcePage';
import i18n from '../../i18n';

/**
 * SubtitleSourcePage 冒烟 + 事件驱动测试（SubTask 8.2，OBS 字幕源）：
 * useLiveWebSocket 打桩捕获 onStreamContent，校验字幕流链路复用与占位态。
 */
const liveWs = vi.hoisted(() => ({
  onStreamContent: undefined as ((c: string) => void) | undefined,
}));

vi.mock('@/hooks/useLiveWebSocket', () => ({
  useLiveWebSocket: (options: { onStreamContent?: (c: string) => void }) => {
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

describe('SubtitleSourcePage 字幕源页', () => {
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
    liveWs.onStreamContent = undefined;
  });

  it('无字幕时渲染占位提示与 OBS 提示', () => {
    render(<SubtitleSourcePage />);
    expect(screen.getByText(/等待 AI 回复字幕/)).toBeInTheDocument();
    expect(screen.getByText(/字幕源 · OBS 浏览器源/)).toBeInTheDocument();
  });

  it('AI 回复流驱动字幕显示', () => {
    render(<SubtitleSourcePage />);

    act(() => {
      liveWs.onStreamContent?.('这是一段 AI 回复字幕');
    });
    // 打字机完成：完整字幕可见；占位提示消失
    expect(screen.queryByText(/等待 AI 回复字幕/)).not.toBeInTheDocument();
    expect(screen.getByText('这是一段 AI 回复字幕')).toBeInTheDocument();
  });
});
