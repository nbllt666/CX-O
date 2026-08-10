/**
 * 管理界面布局（Task 6.1 · 路由注册契约的布局载体）
 *
 * 增强版（复刻 CX-O-Frontend Sidebar 四项交互特性）：
 * - A. 小工具分组折叠：vector/archive/audio-workstation/audio-test 收编为「小工具」分组，
 *      可折叠/展开；路由落在子项时自动展开；整体折叠时子项平铺为图标。
 * - B. 侧边栏整体折叠：260px ↔ 72px 宽度动画，底部折叠按钮。
 * - C. 对话 Agent 子菜单：复用 chatStore 的 agents/currentAgentId/isChatExpanded，
 *      展开显示 Agent 列表，点击切换并跳转 /chat。
 * - D. 二次元粒子装饰：ParticleField 樱花花瓣 + 星形粒子常驻布局顶层。
 *
 * 分组配置定义在本组件内，不改动 routes.tsx 的 20 条冻结契约。
 */
import { Suspense, useEffect, useState, Fragment } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import {
  ChevronDown,
  Languages,
  LayoutGrid,
  MessageSquareText,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PawPrint,
  Sun,
} from 'lucide-react';
import {
  MANAGEMENT_ROUTES,
  findRouteByPathname,
} from '@/pages/management/routes';
import type { ManagementRouteEntry } from '@/pages/management/routes';
import { useThemeStore } from '@/store/themeStore';
import { useChatStore } from '@/store/chatStore';
import { getApiBaseUrl } from '@/api/base';
import { changeLanguage, getCurrentLanguage } from '@/i18n';
import { cn } from '@/lib/utils';
import { ParticleField } from '@/components/anime/ParticleField';

type BackendStatus = 'checking' | 'connected' | 'disconnected';

/**
 * 小工具分组收编的路由 path 集合（分组逻辑全部位于本组件，不触碰 routes.tsx 契约）。
 * 对应 CX-O-Frontend Sidebar 的 widgetItems。
 */
const WIDGET_GROUP_PATHS: ReadonlySet<string> = new Set([
  'vector',
  'archive',
  'audio-workstation',
  'audio-test',
]);

