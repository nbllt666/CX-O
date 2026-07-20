import React from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '../../lib/utils';
import { useThemeStore } from '../../store/themeStore';

// Check if running in Electron
const isElectron = !!(window as unknown as { electronAPI?: unknown }).electronAPI;

interface HeaderProps {
  title?: string;
  actions?: React.ReactNode;
}

// Logo 组件
const Logo: React.FC = () => (
  <div className="flex items-center">
    <div className="flex flex-col">
      <span className="text-base font-bold text-[var(--color-text-primary)] leading-tight">
        CX-O
      </span>
      <span className="text-[10px] text-[var(--color-text-tertiary)] leading-tight">
        晨曦长记忆Agent系统
      </span>
    </div>
  </div>
);

export const Header: React.FC<HeaderProps> = ({ title, actions }) => {
  const { theme, toggleTheme } = useThemeStore();
  const navigate = useNavigate();

  return (
    <div className="h-full px-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        {!title && <Logo />}
        {title && (
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">{title}</h1>
        )}
      </div>

      {/* 页面级内容插槽 - 由具体页面通过 Portal 注入标题和按钮 */}
      <div id="header-page-slot" className="flex items-center justify-between flex-1 px-4 min-w-0 gap-4" />

      <div className="flex items-center gap-2">
        {actions}

        {/* 记忆管理Agent入口 */}
        <button
          onClick={() => navigate('/memory-agent')}
          className={cn(
            'p-2 rounded-[var(--radius-md)]',
            'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]',
            'transition-colors duration-[var(--transition-fast)]'
          )}
          title="记忆管理Agent"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
            />
          </svg>
        </button>

        {/* 爱发电支持按钮 */}
        <a
          href="https://afdian.com/a/nbllt666"
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            'p-2 rounded-[var(--radius-md)]',
            'text-red-500 hover:bg-red-50 dark:hover:bg-red-950',
            'transition-colors duration-[var(--transition-fast)]'
          )}
          title="支持开发者"
        >
          <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
          </svg>
        </a>

        {/* 桌宠模式按钮 - 仅在 Electron 环境显示 */}
        {isElectron && (
          <button
            onClick={() => {
              const electronAPI = (window as unknown as { electronAPI?: { openPetWindow: () => void } }).electronAPI;
              if (electronAPI?.openPetWindow) {
                electronAPI.openPetWindow();
              }
            }}
            className={cn(
              'p-2 rounded-[var(--radius-md)]',
              'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]',
              'transition-colors duration-[var(--transition-fast)]'
            )}
            title="桌宠模式"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
            </svg>
          </button>
        )}

        <button
          onClick={toggleTheme}
          className={cn(
            'p-2 rounded-[var(--radius-md)]',
            'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]',
            'transition-colors duration-[var(--transition-fast)]'
          )}
          title={theme === 'dark' ? '切换到浅色模式' : '切换到深色模式'}
        >
          {theme === 'dark' ? (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
              />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
              />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
};
