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
import { Suspense, useCallback, useEffect, useRef, useState, Fragment } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import {
  Cable,
  ChevronDown,
  FlaskConical,
  Languages,
  LayoutGrid,
  MessageSquareText,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Radio,
  Sun,
} from 'lucide-react';
import {
  MANAGEMENT_ROUTES,
  findRouteByPathname,
} from '@/pages/management/routes';
import type { ManagementRouteEntry } from '@/pages/management/routes';
import { useThemeStore } from '@/store/themeStore';
import { useChatStore } from '@/store/chatStore';
import { useSettingsStore } from '@/store/settingsStore';
import { getApiBaseUrl } from '@/api/base';
import { changeLanguage, getCurrentLanguage } from '@/i18n';
import { cn } from '@/lib/utils';
import { ParticleField } from '@/components/anime/ParticleField';
import { useConfigReload } from '@/hooks/useConfigReload';
import { subscribeConfigChanged } from '@/lib/configEvents';
import ConfigToast, { type ConfigToastData } from './ConfigToast';
import appIcon from '/icon.png';

type BackendStatus = 'checking' | 'connected' | 'disconnected';

/**
 * 小工具分组收编的路由 path 集合（分组逻辑全部位于本组件，不触碰 routes.tsx 契约）。
 * 对应 CX-O-Frontend Sidebar 的 widgetItems。
 */
const WIDGET_GROUP_PATHS: ReadonlySet<string> = new Set([
  'memory-agent',
  'vector',
  'archive',
  'audio-workstation',
  'audio-test',
]);

/**
 * OBS 直播源子项收编集合（避免占满侧边栏扁平菜单）。
 */
const LIVE_SOURCE_GROUP_PATHS: ReadonlySet<string> = new Set([
  'live-overlay',
  'avatar-source',
  'danmaku-source',
  'subtitle-source',
  'audio-source',
]);

/**
 * 实验功能分组收编的路由 path 集合（分组逻辑全部位于本组件，不触碰 routes.tsx 契约）。
 * 收纳：微调（tuner）/ 哨兵集群（cluster）/ Neko插件（neko）/ 会议室（meeting）。
 * 注：autonomy/dream 已按 spec enhance-cxfc-admin-and-integrate-dream Task 7 升为一级导航，
 *     从本集合移除后由 flatItems 过滤逻辑自动归入主列表，无需其他改动。
 */
const EXPERIMENT_GROUP_PATHS: ReadonlySet<string> = new Set([
  'tuner',
  'cluster',
  'neko',
  'meeting',
]);

/**
 * 插件与集成分组（enhance-cxfc-admin-and-integrate-dream Task 2，仅新增 /cxfc 相关，不动既有分组）。
 * 收纳：CXFC 管理台（cxfc）；后续第三方 relay/embedded 集成页可继续归入本组。
 */