/** 顶栏后端连接状态：30s 轮询 /health（轻量探活，与连接检测门同端点） */
function useBackendStatus(): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>('checking');

  useEffect(() => {
    let cancelled = false;

    const probe = async () => {
      try {
        const response = await fetch(`${getApiBaseUrl()}/health`, {
          method: 'GET',
          signal: AbortSignal.timeout(3000),
        });
        if (!cancelled) setStatus(response.ok ? 'connected' : 'disconnected');
      } catch {
        if (!cancelled) setStatus('disconnected');
      }
    };

    void probe();
    const timer = setInterval(() => void probe(), 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return status;
}

export default function ManagementLayout() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useThemeStore();
  const backendStatus = useBackendStatus();
  const [language, setLanguage] = useState(() => getCurrentLanguage());

  // ── 侧边栏本地状态（整体折叠/小工具分组展开）──
  const [collapsed, setCollapsed] = useState(false);
  const [isWidgetsExpanded, setIsWidgetsExpanded] = useState(false);

  // ── 对话 Agent 子菜单（复用 chatStore 既有接口）──
  const { agents, currentAgentId, isChatExpanded, setIsChatExpanded, setCurrentAgentId, fetchAgents } =
    useChatStore();

  // 分组配置：从冻结登记表派生，不改契约
  const flatItems = MANAGEMENT_ROUTES.filter((e) => !WIDGET_GROUP_PATHS.has(e.path));
  const widgetItems = MANAGEMENT_ROUTES.filter((e) => WIDGET_GROUP_PATHS.has(e.path));

  // 挂载即加载 Agent 列表（对齐 CX-O 的 handleAgentClick 数据源）
  useEffect(() => {
    void fetchAgents();
  }, [fetchAgents]);

  // 路由落在 /chat 时自动展开对话子菜单
  useEffect(() => {
    if (location.pathname === '/chat') setIsChatExpanded(true);
  }, [location.pathname, setIsChatExpanded]);

  // 路由落在小工具子项时自动展开该分组
  useEffect(() => {
    if (widgetItems.some((w) => `/${w.path}` === location.pathname)) {
      setIsWidgetsExpanded(true);
    }
  }, [location.pathname, widgetItems]);

  const handleAgentClick = (agentId: string) => {
    setCurrentAgentId(agentId);
    navigate('/chat');
  };

  const currentEntry = findRouteByPathname(location.pathname);
  const currentTitle = currentEntry ? t(currentEntry.titleKey) : t('management.title');

  const toggleLanguage = () => {
    const next = language.startsWith('zh') ? 'en-US' : 'zh-CN';
    void changeLanguage(next);
    setLanguage(next);
  };

  const statusDotClass =
    backendStatus === 'connected'
      ? 'bg-emerald-400'
      : backendStatus === 'checking'
        ? 'bg-amber-400'
        : 'bg-red-400';

  /** 扁平导航项（可折叠态仅显示图标，title 作 tooltip） */
  const renderFlatLink = (entry: ManagementRouteEntry) => {
    const Icon = entry.icon;
    const to = entry.path === '' ? '/' : `/${entry.path}`;
    const isActive = location.pathname === to;
    return (
      <NavLink
        to={to}
        end={entry.path === ''}
        title={collapsed ? t(entry.titleKey) : undefined}
        className={cn(
          'flex items-center gap-3 rounded-lg py-2.5 text-sm transition-all duration-fast',
          collapsed ? 'justify-center px-0' : 'px-3',
          isActive
            ? 'bg-primary/15 font-medium text-primary shadow-[inset_0_1px_0_var(--glass-border)]'
            : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
        )}
      >
        <Icon className={cn('shrink-0', collapsed ? 'h-5 w-5' : 'h-4 w-4')} />
        {!collapsed && <span className="whitespace-nowrap">{t(entry.titleKey)}</span>}
      </NavLink>
    );
  };

  /** 对话 Agent 子菜单项（折叠态退化为平铺图标，展开态为可折叠菜单） */
  const renderChatItem = () => {
    const isActive = location.pathname === '/chat';

    if (collapsed) {
      return (
        <NavLink
          key="chat"
          to="/chat"
          title={t('management.nav.chat')}
          className={cn(
            'flex items-center justify-center rounded-lg py-2.5 text-sm transition-all duration-fast',
            isActive
              ? 'bg-primary/15 font-medium text-primary shadow-[inset_0_1px_0_var(--glass-border)]'
              : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
          )}
        >
          <MessageSquareText className="h-5 w-5 shrink-0" />
        </NavLink>
      );
    }

    return (
      <div key="chat">
        <button
          type="button"
          onClick={() => setIsChatExpanded(!isChatExpanded)}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-fast',
            isActive
              ? 'bg-primary/15 font-medium text-primary shadow-[inset_0_1px_0_var(--glass-border)]'
              : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
          )}
        >
          <MessageSquareText className="h-4 w-4 shrink-0" />
          <span className="whitespace-nowrap">{t('management.nav.chat')}</span>
          <ChevronDown
            className={cn(
              'ml-auto h-4 w-4 transition-transform duration-fast',
              isChatExpanded && 'rotate-180',
            )}
          />
        </button>

        <AnimatePresence initial={false}>
          {isChatExpanded && agents.length > 0 && (
            <motion.ul
              key="chat-submenu"
              className="ml-4 mt-1 space-y-1 overflow-hidden border-l border-[var(--glass-border)] pl-3"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            >
              {agents.map((agent) => (
                <li key={agent.id}>
                  <button
                    type="button"
                    onClick={() => handleAgentClick(agent.id)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md py-2 pl-2 pr-3 text-left text-sm transition-colors duration-fast',
                      currentAgentId === agent.id
                        ? 'text-primary'
                        : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
                    )}
                  >
                    <span
                      className={cn(
                        'h-1.5 w-1.5 shrink-0 rounded-full',
                        currentAgentId === agent.id ? 'bg-primary' : 'bg-border',
                      )}
                    />
                    <span className="truncate">{agent.name}</span>
                  </button>
                </li>
              ))}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>
    );
  };

  /** 小工具分组（展开态）：分组按钮 + 可折叠子项 */
  const renderWidgetGroup = () => {
    const isWidgetChildActive = widgetItems.some((w) => `/${w.path}` === location.pathname);
    return (
      <div key="widget-group">
        <button
          type="button"
          onClick={() => setIsWidgetsExpanded(!isWidgetsExpanded)}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-fast',
            isWidgetChildActive
              ? 'bg-primary/15 font-medium text-primary shadow-[inset_0_1px_0_var(--glass-border)]'
              : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
          )}
        >
          <LayoutGrid className="h-4 w-4 shrink-0" />
          <span className="whitespace-nowrap">{t('management.sidebar.widgets')}</span>
          <ChevronDown
            className={cn(
              'ml-auto h-4 w-4 transition-transform duration-fast',
              isWidgetsExpanded && 'rotate-180',
            )}
          />
        </button>

        <AnimatePresence initial={false}>
          {isWidgetsExpanded && (
            <motion.ul
              key="widget-submenu"
              className="ml-4 mt-1 space-y-1 overflow-hidden border-l border-[var(--glass-border)] pl-3"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            >
              {widgetItems.map((w) => (
                <li key={w.path}>{renderFlatLink(w)}</li>
              ))}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>
    );
  };

  /** 小工具分组（折叠态）：不占位，直接平铺渲染 4 个子项图标 */
  const renderWidgetsCollapsed = () => (
    <Fragment key="widget-group-collapsed">
      {widgetItems.map((w) => (
        <Fragment key={w.path}>{renderFlatLink(w)}</Fragment>
      ))}
    </Fragment>
  );

  return (
    <div className="app-surface relative flex h-screen overflow-hidden">
      {/* 二次元粒子装饰层：常驻布局顶层，pointer-events-none，低于内容高于背景 */}
      <div
        data-testid="particle-decor"
        className="pointer-events-none absolute inset-0 z-0 overflow-hidden"
        aria-hidden="true"
      >
        <ParticleField particleType="petal" density={0.5} maxAlpha={0.28} />
        <ParticleField particleType="star" density={0.2} maxAlpha={0.12} />
      </div>

      {/* 左侧边栏 */}
      <motion.aside
        className="relative z-10 flex h-full shrink-0 flex-col overflow-hidden border-r border-[var(--glass-border)] bg-[var(--glass-bg)] backdrop-blur-xl"
        animate={{ width: collapsed ? 72 : 260 }}
        transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
      >
        <div className={cn('flex items-center gap-2 py-5', collapsed ? 'justify-center px-0' : 'px-5')}>
          <PawPrint className="h-6 w-6 shrink-0 text-primary" />
          {!collapsed && (
            <span className="text-gradient text-lg font-bold whitespace-nowrap">{t('management.title')}</span>
          )}
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
          {flatItems.map((entry) =>
            entry.path === 'chat' ? renderChatItem() : <Fragment key={entry.path || '__index__'}>{renderFlatLink(entry)}</Fragment>,
          )}
          {collapsed ? renderWidgetsCollapsed() : renderWidgetGroup()}
        </nav>

        <div className="border-t border-[var(--glass-border)] px-3 py-3">
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? t('management.sidebar.expand') : t('management.sidebar.collapse')}
            aria-label={collapsed ? t('management.sidebar.expand') : t('management.sidebar.collapse')}
            className={cn(
              'flex w-full items-center gap-3 rounded-lg py-2.5 text-sm text-muted-foreground transition-all duration-fast hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
              collapsed ? 'justify-center px-0' : 'px-3',
            )}
          >
            {collapsed ? (
              <PanelLeftOpen className="h-5 w-5 shrink-0" />
            ) : (
              <PanelLeftClose className="h-4 w-4 shrink-0" />
            )}
            {!collapsed && <span className="whitespace-nowrap">{t('management.sidebar.collapse')}</span>}
          </button>

          <div
            className={cn(
              'mt-3 flex items-center gap-2 text-xs text-muted-foreground',
              collapsed && 'justify-center',
            )}
          >
            <Monitor className="h-3.5 w-3.5 shrink-0" />
            {!collapsed &&
              (window.electronAPI ? t('management.mode.electron') : t('management.mode.browser'))}
          </div>
        </div>
      </motion.aside>

      {/* 右侧：顶栏 + 内容区 */}
      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[var(--glass-border)] bg-[var(--glass-bg)] px-6 backdrop-blur-xl">
          <h1 className="text-base font-semibold">{currentTitle}</h1>

          <div className="ml-auto flex items-center gap-2">
            {/* 后端连接状态 */}
            <span
              className="mr-1 flex items-center gap-1.5 text-xs text-muted-foreground"
              title={getApiBaseUrl()}
            >
              <span className={cn('h-2 w-2 rounded-full', statusDotClass)} />
              {t(`management.topbar.backend.${backendStatus}`)}
            </span>

            {/* 语言切换 */}
            <button
              type="button"
              onClick={toggleLanguage}
              aria-label={t('management.topbar.language')}
              title={t('management.topbar.language')}
              className="flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs text-muted-foreground transition-colors duration-fast hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
            >
              <Languages className="h-4 w-4" />
              {language.startsWith('zh') ? 'EN' : '中'}
            </button>

            {/* 主题切换 */}
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={t('management.topbar.theme')}
              title={t('management.topbar.theme')}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground transition-colors duration-fast hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-6">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center text-muted-foreground">
                {t('management.loading')}
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
