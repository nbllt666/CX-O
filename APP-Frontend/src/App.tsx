import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { HashRouter, Routes, Route } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import ManagementLayout from '@/components/management/ManagementLayout';
import { MANAGEMENT_ROUTES } from '@/pages/management/routes';
import PetPage from '@/pages/PetPage';
import DanmakuPage from '@/pages/DanmakuPage';
import ConnectionSetup from '@/components/ConnectionSetup';
import GlobalToasts from '@/components/GlobalToast';
import { useThemeStore } from '@/store/themeStore';
import { useSettingsStore } from '@/store/settingsStore';
import { getApiBaseUrl } from '@/api/base';
import { useBackendFailover } from '@/hooks/useBackendFailover';

// 顶层 OBS 浏览器源页（/source/*）：自包含、无管理布局依赖、懒加载，
// 供 OBS 浏览器源独立拉取（透明背景 + 1920×1080）。
const LiveOverlayPage = lazy(() => import('@/pages/management/LiveOverlayPage'));
const AvatarSourcePage = lazy(() => import('@/pages/management/AvatarSourcePage'));
const DanmakuSourcePage = lazy(() => import('@/pages/management/DanmakuSourcePage'));
const SubtitleSourcePage = lazy(() => import('@/pages/management/SubtitleSourcePage'));
const AudioSourcePage = lazy(() => import('@/pages/management/AudioSourcePage'));

/**
 * 依据当前 hash 判定应渲染的顶层 OBS 源页；非 /source/* 返回 null。
 * 这些页面需跳过后端连接门，保证 OBS 无论后端是否在线都能拉取到源画面。
 */
function resolveSourceRoute(): React.ReactNode | null {
  if (typeof window === 'undefined') return null;
  const hash = window.location.hash;
  if (hash.startsWith('#/source/live-overlay')) return <LiveOverlayPage />;
  if (hash.startsWith('#/source/avatar-source')) return <AvatarSourcePage />;
  if (hash.startsWith('#/source/danmaku-source')) return <DanmakuSourcePage />;
  if (hash.startsWith('#/source/subtitle-source')) return <SubtitleSourcePage />;
  if (hash.startsWith('#/source/audio-source')) return <AudioSourcePage />;
  return null;
}

/**
 * 路由（HashRouter：同时兼容 dev server 与生产 loadFile）：
 *   /        管理界面（managementWindow 加载）：ManagementLayout 布局 +
 *            MANAGEMENT_ROUTES 登记表驱动的嵌套子路由（/ 仪表盘、/chat、/memories…）
 *   /pet     桌宠悬浮窗（petWindow 加载）
 *   /danmaku 弹幕窗（danmakuWindow 加载）
 *
 * 连接检测门：启动时探测后端 /health，不可达时先渲染 ConnectionSetup，
 * 连接成功（或用户填写新地址并连通）后才进入路由。
 * 后端地址与存储初始化已在 main.tsx bootstrap 中完成。
 */
export default function App() {
  const { t } = useTranslation();
  const theme = useThemeStore((s) => s.theme);
  const [isConnected, setIsConnected] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const cancelledRef = useRef(false);

  // 启动时将 store 中的主题同步到 <html data-theme>（bootstrap 脚本已先行设置，此处对齐后续切换）
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // 按路由固定 document.title（SubTask 9.1：桌宠窗标题唯一可识别）。
  // 桌宠窗主进程已拦截 page-title-updated、恒为 'CXO-Pet'；管理窗/弹幕窗未拦截，
  // 若不写回将随 index.html 的 <title> 漂移成与桌宠窗同名的 'CXO-Pet'，
  // 三窗重名会干扰 OBS 窗口采集的唯一选中。标题口径与 main.ts 各窗创建 title 一致。
  useEffect(() => {
    const hash = window.location.hash;
    if (hash.startsWith('#/pet')) {
      document.title = 'CXO-Pet';
    } else if (hash.startsWith('#/danmaku')) {
      document.title = 'CXO-Pet 弹幕';
    } else {
      document.title = 'CXO-Pet 管理界面';
    }
  }, []);

  useEffect(() => {
    cancelledRef.current = false;

    const checkBackendConnection = async () => {
      try {
        const response = await fetch(`${getApiBaseUrl()}/health`, {
          method: 'GET',
          signal: AbortSignal.timeout(3000),
        });
        if (cancelledRef.current) return;
        if (response.ok) {
          setIsConnected(true);
          // 连接成功后拉取后端限制配置（失败静默，走默认 min/max）
          void useSettingsStore.getState().fetchLimits();
        } else {
          setIsConnected(false);
        }
      } catch {
        if (cancelledRef.current) return;
        setIsConnected(false);
      } finally {
        if (!cancelledRef.current) {
          setIsChecking(false);
        }
      }
    };

    void checkBackendConnection();
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  // 后端集群感知故障转移：当前后端失联时自动切到健康对等节点（含桌宠可视化/弹幕窗）。
  // 挂在根组件，所有窗口随 App 渲染均生效；切换成功后重载窗以新地址重连。
  useBackendFailover();

  // 顶层 OBS 浏览器源路由：跳过后端连接门，自包含独立渲染（懒加载）。
  const sourceRoute = resolveSourceRoute();
  if (sourceRoute) {
    return (
      <HashRouter>
        <Routes>
          <Route
            path="/source/*"
            element={<Suspense fallback={null}>{sourceRoute}</Suspense>}
          />
        </Routes>
      </HashRouter>
    );
  }

  // 桌宠窗与弹幕窗独立于后端连接门：即使后端不可达也应正常渲染
  //（对话/ASR 等功能降级，但窗口本身可用）。连接门仅拦截管理界面。
  const hash = typeof window !== 'undefined' ? window.location.hash : '';
  if (hash.startsWith('#/pet') || hash.startsWith('#/danmaku')) {
    return (
      <HashRouter>
        <Routes>
          <Route path="/pet" element={<PetPage />} />
          <Route path="/danmaku" element={<DanmakuPage />} />
        </Routes>
        {/* D9 全局轻量 toast（cluster_event / autonomy_cost_alert）；OBS /source/* 叠加页不挂载 */}
        <GlobalToasts />
      </HashRouter>
    );
  }

  if (isChecking) {
    return (
      <div className="app-surface flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">{t('connection.checking')}</div>
      </div>
    );
  }

  if (!isConnected) {
    return <ConnectionSetup onConnected={() => setIsConnected(true)} />;
  }

  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<ManagementLayout />}>
          {MANAGEMENT_ROUTES.map((entry) =>
            entry.path === '' ? (
              <Route key="__index__" index element={<entry.Component />} />
            ) : (
              <Route key={entry.path} path={entry.path} element={<entry.Component />} />
            ),
          )}
        </Route>
      </Routes>
      {/* D9 全局轻量 toast（cluster_event / autonomy_cost_alert） */}
      <GlobalToasts />
    </HashRouter>
  );
}
