import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';
import AvatarSourcePage from './AvatarSourcePage';
import i18n from '../../i18n';

/**
 * AvatarSourcePage 冒烟测试（SubTask 8.2，OBS 头像源）：
 * 复用 Task 3 头像系统，PetAvatar 打桩，校验自包含渲染与 OBS 提示。
 */
vi.mock('@/components/pet/PetAvatar', () => ({
  PetAvatar: () => <div data-testid="pet-avatar" />,
}));

describe('AvatarSourcePage 头像源页', () => {
  beforeAll(async () => {
    await i18n.changeLanguage('zh-CN');
  });

  afterEach(() => {
    cleanup();
  });

  it('自包含渲染头像实例与 OBS 提示', () => {
    render(<AvatarSourcePage />);
    expect(screen.getByTestId('pet-avatar')).toBeInTheDocument();
    expect(screen.getByText(/头像源 · OBS 浏览器源/)).toBeInTheDocument();
    expect(screen.getByText(/1920×1080/)).toBeInTheDocument();
  });
});
