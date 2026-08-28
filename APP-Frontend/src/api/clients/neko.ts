/**
 * Neko 插件服务器兼容层（渲染层）
 * ============================================================================
 * 把插件服务器（python -m plugin.user_plugin_server）的 REST 契约封装成类型化
 * 方法供管理页使用。所有跨源请求优先经主进程 net.fetch 代理（生产 file:// 下
 * 规避 CORS 与 Host/Origin 守卫），浏览器模式下回退为直连 fetch。
 *
 * 覆盖：health、插件 CRUD、日志、消息，以及市场桥（商店目录 / 安装 / 任务）。
 * ============================================================================
 */
// （NekoRuntimeConfig 为全局环境类型，定义于 src/types/electron.d.ts，无需导入）

// ═══════════════════════════════════════════════════════════════════════════
// 传输层
// ═══════════════════════════════════════════════════════════════════════════

/** 当前插件服务器端口（nekoStore 启动时经 status/config 设置） */
let currentPort: number | null = null;
let cachedMarketToken: string | null = null;

/** 浏览器直连 fetch 超时（ms），与主进程 neko:http 15s 超时对齐 */
const NEKO_FETCH_TIMEOUT_MS = 15000;

export function setNekoPort(port: number | null): void {
  currentPort = port;
  // 端口变化时 token 可能失效，重置
  cachedMarketToken = null;
}

export function getNekoPort(): number | null {
  return currentPort;
}

/** 在可用端口报错时的归一化消息 */
export function nekoUnavailableError(): Error {
  return new Error('Neko 插件服务器未运行，请先在「设置」中启动');
}

function buildUrl(pathValue: string, query?: Record<string, string | number | boolean>): string {
  if (!currentPort) {
    throw nekoUnavailableError();
  }
  if (!pathValue.startsWith('/')) {
    throw new Error('非法路径');
  }
  const params = query
    ? `?${Object.entries(query)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&')}`
    : '';
  return `http://127.0.0.1:${currentPort}${pathValue}${params}`;
}

interface NekoResult {
  ok: boolean;
  status?: number;
  body?: string;
  error?: string;
}

/** 走主进程代理（Electron） */
async function ipcRequest<T>(
  method: string,
  pathValue: string,
  query?: Record<string, string | number | boolean>,
  body?: unknown,
): Promise<T> {
  if (!window.neko) {
    throw new Error('未检测到 Electron Neko 桥');
  }
  const res: NekoResult = await window.neko.http({ method, path: pathValue, query, body });
  if (!res.ok || typeof res.body !== 'string') {
    throw new Error(res.error || 'Neko 请求失败');
  }
  if (res.status !== undefined && res.status >= 400) {
    let detail = res.body;
    try {
      const parsed = JSON.parse(res.body) as { detail?: string } | string;
      detail = typeof parsed === 'string' ? parsed : (parsed.detail ?? res.body);
    } catch {
      /* 保留原文 */
    }
    throw new Error(`Neko 请求失败 (${res.status})：${detail}`);
  }
  try {
    return JSON.parse(res.body) as T;
  } catch {
    // 成功响应体非合法 JSON：带状态码与原文片段抛错（与上方错误分支风格同构）
    const snippet = res.body.length > 120 ? `${res.body.slice(0, 120)}…` : res.body;
    throw new Error(`Neko 响应解析失败 (${res.status ?? 'unknown'})：${snippet}`);
  }
}

/** 浏览器 / 直连回退（F4：加 15s 超时——旧实现裸 fetch 无超时，插件服务器挂起
 *  时 Promise 永久悬挂，nekoStore 的 loading 态无法复位；与主进程 neko:http 超时对齐） */
