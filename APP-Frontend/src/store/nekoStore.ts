/**
 * Neko 插件运行时状态存储（渲染层）
 * ============================================================================
 * 维护插件服务器 sidecar 的运行状态、插件列表、商店目录、安装任务与实时日志。
 * 所有数据来自 nekoApi；运行时配置的持久化由 Electron 主进程 config 承接，
 * 这里仅做内存快照便于页面渲染。
 * ============================================================================
 */
import { create } from 'zustand';
import {
  nekoApi,
  setNekoPort,
  normalizePluginList,
  type NekoPluginItem,
  type NekoMarketStatus,
  type NekoInstalledPlugin,
  type NekoCatalogPlugin,
  type NekoInstallTask,
  type NekoMarketInstallRequest,
} from '../api/clients/neko';
// NekoRuntimeConfig 为全局环境类型（src/types/electron.d.ts），无需导入

interface NekoBridgeStatus {
  registrarRunning: boolean;
  bridgeRunning: boolean;
  bridgePort: number | null;
  tools: number;
  cxfcRegistered: boolean;
}

interface NekoState {
  // 运行时
  running: boolean;
  port: number | null;
  config: NekoRuntimeConfig;
  checking: boolean;
  bridge: NekoBridgeStatus | null;

  // 数据
  plugins: NekoPluginItem[];
  installed: NekoInstalledPlugin[];
  marketStatus: NekoMarketStatus | null;
  catalog: NekoCatalogPlugin[];
  installTasks: Record<string, NekoInstallTask>;

  // 日志
  logs: string[];

  // UI 状态
  loadingPlugins: boolean;
  loadingCatalog: boolean;
  error: string | null;
  marketUnreachable: boolean;

  // actions
  refreshStatus: () => Promise<void>;
  refreshBridgeStatus: () => Promise<void>;
  startRuntime: () => Promise<{ ok: boolean; error?: string }>;
  stopRuntime: () => Promise<{ ok: boolean; error?: string }>;
  setConfig: (partial: Partial<NekoRuntimeConfig>) => Promise<void>;
  refreshPlugins: () => Promise<void>;
  refreshInstalled: () => Promise<void>;
  refreshMarket: () => Promise<void>;
  refreshCatalog: () => Promise<void>;
  pluginAction: (pluginId: string, action: 'start' | 'stop' | 'refresh' | 'reload') => Promise<void>;
  installPlugin: (req: NekoMarketInstallRequest) => Promise<string | null>;
  pollTask: (taskId: string) => Promise<void>;
  appendLog: (line: string) => void;
  clearLogs: () => void;
  clearError: () => void;
}

const MAX_LOGS = 800;

// 各刷新动作的单调请求序号：并发触发时，旧请求的过期响应不覆盖最新请求写入的状态。
let statusSeq = 0;
let bridgeSeq = 0;
let pluginSeq = 0;
let installedSeq = 0;
let marketSeq = 0;
let catalogSeq = 0;
// pollTask 按 task 追踪请求序号，防止旧轮询的迟到响应覆盖新状态
const taskSeqMap = new Map<string, number>();