const INTEGRATION_GROUP_PATHS: ReadonlySet<string> = new Set(['cxfc']);

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

  // ── 配置热更新：订阅 /ws config_changed，刷新 limits 并展示通知 toast ──
  useConfigReload();
  const [configToast, setConfigToast] = useState<ConfigToastData | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const unsubscribe = subscribeConfigChanged(({ section, requiresRestart }) => {
      // 前端限制配置随后端 limits 变更即时刷新
      void useSettingsStore.getState().fetchLimits();
      setConfigToast({ section, requiresRestart });
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(() => setConfigToast(null), 4000);
    });
    return () => {
      unsubscribe();
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  // ── 侧边栏本地状态（整体折叠/小工具分组展开/直播源分组展开/集成分组展开）──
  const [collapsed, setCollapsed] = useState(false);
  const [isWidgetsExpanded, setIsWidgetsExpanded] = useState(false);
  const [isLiveSourcesExpanded, setIsLiveSourcesExpanded] = useState(false);
  const [isExperimentsExpanded, setIsExperimentsExpanded] = useState(false);
  const [isIntegrationExpanded, setIsIntegrationExpanded] = useState(false);

  // ── 对话 Agent 子菜单（复用 chatStore 既有接口）──
  const { agents, currentAgentId, isChatExpanded, setIsChatExpanded, setCurrentAgentId, fetchAgents } =
    useChatStore();

  // 分组配置：从冻结登记表派生，不改契约
  const flatItems = MANAGEMENT_ROUTES.filter(
    (e) =>
      !WIDGET_GROUP_PATHS.has(e.path) &&
      !LIVE_SOURCE_GROUP_PATHS.has(e.path) &&
      !EXPERIMENT_GROUP_PATHS.has(e.path) &&
      !INTEGRATION_GROUP_PATHS.has(e.path),
  );
  const widgetItems = MANAGEMENT_ROUTES.filter((e) => WIDGET_GROUP_PATHS.has(e.path));
  const liveSourceItems = MANAGEMENT_ROUTES.filter((e) => LIVE_SOURCE_GROUP_PATHS.has(e.path));
  const experimentItems = MANAGEMENT_ROUTES.filter((e) => EXPERIMENT_GROUP_PATHS.has(e.path));
  const integrationItems = MANAGEMENT_ROUTES.filter((e) => INTEGRATION_GROUP_PATHS.has(e.path));

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

  // 路由落在直播源子项时自动展开直播源分组
  useEffect(() => {
    if (liveSourceItems.some((s) => `/${s.path}` === location.pathname)) {
      setIsLiveSourcesExpanded(true);
    }
  }, [location.pathname, liveSourceItems]);

  // 路由落在实验功能子项时自动展开该分组
  useEffect(() => {
    if (experimentItems.some((e) => `/${e.path}` === location.pathname)) {
      setIsExperimentsExpanded(true);
    }
  }, [location.pathname, experimentItems]);

  // 路由落在插件与集成分组子项时自动展开该分组
  useEffect(() => {
    if (integrationItems.some((e) => `/${e.path}` === location.pathname)) {
      setIsIntegrationExpanded(true);
    }
  }, [location.pathname, integrationItems]);

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

  /** 在系统默认浏览器打开 OBS 源（/source/<path>），Electron 走 IPC，浏览器回退 window.open */
  const openSourceInBrowser = useCallback((path: string) => {
    const url = `${window.location.origin}${window.location.pathname}#/source/${path}`;
    if (window.electronAPI?.openExternal) {
      void window.electronAPI.openExternal(url);
    } else {
      window.open(url, '_blank', 'noopener,noreferrer');
    }
  }, []);

  /** 直播 OBS 源子项：点击跳系统浏览器打开对应 /source/* 页面（不应用内预览导航） */
  const renderLiveSourceLink = (entry: ManagementRouteEntry) => {
    const Icon = entry.icon;
    return (
      <button
        type="button"
        onClick={() => openSourceInBrowser(entry.path)}
        title={collapsed ? `${t(entry.titleKey)} · ${t('management.sidebar.openInBrowser')}` : undefined}
        className={cn(
          'flex w-full items-center gap-3 rounded-lg py-2.5 text-sm transition-all duration-fast',
          collapsed ? 'justify-center px-0' : 'px-3',
          'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-primary',
        )}
      >
        <Icon className={cn('shrink-0', collapsed ? 'h-5 w-5' : 'h-4 w-4')} />
        {!collapsed && <span className="whitespace-nowrap">{t(entry.titleKey)}</span>}
      </button>
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

  /** 直播源分组（展开态）：折叠分组按钮 + 可折叠 5 个 OBS 源子项 */
  const renderLiveSourcesGroup = () => {
    const isSourceActive = liveSourceItems.some((s) => `/${s.path}` === location.pathname);
    return (
      <div key="live-sources-group">
        <button
          type="button"
          onClick={() => setIsLiveSourcesExpanded(!isLiveSourcesExpanded)}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-fast',
            isSourceActive
              ? 'bg-primary/15 font-medium text-primary shadow-[inset_0_1px_0_var(--glass-border)]'
              : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
          )}
        >
          <Radio className="h-4 w-4 shrink-0" />
          <span className="whitespace-nowrap">{t('management.sidebar.liveSources')}</span>
          <ChevronDown
            className={cn(
              'ml-auto h-4 w-4 transition-transform duration-fast',
              isLiveSourcesExpanded && 'rotate-180',
            )}
          />
        </button>

        <AnimatePresence initial={false}>
          {isLiveSourcesExpanded && (
            <motion.ul
              key="live-sources-submenu"
              className="ml-4 mt-1 space-y-1 overflow-hidden border-l border-[var(--glass-border)] pl-3"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            >
              {liveSourceItems.map((s) => (
                <li key={s.path}>{renderLiveSourceLink(s)}</li>
              ))}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>
    );
  };

  /** 直播源分组（折叠态）：直接平铺渲染子项图标 */
  const renderLiveSourcesCollapsed = () => (
    <Fragment key="live-sources-collapsed">
      {liveSourceItems.map((s) => (
        <Fragment key={s.path}>{renderLiveSourceLink(s)}</Fragment>
      ))}
    </Fragment>
  );

  /** 实验功能分组（展开态）：分组按钮 + 可折叠子项 */
  const renderExperimentsGroup = () => {
    const isExperimentChildActive = experimentItems.some(
      (e) => `/${e.path}` === location.pathname,
    );
    return (
      <div key="experiment-group">
        <button
          type="button"
          onClick={() => setIsExperimentsExpanded(!isExperimentsExpanded)}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-fast',
            isExperimentChildActive
              ? 'bg-primary/15 font-medium text-primary shadow-[inset_0_1px_0_var(--glass-border)]'
              : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
          )}
        >
          <FlaskConical className="h-4 w-4 shrink-0" />
          <span className="whitespace-nowrap">{t('management.sidebar.experimental')}</span>
          <ChevronDown
            className={cn(
              'ml-auto h-4 w-4 transition-transform duration-fast',
              isExperimentsExpanded && 'rotate-180',
            )}
          />
        </button>

        <AnimatePresence initial={false}>
          {isExperimentsExpanded && (
            <motion.ul
              key="experiment-submenu"
              className="ml-4 mt-1 space-y-1 overflow-hidden border-l border-[var(--glass-border)] pl-3"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            >
              {experimentItems.map((e) => (
                <li key={e.path}>{renderFlatLink(e)}</li>
              ))}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>
    );
  };

  /** 实验功能分组（折叠态）：不占位，直接平铺渲染子项图标 */
  const renderExperimentsCollapsed = () => (
    <Fragment key="experiment-group-collapsed">
      {experimentItems.map((e) => (
        <Fragment key={e.path}>{renderFlatLink(e)}</Fragment>
      ))}
    </Fragment>
  );

  /** 插件与集成分组（展开态）：分组按钮 + 可折叠子项 */
  const renderIntegrationGroup = () => {
    const isIntegrationChildActive = integrationItems.some(
      (e) => `/${e.path}` === location.pathname,
    );
    return (
      <div key="integration-group">
        <button
          type="button"
          onClick={() => setIsIntegrationExpanded(!isIntegrationExpanded)}
          className={cn(
            'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-fast',
            isIntegrationChildActive
              ? 'bg-primary/15 font-medium text-primary shadow-[inset_0_1px_0_var(--glass-border)]'
              : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] hover:text-foreground',
          )}
        >
          <Cable className="h-4 w-4 shrink-0" />
          <span className="whitespace-nowrap">{t('management.sidebar.integration')}</span>
          <ChevronDown
            className={cn(
              'ml-auto h-4 w-4 transition-transform duration-fast',
              isIntegrationExpanded && 'rotate-180',
            )}
          />
        </button>

        <AnimatePresence initial={false}>
          {isIntegrationExpanded && (
            <motion.ul
              key="integration-submenu"
              className="ml-4 mt-1 space-y-1 overflow-hidden border-l border-[var(--glass-border)] pl-3"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
            >
              {integrationItems.map((e) => (
                <li key={e.path}>{renderFlatLink(e)}</li>
              ))}
            </motion.ul>
          )}
        </AnimatePresence>
      </div>
    );
  };

  /** 插件与集成分组（折叠态）：不占位，直接平铺渲染子项图标 */
  const renderIntegrationCollapsed = () => (
    <Fragment key="integration-group-collapsed">
      {integrationItems.map((e) => (
        <Fragment key={e.path}>{renderFlatLink(e)}</Fragment>
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
          <img
            src={appIcon}
            alt={t('management.title')}
            className={cn('shrink-0 object-contain', collapsed ? 'h-8 w-8' : 'h-7 w-7')}
          />
          {!collapsed && (
            <span className="text-gradient text-lg font-bold whitespace-nowrap">{t('management.title')}</span>
          )}
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
          {flatItems.map((entry) =>
            entry.path === 'chat' ? renderChatItem() : <Fragment key={entry.path || '__index__'}>{renderFlatLink(entry)}</Fragment>,
          )}
          {collapsed ? renderLiveSourcesCollapsed() : renderLiveSourcesGroup()}
          {collapsed ? renderExperimentsCollapsed() : renderExperimentsGroup()}
          {collapsed ? renderIntegrationCollapsed() : renderIntegrationGroup()}
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

      {/* 配置变更通知 toast */}
      <ConfigToast toast={configToast} />
    </div>
  );
}