async function directRequest<T>(
  method: string,
  pathValue: string,
  query?: Record<string, string | number | boolean>,
  body?: unknown,
): Promise<T> {
  const init: RequestInit = {
    method,
    headers: { Accept: 'application/json' },
  };
  if (body !== undefined) {
    init.headers = { ...init.headers, 'Content-Type': 'application/json' };
    init.body = typeof body === 'string' ? body : JSON.stringify(body);
  }
  const res = await fetch(buildUrl(pathValue, query), {
    ...init,
    signal: AbortSignal.timeout(NEKO_FETCH_TIMEOUT_MS),
  });
  if (!res.ok) {
    let detail = '';
    try {
      const parsed = (await res.json()) as { detail?: string };
      detail = parsed.detail ?? '';
    } catch {
      /* ignore */
    }
    throw new Error(`Neko 请求失败 (${res.status})：${detail}`);
  }
  return (await res.json()) as T;
}

/** 统一请求：优先 IPC 代理，浏览器降级直接 fetch */
export async function nekoRequest<T>(
  method: string,
  pathValue: string,
  query?: Record<string, string | number | boolean>,
  body?: unknown,
): Promise<T> {
  if (window.neko) {
    return ipcRequest<T>(method, pathValue, query, body);
  }
  return directRequest<T>(method, pathValue, query, body);
}

/** 获取市场桥 token（安装/任务/已安装需要）；未运行则抛错 */
export async function nekoEnsureMarketToken(): Promise<string> {
  if (cachedMarketToken) return cachedMarketToken;
  if (!currentPort) throw nekoUnavailableError();
  const res = await nekoRequest<{ bridge_token?: string; port?: number }>('GET', '/market/bridge-token');
  if (!res?.bridge_token) {
    throw new Error('无法获取市场桥 token');
  }
  cachedMarketToken = res.bridge_token;
  return cachedMarketToken;
}

// ═══════════════════════════════════════════════════════════════════════════
// 类型（对齐插件服务器 REST 契约；目录/列表字段做防御性建模）
// ═══════════════════════════════════════════════════════════════════════════

export interface NekoPluginItem {
  id: string;
  name?: string;
  description?: string;
  version?: string;
  enabled?: boolean;
  auto_start?: boolean;
  status?: string;
  [key: string]: unknown;
}

export interface NekoMarketStatus {
  online: boolean;
  version: string;
  protocol_version: number;
  client_name: string;
  installed_count: number;
  token_required: boolean;
  market_url: string;
  market_web_url: string;
  [key: string]: unknown;
}

export interface NekoInstalledPlugin {
  plugin_id: string;
  path: string;
  latest_install_source?: {
    plugin_market_id?: string;
    channel?: string;
    version?: string;
    package_url?: string;
    published_at?: string;
    [key: string]: unknown;
  } | null;
}