export const useNekoStore = create<NekoState>()((set, get) => ({
  running: false,
  port: null,
  config: {
    python: 'python',
    sourceDir: 'C:\\N.E.K.O-main',
    port: 48916,
    autoStart: false,
  },
  checking: false,
  bridge: null,

  plugins: [],
  installed: [],
  marketStatus: null,
  catalog: [],
  installTasks: {},
  logs: [],

  loadingPlugins: false,
  loadingCatalog: false,
  error: null,
  marketUnreachable: false,

  refreshStatus: async () => {
    const seq = ++statusSeq;
    set({ checking: true });
    try {
      let status: { running: boolean; port: number | null; config: NekoRuntimeConfig };
      if (window.neko) {
        status = await window.neko.getStatus();
      } else {
        // 浏览器模式：无桥，无法感知真实运行状态 → 展示未运行，避免对不存在服务发无效 HTTP
        status = {
          running: false,
          port: null,
          config: get().config,
        };
      }
      // 过期响应不覆盖新状态
      if (seq !== statusSeq) return;
      setNekoPort(status.port);
      set({
        running: status.running,
        port: status.port,
        config: status.config,
      });
      if (status.running && status.port) {
        await get().refreshBridgeStatus();
        await Promise.allSettled([
          get().refreshPlugins(),
          get().refreshInstalled(),
          get().refreshMarket(),
        ]);
      } else {
        // F2: 运行时被外部终止（崩溃/手动杀进程）后刷新，须与 stopRuntime 一致清理
        // 旧插件/商店列表，避免 running=false 下 UI 仍展示过期数据。
        set({ bridge: null, plugins: [], installed: [], marketStatus: null, catalog: [] });
      }
    } finally {
      if (seq === statusSeq) set({ checking: false });
    }
  },

  refreshBridgeStatus: async () => {
    if (!window.neko) {
      set({ bridge: null });
      return;
    }
    const seq = ++bridgeSeq;
    try {
      const bridge = await window.neko.getBridgeStatus();
      if (seq === bridgeSeq) set({ bridge });
    } catch {
      if (seq === bridgeSeq) set({ bridge: null });
    }
  },

  startRuntime: async () => {
    if (!window.neko) return { ok: false, error: '仅在桌面模式（Electron）下支持启动插件服务器' };
    const res = await window.neko.start();
    if (res.ok && res.port) {
      setNekoPort(res.port);
      set({ running: true, port: res.port });
      await get().refreshBridgeStatus();
      await get().refreshPlugins();
    }
    return { ok: res.ok, error: res.error };
  },

  stopRuntime: async () => {
    if (!window.neko) return { ok: false, error: '仅在桌面模式下支持停止' };
    const res = await window.neko.stop();
    if (res.ok) {
      setNekoPort(null);
      set({ running: false, port: null, bridge: null, plugins: [], installed: [], marketStatus: null, catalog: [] });
    }
    return { ok: res.ok, error: res.error };
  },

  setConfig: async (partial) => {
    if (window.neko) {
      const next = await window.neko.setConfig(partial);
      setNekoPort(next.port);
      set({ config: next });
    } else {
      set((s) => ({ config: { ...s.config, ...partial } }));
    }
  },

  refreshPlugins: async () => {
    const seq = ++pluginSeq;
    set({ loadingPlugins: true });
    try {
      const data = await nekoApi.listPlugins();
      if (seq !== pluginSeq) return;
      set({ plugins: normalizePluginList(data), error: null });
    } catch (e) {
      if (seq === pluginSeq) {
        set({ error: e instanceof Error ? e.message : '插件列表加载失败' });
      }
    } finally {
      if (seq === pluginSeq) set({ loadingPlugins: false });
    }
  },

  refreshInstalled: async () => {
    const seq = ++installedSeq;
    try {
      const data = await nekoApi.marketInstalled();
      if (seq === installedSeq) set({ installed: data?.installed ?? [], error: null });
    } catch {
      // 市场桥不可达不阻塞插件列表
    }
  },

  refreshMarket: async () => {
    const seq = ++marketSeq;
    try {
      const status = await nekoApi.marketStatus();
      if (seq === marketSeq) set({ marketStatus: status, marketUnreachable: false, error: null });
    } catch {
      if (seq === marketSeq) set({ marketUnreachable: true });
    }
  },

  refreshCatalog: async () => {
    const seq = ++catalogSeq;
    set({ loadingCatalog: true });
    try {
      const data = (await nekoApi.marketCatalog()) as unknown;
      // 目录可能是数组，或 {plugins:[...]}
      let list: NekoCatalogPlugin[] = [];
      if (Array.isArray(data)) {
        list = data as NekoCatalogPlugin[];
      } else if (data && typeof data === 'object') {
        const obj = data as Record<string, unknown>;
        const raw = obj.plugins ?? obj.items ?? obj.data;
        if (Array.isArray(raw)) list = raw as NekoCatalogPlugin[];
      }
      if (seq !== catalogSeq) return;
      set({ catalog: list, marketUnreachable: false, error: null });
    } catch (e) {
      if (seq === catalogSeq) {
        set({ error: e instanceof Error ? e.message : '商店目录加载失败', marketUnreachable: true });
      }
    } finally {
      if (seq === catalogSeq) set({ loadingCatalog: false });
    }
  },

  pluginAction: async (pluginId, action) => {
    await nekoApi.pluginAction(pluginId, action);
    await get().refreshPlugins();
  },

  installPlugin: async (req) => {
    try {
      const res = await nekoApi.marketInstall(req);
      set((s) => ({
        installTasks: { ...s.installTasks, [res.task_id]: { task_id: res.task_id, status: res.status, stage: 'pending', progress: 0, message: res.message } },
        error: null,
      }));
      return res.task_id;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : '安装请求失败' });
      return null;
    }
  },

  pollTask: async (taskId) => {
    // 单调请求序号：仅最新一次轮询响应生效，旧轮询的迟到响应不覆盖新状态
    const seq = (taskSeqMap.get(taskId) ?? 0) + 1;
    taskSeqMap.set(taskId, seq);
    try {
      const task = await nekoApi.marketTask(taskId);
      if (taskSeqMap.get(taskId) !== seq) return;
      set((s) => ({ installTasks: { ...s.installTasks, [taskId]: task }, error: null }));
      if (task.status === 'completed') {
        await get().refreshInstalled();
        await get().refreshPlugins();
      }
    } catch (e) {
      if (taskSeqMap.get(taskId) !== seq) return;
      set({ error: e instanceof Error ? e.message : '任务查询失败' });
    }
  },

  appendLog: (line) => {
    set((s) => {
      const logs = [...s.logs, line];
      if (logs.length > MAX_LOGS) logs.splice(0, logs.length - MAX_LOGS);
      return { logs };
    });
  },

  clearLogs: () => set({ logs: [] }),
  clearError: () => set({ error: null }),
}));

/** 订阅 IPC 日志（Electron）；返回取消订阅函数（供组件 effect 使用） */
export function subscribeNekoLogs(store: typeof useNekoStore): (() => void) | undefined {
  if (!window.neko) return undefined;
  return window.neko.onLog((line) => store.getState().appendLog(line));
}
