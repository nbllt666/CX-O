import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import AudioSourcePage from './AudioSourcePage';
import i18n from '../../i18n';

/**
 * AudioSourcePage 冒烟测试（SubTask 8.2，OBS 音频源）：
 * 复用 AudioPanelPage 渲染链路；此处打桩 AudioPanelPage 校验自包含组装。
 */
vi.mock('./AudioPanelPage', () => ({
  default: () => <div data-testid="audio-panel" />,
}));

describe('AudioSourcePage 音频源页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
  });

  it('自包含组装 AudioPanel 渲染实例', () => {
    render(<AudioSourcePage />);
    expect(screen.getByTestId('audio-panel')).toBeInTheDocument();
  });
});
