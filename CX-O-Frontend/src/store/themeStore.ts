import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ThemeState {
  theme: 'light' | 'dark' | 'system';
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      theme: 'system',
      setTheme: (theme) => {
        set({ theme });
        applyTheme(theme);
      },
      toggleTheme: () => {
        const current = get().theme;
        const next = current === 'light' ? 'dark' : current === 'dark' ? 'system' : 'light';
        set({ theme: next });
        applyTheme(next);
      },
    }),
    {
      name: 'cxhms-theme',
    }
  )
);

function applyTheme(theme: 'light' | 'dark' | 'system') {
  const root = window.document.documentElement;

  let effectiveTheme: 'light' | 'dark';
  if (theme === 'system') {
    effectiveTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } else {
    effectiveTheme = theme;
  }

  root.setAttribute('data-theme', effectiveTheme);

  // 同时添加/移除 dark 类以支持 Tailwind 的 dark 模式
  if (effectiveTheme === 'dark') {
    root.classList.add('dark');
  } else {
    root.classList.remove('dark');
  }
}

// Initialize theme on load
if (typeof window !== 'undefined') {
  const savedTheme = localStorage.getItem('cxhms-theme');
  if (savedTheme) {
    try {
      const parsed = JSON.parse(savedTheme);
      applyTheme(parsed.state?.theme || 'system');
    } catch {
      applyTheme('system');
    }
  }
}
