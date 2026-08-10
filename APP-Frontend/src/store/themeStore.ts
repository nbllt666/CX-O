import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';

export type Theme = 'light' | 'dark';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

/**
 * 主题状态（明暗双套）。
 * persist key 'cxo-pet-theme' 与 index.html 的防闪烁 bootstrap 脚本联动。
 * 存储经 createStorage()：Electron 下落 userData 文件（三窗共享同一文件），
 * 浏览器模式回退 localStorage。
 */
export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'dark',
      setTheme: (theme) => set({ theme }),
      toggleTheme: () => set({ theme: get().theme === 'dark' ? 'light' : 'dark' }),
    }),
    { name: 'cxo-pet-theme', storage: createStorage() },
  ),
);
