/*
 * 桌面能力探测与连接配置。
 *
 * - Electron 环境：经 preload 暴露的 window.modelstationDesktop（IPC）读取/持久化配置到 userData；
 * - 浏览器环境：优雅降级，配置退回 localStorage，数据根与生命周期动作只读提示。
 * 注意：渲染层禁止 import Electron / Node 模块，本文件仅依赖 DOM API。
 */

// ======================== 类型（与 electron/ipc.ts 契约一致） ========================

export interface DesktopInfo {
  isDesktop: true;
  backendBaseUrl: string;
  frontendUrl: string;
  frontendPort: number;
  dataRoot: string;
  layoutMode: "packaged" | "dev";
  configFilePath: string;
}

export interface BackendStatus {
  healthy: boolean;
  baseUrl: string;
  checkedAt: number;
  detail?: string;
}

export interface BackendActionResult {
  ok: boolean;
  message: string;
  status?: BackendStatus;
}

export interface AppConfig {
  backendBaseUrl: string;
  dataRoot: string;
  preferredFrontendPort: number;
}

export interface DesktopBridge {
  isDesktop: true;
  getInfo(): Promise<DesktopInfo>;
  getConfig(): Promise<unknown>;
  setConfig(patch: Record<string, unknown>): Promise<unknown>;
  checkBackend(baseUrl?: string): Promise<BackendStatus>;
  restartBackend(): Promise<BackendActionResult>;
  stopBackend(): Promise<BackendActionResult>;
}

declare global {
  interface Window {
    modelstationDesktop?: DesktopBridge;
  }
}

// ======================== 常量 ========================

export const DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8300";
export const DEFAULT_FRONTEND_PORT = 3300;
/** 数据根默认位置的展示提示（浏览器态无法直接读取，仅作说明） */
export const DEFAULT_DATA_ROOT_HINT = "%LOCALAPPDATA%\\CXO-ModelStation\\data";
export const BACKEND_START_HINT =
  "后端不可达。可在 CXO-ModelStation 目录运行 start.bat 启动后端（默认 http://127.0.0.1:8300），或在上方修改连接地址。";
export const HEALTH_CHECK_TIMEOUT_MS = 3000;

const STORAGE_KEY = "cxo-modelstation.desktop-config";

// ======================== 环境探测 ========================

export function getDesktopBridge(): DesktopBridge | null {
  if (typeof window === "undefined") return null;
  const bridge = window.modelstationDesktop;
  return bridge && bridge.isDesktop ? bridge : null;
}

export function isDesktopRuntime(): boolean {
  return getDesktopBridge() !== null;
}

/** 是否为本机回环后端地址（用于判定桌面实际 base 是否可覆盖配置显示值） */
export function isLocalBaseUrl(baseUrl: string): boolean {
  try {
    const hostname = new URL(baseUrl).hostname;
    return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1";
  } catch {
    return false;
  }
}

// ======================== 配置归一化 / 读写 ========================

export function defaultConfig(): AppConfig {
  return {
    backendBaseUrl: DEFAULT_BACKEND_BASE_URL,
    dataRoot: "",
    preferredFrontendPort: DEFAULT_FRONTEND_PORT,
  };
}

function normalizeBaseUrl(value: unknown, fallback: string): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return fallback;
  try {
    const url = new URL(raw);
    if (url.protocol !== "http:" && url.protocol !== "https:") return fallback;
    return raw.replace(/\/+$/, "");
  } catch {
    return fallback;
  }
}

/** 归一化配置（与 electron/settings.ts 同口径，渲染层不引入 Node 依赖故此处复刻） */
export function normalizeConfig(raw: unknown, fallback: AppConfig = defaultConfig()): AppConfig {
  const data = (raw ?? {}) as Partial<Record<keyof AppConfig, unknown>>;
  const port = Number(data.preferredFrontendPort);
  return {
    backendBaseUrl: normalizeBaseUrl(data.backendBaseUrl, fallback.backendBaseUrl),
    dataRoot: typeof data.dataRoot === "string" ? data.dataRoot.trim() : fallback.dataRoot,
    preferredFrontendPort:
      Number.isInteger(port) && port >= 0 && port <= 65535 ? port : fallback.preferredFrontendPort,
  };
}

function readLocalConfig(): AppConfig {
  const fallback = defaultConfig();
  if (typeof window === "undefined" || !window.localStorage) return fallback;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? normalizeConfig(JSON.parse(raw), fallback) : fallback;
  } catch {
    return fallback;
  }
}

function writeLocalConfig(config: AppConfig): AppConfig {
  try {
    window.localStorage?.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch {
    // localStorage 不可用（隐私模式等）时静默降级为内存态
  }
  return config;
}

/** 读取配置：桌面走 userData 配置文件，浏览器走 localStorage */
export async function loadConfig(): Promise<AppConfig> {
  const bridge = getDesktopBridge();
  if (!bridge) return readLocalConfig();
  try {
    return normalizeConfig(await bridge.getConfig());
  } catch {
    return defaultConfig();
  }
}

/** 保存配置（局部补丁合并） */
export async function saveConfig(patch: Partial<AppConfig>): Promise<AppConfig> {
  const bridge = getDesktopBridge();
  if (bridge) {
    try {
      return normalizeConfig(await bridge.setConfig(patch as Record<string, unknown>));
    } catch {
      return normalizeConfig({ ...(await loadConfig()), ...patch });
    }
  }
  return writeLocalConfig(normalizeConfig({ ...readLocalConfig(), ...patch }));
}

// ======================== 健康检查 ========================

interface HealthPayload {
  status?: unknown;
  service?: unknown;
}

/** 浏览器态直接 GET <base>/health（后端 CORS 已放行 3300 来源），带短超时，不轮询 */
async function checkBackendInBrowser(baseUrl: string): Promise<BackendStatus> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);
  const checkedAt = Date.now();
  try {
    const response = await fetch(`${baseUrl.replace(/\/+$/, "")}/health`, {
      signal: controller.signal,
      headers: { accept: "application/json" },
    });
    if (!response.ok) {
      return { healthy: false, baseUrl, checkedAt, detail: `HTTP ${response.status}（${baseUrl}/health）` };
    }
    const body = (await response.json()) as HealthPayload;
    const healthy = body?.status === "healthy" && body?.service === "CXO-ModelStation";
    return { healthy, baseUrl, checkedAt, detail: healthy ? undefined : BACKEND_START_HINT };
  } catch (error) {
    return {
      healthy: false,
      baseUrl,
      checkedAt,
      detail: `${error instanceof Error ? error.message : String(error)}。${BACKEND_START_HINT}`,
    };
  } finally {
    clearTimeout(timer);
  }
}

/** 单次健康检查（桌面经主进程 IPC，浏览器直连）；不实现轮询，避免失败请求风暴 */
export async function checkBackend(baseUrl: string): Promise<BackendStatus> {
  const bridge = getDesktopBridge();
  if (bridge) {
    try {
      return await bridge.checkBackend(baseUrl);
    } catch (error) {
      return {
        healthy: false,
        baseUrl,
        checkedAt: Date.now(),
        detail: error instanceof Error ? error.message : String(error),
      };
    }
  }
  return checkBackendInBrowser(baseUrl);
}

export function isDesktopAction(dataRoot: string): boolean {
  return isDesktopRuntime() && dataRoot.trim().length > 0;
}