export interface NekoCatalogPlugin {
  id?: string;
  slug?: string;
  name?: string;
  description?: string;
  version?: string;
  latest_version?: {
    version?: string;
    channel?: string;
    package_url?: string;
    package_sha256?: string;
    created_at?: string;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

export interface NekoMarketInstallRequest {
  package_url: string;
  package_sha256: string;
  plugin_id?: string;
  version?: string;
  channel?: string;
  published_at?: string;
  mode?: 'install' | 'upgrade' | 'reinstall';
  expected_plugin_toml_id?: string;
  on_conflict?: 'fail' | 'rename';
  canonical_package_url?: string;
}

export interface NekoInstallTask {
  task_id: string;
  status: string;
  stage: string;
  progress: number;
  message: string;
  downloaded_bytes?: number;
  total_bytes?: number | null;
  result?: Record<string, unknown> | null;
  error?: string | null;
  error_code?: string | null;
  created_at?: number;
  completed_at?: number | null;
}

// ═══════════════════════════════════════════════════════════════════════════
// API
// ═══════════════════════════════════════════════════════════════════════════

export const nekoApi = {
  // -- 运行时/健康 --
  health(): Promise<Record<string, unknown>> {
    return nekoRequest('GET', '/health');
  },

  // -- 插件管理 --
  listPlugins(): Promise<Record<string, unknown>> {
    return nekoRequest('GET', '/api/plugins');
  },
  getPluginStatus(pluginId?: string): Promise<Record<string, unknown>> {
    return nekoRequest('GET', '/api/plugin/status', pluginId ? { id: pluginId } : undefined);
  },
  pluginAction(pluginId: string, action: 'start' | 'stop' | 'refresh' | 'reload'): Promise<Record<string, unknown>> {
    return nekoRequest('POST', `/api/plugin/${encodeURIComponent(pluginId)}/${action}`);
  },
  reloadAllPlugins(): Promise<Record<string, unknown>> {
    return nekoRequest('POST', '/api/plugins/reload');
  },
  refreshRegistry(): Promise<Record<string, unknown>> {
    return nekoRequest('POST', '/api/plugins/refresh');
  },
  // -- 生命周期配置 / 事件消息 --
  getPluginConfig(pluginId: string): Promise<Record<string, unknown>> {
    return nekoRequest('GET', `/api/plugin/${encodeURIComponent(pluginId)}/config`);
  },
  getPluginMessages(pluginId: string, maxCount = 50): Promise<Record<string, unknown>> {
    return nekoRequest('GET', '/api/plugin/messages', { plugin_id: pluginId, max_count: maxCount });
  },

  // -- 市场桥 --
  marketStatus(): Promise<NekoMarketStatus> {
    return nekoRequest('GET', '/market/status');
  },
  async marketInstalled(): Promise<{ installed: NekoInstalledPlugin[]; count: number }> {
    const token = await nekoEnsureMarketToken();
    return nekoRequest('GET', '/market/installed', { token });
  },
  async marketCatalog(): Promise<unknown> {
    return nekoRequest('GET', '/market/catalog/api/v1/plugins');
  },
  async marketInstall(req: NekoMarketInstallRequest): Promise<{ task_id: string; status: string; message: string }> {
    const token = await nekoEnsureMarketToken();
    return nekoRequest('POST', '/market/install', { token }, req);
  },
  async marketTask(taskId: string): Promise<NekoInstallTask> {
    const token = await nekoEnsureMarketToken();
    return nekoRequest('GET', `/market/tasks/${encodeURIComponent(taskId)}`, { token });
  },
  async marketTaskCancel(taskId: string): Promise<NekoInstallTask> {
    const token = await nekoEnsureMarketToken();
    return nekoRequest('POST', `/market/tasks/${encodeURIComponent(taskId)}/cancel`, { token });
  },

  // -- 插件 UI / 静态资源代理（返回原始文本，供 iframe 使用）--
  pluginUiBase(port: number | null): string {
    const p = port ?? currentPort;
    if (!p) throw nekoUnavailableError();
    return `http://127.0.0.1:${p}`;
  },
};

/** 供应给 iframe 的插件 UI 地址（经主进程代理不可行时可改为直连） */
export function pluginUiUrl(port: number | null, pathValue: string): string {
  return `${nekoApi.pluginUiBase(port)}${pathValue.startsWith('/') ? pathValue : `/${pathValue}`}`;
}

/** 从 /api/plugins 返回的字典规整出插件数组（字段缺失时补齐） */
export function normalizePluginList(data: unknown): NekoPluginItem[] {
  if (Array.isArray(data)) {
    return data as NekoPluginItem[];
  }
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    // 常见形态：{plugins: [...], length: n} 或 {items: [...]}
    const raw = obj.plugins ?? obj.items ?? obj.result;
    if (Array.isArray(raw)) return raw as NekoPluginItem[];
    // 兜底：{id: {...}} 字典形态
    const entries = Object.entries(obj).filter(([, v]) => v && typeof v === 'object');
    return entries.map(([id, v]) => ({
      id,
      ...(v as Record<string, unknown>),
    }));
  }
  return [];
}
