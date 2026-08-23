/**
 * 管理界面路由登记表（路由注册契约 · Task 6.1 冻结）
 * ============================================================================
 * 本文件是管理窗（HashRouter '/' 下嵌套子路由）页面登记的唯一权威来源。
 *
 * 登记规则（契约，Task 7/8 及后续页面任务必须遵守）：
 * 1. 只允许向 MANAGEMENT_ROUTES 数组**末尾追加**新条目；
 *    不得修改/删除既有条目，不得改动布局组件（ManagementLayout）与登记机制；
 * 2. path 为管理窗内相对路径（不含前导斜杠），命名小写连字符（如 'audio-panel'）；
 *    首页（仪表盘）固定为空串 ''（index 路由）；不得与既有 path 重复；
 *    不得占用 '/pet'、'/danmaku'（独立窗顶层路由）；
 * 3. 页面组件文件放 src/pages/management/ 下，命名 {Name}Page.tsx，
 *    必须经 React.lazy 懒加载登记；
 * 4. 侧边栏标题 i18n key 统一登记在 management.nav.* 命名空间。
 *
 * 契约全文见 .trae/specs/build-app-pet-frontend/route-contract.md
 * ============================================================================
 */
import { lazy } from 'react';
import type { ComponentType, LazyExoticComponent } from 'react';
import {
  Archive,
  AudioLines,
  AudioWaveform,
  Bot,
  Brain,
  Captions,
  Cat,
  Database,
  FlaskConical,
  HeartPulse,
  LayoutDashboard,
  Layers,
  MessageSquareText,
  MonitorPlay,
  Moon,
  Network,
  Puzzle,
  Settings,
  SlidersHorizontal,
  Sparkles,
  User,
  Volume2,
  Wrench,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

/** 单条管理页路由登记项 */
export interface ManagementRouteEntry {
  /** 管理窗内相对路径（不含前导斜杠）；首页（仪表盘）固定为 ''（index 路由） */
  path: string;
  /** 侧边栏标题 i18n key（management.nav.* 命名空间） */
  titleKey: string;
  /** 侧边栏图标（lucide-react 组件） */
  icon: LucideIcon;
  /** 页面组件（必须 React.lazy 懒加载） */
  Component: LazyExoticComponent<ComponentType>;
}

/** 独立窗顶层路由：管理窗登记表不得占用 */
export const RESERVED_TOP_LEVEL_PATHS = ['/pet', '/danmaku'] as const;

/**
 * 集中式路由登记表。
 * 第一批页面（Task 6）：仪表盘 / 对话 / 记忆 / 归档 / 设置。
 * 后续批次（Task 7/8）只能向数组末尾追加。
 */
export const MANAGEMENT_ROUTES: readonly ManagementRouteEntry[] = [
  {
    path: '',
    titleKey: 'management.nav.dashboard',
    icon: LayoutDashboard,
    Component: lazy(() => import('./DashboardPage')),
  },
  {
    path: 'chat',
    titleKey: 'management.nav.chat',
    icon: MessageSquareText,
    Component: lazy(() => import('./ChatPage')),
  },
  {
    path: 'memories',
    titleKey: 'management.nav.memories',
    icon: Brain,
    Component: lazy(() => import('./MemoriesPage')),
  },
  {
    path: 'archive',
    titleKey: 'management.nav.archive',
    icon: Archive,
    Component: lazy(() => import('./ArchivePage')),
  },
  {
    path: 'settings',
    titleKey: 'management.nav.settings',
    icon: Settings,
    Component: lazy(() => import('./SettingsPage')),
  },
  // ── 第二批页面（Task 7）：仅追加，不改既有条目 ──
  {
    path: 'agents',
    titleKey: 'management.nav.agents',
    icon: Bot,
    Component: lazy(() => import('./AgentsPage')),
  },
  {
    path: 'acp',
    titleKey: 'management.nav.acp',
    icon: Network,
    Component: lazy(() => import('./AcpPage')),
  },
  // SubTask 7.2：插件页 + 工具页
  {
    path: 'plugins',
    titleKey: 'management.nav.plugins',
    icon: Puzzle,
    Component: lazy(() => import('./PluginsPage')),
  },
  {
    path: 'tools',
    titleKey: 'management.nav.tools',
    icon: Wrench,
    Component: lazy(() => import('./ToolsPage')),
  },
  // SubTask 7.3：记忆代理页 + 向量数据页
  {
    path: 'memory-agent',
    titleKey: 'management.nav.memoryAgent',
    icon: Sparkles,
    Component: lazy(() => import('./MemoryAgentPage')),
  },
  {
    path: 'vector',
    titleKey: 'management.nav.vector',
    icon: Database,
    Component: lazy(() => import('./VectorDataPage')),
  },
  // SubTask 7.4：音频面板 / 音频测试 / 音频工作站
  {
    path: 'audio-panel',
    titleKey: 'management.nav.audioPanel',
    icon: AudioLines,
    Component: lazy(() => import('./AudioPanelPage')),
  },
  {
    path: 'audio-test',
    titleKey: 'management.nav.audioTest',
    icon: AudioWaveform,
    Component: lazy(() => import('./AudioTestPage')),
  },
  {
    path: 'audio-workstation',
    titleKey: 'management.nav.audioWorkstation',
    icon: SlidersHorizontal,
    Component: lazy(() => import('./AudioWorkstationPage')),
  },
  // ── 第三批页面（Task 8）：直播控制台 / 直播分屏 / 四类浏览器源（仅追加，不改既有条目） ──
  {
    path: 'live-console',
    titleKey: 'management.nav.liveConsole',
    icon: MonitorPlay,
    Component: lazy(() => import('./LiveConsolePage')),
  },
  {
    path: 'live-overlay',
    titleKey: 'management.nav.liveOverlay',
    icon: Layers,
    Component: lazy(() => import('./LiveOverlayPage')),
  },
  {
    path: 'avatar-source',
    titleKey: 'management.nav.avatarSource',
    icon: User,
    Component: lazy(() => import('./AvatarSourcePage')),
  },
  {
    path: 'danmaku-source',
    titleKey: 'management.nav.danmakuSource',
    icon: MessageSquareText,
    Component: lazy(() => import('./DanmakuSourcePage')),
  },
  {
    path: 'subtitle-source',
    titleKey: 'management.nav.subtitleSource',
    icon: Captions,
    Component: lazy(() => import('./SubtitleSourcePage')),
  },
  {
    path: 'audio-source',
    titleKey: 'management.nav.audioSource',
    icon: Volume2,
    Component: lazy(() => import('./AudioSourcePage')),
  },
  // ── 蒸馏页（仅追加，不改既有条目） ──
  {
    path: 'distillation',
    titleKey: 'management.nav.distillation',
    icon: FlaskConical,
    Component: lazy(() => import('./DistillationPage')),
  },
  // ── Neko 插件兼容层页（仅追加，不改既有条目；物理读 neko 插件服务器） ──
  {
    path: 'neko',
    titleKey: 'management.nav.neko',
    icon: Cat,
    Component: lazy(() => import('./NekoPluginsPage')),
  },
  // ── Agent 生活页（P4-T1，仅追加，不改既有条目） ──
  {
    path: 'autonomy',
    titleKey: 'management.nav.autonomy',
    icon: HeartPulse,
    Component: lazy(() => import('./AutonomyPage')),
  },
  // ── 梦境日志页（DreamPage，仅追加，不改既有条目） ──
  {
    path: 'dream',
    titleKey: 'management.nav.dream',
    icon: Moon,
    Component: lazy(() => import('./DreamPage')),
  },
];

/** 由管理窗内绝对路径（如 '/chat'）反查登记条目；未登记返回 undefined */
export function findRouteByPathname(
  pathname: string,
): ManagementRouteEntry | undefined {
  const rel = pathname.startsWith('/') ? pathname.slice(1) : pathname;
  return MANAGEMENT_ROUTES.find((entry) => entry.path === rel);
}

/** 登记表结构校验（单测与开发期自检共用）；返回违规说明列表，空数组即通过 */
export function validateRouteRegistry(
  entries: readonly ManagementRouteEntry[] = MANAGEMENT_ROUTES,
): string[] {
  const violations: string[] = [];
  const seen = new Set<string>();

  if (entries.length === 0) {
    violations.push('登记表为空：至少需要首页（path 为空串）条目');
  }
  if (entries[0]?.path !== '') {
    violations.push("首条登记项必须是首页（path 为空串 '' 的 index 路由）");
  }

  for (const entry of entries) {
    if (entry.path.includes('/')) {
      violations.push(`path '${entry.path}' 非法：只允许单层相对路径`);
    }
    if (entry.path !== '' && !/^[a-z0-9]+(-[a-z0-9]+)*$/.test(entry.path)) {
      violations.push(`path '${entry.path}' 非法：必须使用小写连字符命名`);
    }
    if (seen.has(entry.path)) {
      violations.push(`path '${entry.path}' 重复登记`);
    }
    seen.add(entry.path);
    if (RESERVED_TOP_LEVEL_PATHS.some((p) => p === `/${entry.path}`)) {
      violations.push(`path '${entry.path}' 占用独立窗顶层路由（/pet、/danmaku）`);
    }
    if (!entry.titleKey.startsWith('management.nav.')) {
      violations.push(`titleKey '${entry.titleKey}' 必须位于 management.nav.* 命名空间`);
    }
    if (!entry.icon) {
      violations.push(`path '${entry.path}' 缺少侧边栏图标`);
    }
    if (!entry.Component) {
      violations.push(`path '${entry.path}' 缺少页面组件（必须 React.lazy 登记）`);
    }
  }

  return violations;
}
