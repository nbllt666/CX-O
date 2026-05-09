import { useLocation, useNavigate } from 'react-router-dom';
import { Heart, Database } from 'lucide-react';
import { cn } from '../lib/utils';
import { LanguageSwitcher } from './LanguageSwitcher';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';

const getPageTitles = (t: TFunction): Record<string, string> => ({
  '/': t('nav.chat'),
  '/agents': t('agent.title'),
  '/memories': t('memory.title'),
  '/archive': t('archive.title'),
  '/acp': t('acp.title'),
  '/tools': t('tools.title'),
  '/settings': t('settings.title'),
  '/memory-agent': '记忆管理助手',
});

export function Header() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const pageTitles = getPageTitles(t);
  const title = pageTitles[location.pathname] || 'CXHMS';
  const isMemoryAgentPage = location.pathname === '/memory-agent';

  return (
    <header className="h-16 border-b border-border bg-card/50 backdrop-blur-sm flex items-center justify-between px-6">
      <h2 className="text-xl font-semibold">{title}</h2>

      <div className="flex items-center gap-4">
        {/* 记忆管理助手入口 */}
        <button
          onClick={() => navigate('/memory-agent')}
          className={cn(
            'p-2 rounded-lg transition-colors relative group',
            isMemoryAgentPage
              ? 'bg-primary text-primary-foreground'
              : 'hover:bg-accent text-muted-foreground hover:text-foreground'
          )}
          title="记忆管理助手"
        >
          <Database className="w-5 h-5" />
          <span className="absolute -bottom-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            记忆管理助手
          </span>
        </button>

        {/* 语言切换器 */}
        <LanguageSwitcher />

        <a
          href="https://afdian.com/a/nbllt666"
          target="_blank"
          rel="noopener noreferrer"
          className="p-2 rounded-lg hover:bg-accent transition-colors relative group"
          title="支持开发者"
        >
          <Heart className="w-5 h-5 text-red-500 group-hover:text-red-600" />
          <span className="absolute -bottom-8 left-1/2 -translate-x-1/2 px-2 py-1 bg-popover text-popover-foreground text-xs rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap">
            支持开发者
          </span>
        </a>
        <span className="text-sm text-muted-foreground">CXHMS v1.0</span>
      </div>
    </header>
  );
}
