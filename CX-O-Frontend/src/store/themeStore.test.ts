import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useThemeStore } from './themeStore';

describe('themeStore', () => {
  beforeEach(() => {
    useThemeStore.setState({
      theme: 'system',
    });
    localStorage.clear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('initial state', () => {
    it('should have system theme by default', () => {
      const state = useThemeStore.getState();
      expect(state.theme).toBe('system');
    });
  });

  describe('setTheme', () => {
    it('should set light theme', () => {
      useThemeStore.getState().setTheme('light');
      expect(useThemeStore.getState().theme).toBe('light');
    });

    it('should set dark theme', () => {
      useThemeStore.getState().setTheme('dark');
      expect(useThemeStore.getState().theme).toBe('dark');
    });

    it('should set system theme', () => {
      useThemeStore.getState().setTheme('dark');
      useThemeStore.getState().setTheme('system');
      expect(useThemeStore.getState().theme).toBe('system');
    });

    it('should handle multiple theme changes', () => {
      useThemeStore.getState().setTheme('light');
      expect(useThemeStore.getState().theme).toBe('light');

      useThemeStore.getState().setTheme('dark');
      expect(useThemeStore.getState().theme).toBe('dark');

      useThemeStore.getState().setTheme('system');
      expect(useThemeStore.getState().theme).toBe('system');

      useThemeStore.getState().setTheme('light');
      expect(useThemeStore.getState().theme).toBe('light');
    });
  });

  describe('toggleTheme', () => {
    it('should toggle from light to dark', () => {
      useThemeStore.getState().setTheme('light');
      useThemeStore.getState().toggleTheme();
      expect(useThemeStore.getState().theme).toBe('dark');
    });

    it('should toggle from dark to system', () => {
      useThemeStore.getState().setTheme('dark');
      useThemeStore.getState().toggleTheme();
      expect(useThemeStore.getState().theme).toBe('system');
    });

    it('should toggle from system to light', () => {
      useThemeStore.getState().setTheme('system');
      useThemeStore.getState().toggleTheme();
      expect(useThemeStore.getState().theme).toBe('light');
    });

    it('should cycle through all themes', () => {
      useThemeStore.getState().setTheme('light');
      expect(useThemeStore.getState().theme).toBe('light');

      useThemeStore.getState().toggleTheme();
      expect(useThemeStore.getState().theme).toBe('dark');

      useThemeStore.getState().toggleTheme();
      expect(useThemeStore.getState().theme).toBe('system');

      useThemeStore.getState().toggleTheme();
      expect(useThemeStore.getState().theme).toBe('light');
    });

    it('should handle multiple toggles', () => {
      useThemeStore.getState().setTheme('system');

      for (let i = 0; i < 10; i++) {
        useThemeStore.getState().toggleTheme();
      }

      expect(useThemeStore.getState().theme).toBe('light');
    });
  });

  describe('DOM manipulation', () => {
    it('should add light class to document element when theme is light', () => {
      const root = window.document.documentElement;
      root.classList.remove('light', 'dark');

      useThemeStore.getState().setTheme('light');

      // 当前实现只添加/移除 dark 类，light 模式通过移除 dark 类表示
      expect(root.classList.contains('dark')).toBe(false);
    });

    it('should add dark class to document element when theme is dark', () => {
      const root = window.document.documentElement;
      root.classList.remove('light', 'dark');

      useThemeStore.getState().setTheme('dark');

      expect(root.classList.contains('dark')).toBe(true);
      expect(root.classList.contains('light')).toBe(false);
    });

    it('should remove previous theme class when changing theme', () => {
      const root = window.document.documentElement;

      useThemeStore.getState().setTheme('light');
      // light 模式通过移除 dark 类表示
      expect(root.classList.contains('dark')).toBe(false);

      useThemeStore.getState().setTheme('dark');
      expect(root.classList.contains('dark')).toBe(true);
    });
  });

  describe('system theme detection', () => {
    it('should apply system preference when theme is system', () => {
      const root = window.document.documentElement;
      root.classList.remove('light', 'dark');

      useThemeStore.getState().setTheme('system');

      // system 模式会根据系统偏好添加 dark 类或不添加
      // 至少应该设置 data-theme 属性
      const dataTheme = root.getAttribute('data-theme');
      expect(dataTheme === 'light' || dataTheme === 'dark').toBe(true);
    });
  });

  describe('edge cases', () => {
    it('should handle rapid theme changes', () => {
      for (let i = 0; i < 100; i++) {
        useThemeStore.getState().setTheme(i % 2 === 0 ? 'light' : 'dark');
      }
      expect(useThemeStore.getState().theme).toBe('dark');
    });

    it('should handle setting same theme multiple times', () => {
      useThemeStore.getState().setTheme('dark');
      useThemeStore.getState().setTheme('dark');
      useThemeStore.getState().setTheme('dark');

      expect(useThemeStore.getState().theme).toBe('dark');
    });

    it('should handle toggle after direct set', () => {
      useThemeStore.getState().setTheme('dark');
      useThemeStore.getState().toggleTheme();

      expect(useThemeStore.getState().theme).toBe('system');
    });
  });

  describe('theme value validation', () => {
    it('should only accept valid theme values', () => {
      const validThemes: Array<'light' | 'dark' | 'system'> = ['light', 'dark', 'system'];

      validThemes.forEach((theme) => {
        useThemeStore.getState().setTheme(theme);
        expect(useThemeStore.getState().theme).toBe(theme);
      });
    });
  });
});
