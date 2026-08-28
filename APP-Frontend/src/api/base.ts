/**
 * API 基座：axios 实例工厂、错误归一化、超时与重试、后端地址解析。
 *
 * 后端地址解析优先级（HTTP）：
 *   1. Electron IPC config:get-backend-url（initBackendUrl() 启动时解析一次并缓存）
 *   2. localStorage `cxo-backend-url`
 *   3. import.meta.env.VITE_API_URL
 *   4. 默认 http://127.0.0.1:8000
 *
 * WS 地址解析优先级：
 *   1. IPC 持久化（initBackendUrl 时从 app-config 同步到 localStorage 的 cxo-ws-url）
 *   2. localStorage `cxo-ws-url`
 *   3. import.meta.env.VITE_WS_URL
 *   4. 由 HTTP 地址推导（http→ws、https→wss）
 *
 * setBackendUrl() 运行时更新：写缓存 + localStorage + IPC 持久化。
 */
import axios, { AxiosError } from 'axios';
import type { AxiosInstance, AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';

// F3: 与主进程 ensureDefaultConfig 默认一致（8000），避免浏览器/桌面端默认端口分叉。
export const DEFAULT_BACKEND_URL = 'http://127.0.0.1:8000';
export const DEFAULT_VOICE_WS_URL = 'http://127.0.0.1:8200';

export const STORAGE_KEYS = {
  backendUrl: 'cxo-backend-url',
  wsUrl: 'cxo-ws-url',
  voiceWsUrl: 'cxo-voicews-url',
  controlUrl: 'cxo-control-url',
  token: 'cxo-token',
  /** 管理面 x-api-key（与后端 ADMIN_API_KEY 对齐；C5/C10 鉴权端点调用需携带） */
  adminKey: 'cxo-admin-key',
  offlineTimeout: 'cxo-offline-timeout',
} as const;

// ── 缓存的后端 / WS 地址（initBackendUrl / setBackendUrl 写入） ──
let cachedBackendUrl: string | null = null;
let cachedWsUrl: string | null = null;

export function getApiBaseUrl(): string {
  if (cachedBackendUrl) return cachedBackendUrl;
  return (
    localStorage.getItem(STORAGE_KEYS.backendUrl) ||
    import.meta.env.VITE_API_URL ||
    DEFAULT_BACKEND_URL
  );
}

export function getWsBaseUrl(): string {
  if (cachedWsUrl) return cachedWsUrl;
  return (
    localStorage.getItem(STORAGE_KEYS.wsUrl) ||
    import.meta.env.VITE_WS_URL ||
    httpToWsUrl(getApiBaseUrl())
  );
}

export function getVoiceWorkstationUrl(): string {
  return (
    localStorage.getItem(STORAGE_KEYS.voiceWsUrl) ||
    import.meta.env.VITE_VOICE_WS_URL ||
    DEFAULT_VOICE_WS_URL
  );
}

/**
 * 将 HTTP(S) base URL 转换为对应的 WS(S) base URL。
 * 通过 URL.protocol 切换，避免 base URL 含 "http" 子串时被错误替换。
 */
export function httpToWsUrl(httpBaseUrl: string): string {
  try {
    const u = new URL(httpBaseUrl);
    u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return u.toString().replace(/\/$/, '');
  } catch {
    // 解析失败时退化为朴素替换兜底
    return httpBaseUrl
      .replace(/^http/i, httpBaseUrl.startsWith('https') ? 'wss' : 'ws')
      .replace(/\/$/, '');
  }
}

/** 运行时更新后端地址：写缓存 + localStorage +（Electron 下）IPC 持久化 */
export function setBackendUrl(url: string): void {
  cachedBackendUrl = url;
  localStorage.setItem(STORAGE_KEYS.backendUrl, url);
  // WS 地址未显式设置时跟随 HTTP 推导
  if (!localStorage.getItem(STORAGE_KEYS.wsUrl)) {
    cachedWsUrl = httpToWsUrl(url);
  }
  if (window.electronAPI) {
    window.electronAPI.setBackendUrl(url).catch(() => {});
  }
}

/** 运行时显式更新 WS 地址（独立于 HTTP 推导链） */
export function setWsUrl(url: string): void {
  cachedWsUrl = url;
  localStorage.setItem(STORAGE_KEYS.wsUrl, url);
}

/**
 * 启动时解析后端地址（必须在首次 API 调用前 await）。
 * 优先级：Electron IPC > localStorage > env > 默认。
 */
export async function initBackendUrl(): Promise<string> {
  if (window.electronAPI) {
    try {
      const ipcUrl = await window.electronAPI.getBackendUrl();
      if (ipcUrl) {
        cachedBackendUrl = ipcUrl;
        localStorage.setItem(STORAGE_KEYS.backendUrl, ipcUrl);
        // WS：localStorage 已有显式值（含 IPC app-config 同步来的）则保留，否则由 HTTP 推导
        const storedWs = localStorage.getItem(STORAGE_KEYS.wsUrl);
        cachedWsUrl = storedWs || import.meta.env.VITE_WS_URL || httpToWsUrl(ipcUrl);
        return ipcUrl;
      }
    } catch {
      // IPC 失败则落到常规链
    }
  }
  const url =
    localStorage.getItem(STORAGE_KEYS.backendUrl) ||
    import.meta.env.VITE_API_URL ||
    DEFAULT_BACKEND_URL;
  cachedBackendUrl = url;
  if (!cachedWsUrl) {
    cachedWsUrl =
      localStorage.getItem(STORAGE_KEYS.wsUrl) ||
      import.meta.env.VITE_WS_URL ||
      httpToWsUrl(url);
  }
  return url;
}

// ── 重试配置 ──

interface RetryConfig extends InternalAxiosRequestConfig {
  retryCount?: number;
  /** 非幂等方法显式声明可自动重试（默认 POST 等写方法不重试，避免重复投递） */
  retryable?: boolean;
}

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

/** 自动重试方法白名单：仅幂等方法；网络错误重试不会造成重复投递副作用 */
const RETRYABLE_METHODS = new Set(['get', 'head']);

/**
 * 重试判定：仅白名单方法（GET/HEAD，或声明 retryable===true 的请求）在
 * 网络错误 / 5xx / 408 / 429 时触发重试，其余 4xx 不重试。
 */
export function shouldRetry(error: AxiosError): boolean {
  const config = error.config as RetryConfig | undefined;
  const method = (config?.method ?? '').toLowerCase();
  const methodAllowed = RETRYABLE_METHODS.has(method) || config?.retryable === true;
  if (!methodAllowed) return false; // POST 等写方法：重复投递有副作用，默认不重试
  if (!error.response) return true;
  const status = error.response.status;
  return (status >= 500 && status < 600) || status === 408 || status === 429;
}

function sleepWithAbort(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    };
    signal?.addEventListener('abort', onAbort, { once: true });
  });
}

function setupInterceptors(instance: AxiosInstance): void {
  instance.interceptors.request.use((config) => {
    const token = localStorage.getItem(STORAGE_KEYS.token);
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // C5/C10: 后端鉴权端点（live disconnect / discovery / config 写路径等）要求
    // x-api-key 头；localStorage 配置了管理密钥时统一注入，与 Bearer token 同口径。
    const adminKey = localStorage.getItem(STORAGE_KEYS.adminKey);
    if (adminKey) {
      config.headers['x-api-key'] = adminKey;
    }
    return config;
  });

  instance.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
      const config = error.config as RetryConfig | undefined;
      if (!config || !shouldRetry(error)) {
        return Promise.reject(error);
      }
      const retryCount = (config.retryCount ?? 0) + 1;
      if (retryCount > MAX_RETRIES) {
        return Promise.reject(error);
      }
      config.retryCount = retryCount;

      const signal = (config.signal as AbortSignal | undefined) ?? undefined;
      if (signal?.aborted) {
        return Promise.reject(error);
      }
      try {
        await sleepWithAbort(RETRY_DELAY_MS * retryCount, signal);
      } catch (abortErr) {
        return Promise.reject(abortErr);
      }
      if (signal?.aborted) {
        return Promise.reject(error);
      }
      return instance(config);
    },
  );
}

// ── axios 实例缓存（base URL 变化时重建） ──

let httpClient: AxiosInstance | null = null;
let httpClientBaseUrl: string | null = null;
let voiceWsClient: AxiosInstance | null = null;
let voiceWsClientBaseUrl: string | null = null;

/** 主后端 axios 实例（30s 超时） */
export function getHttpClient(): AxiosInstance {
  const baseUrl = getApiBaseUrl();
  if (!httpClient || httpClientBaseUrl !== baseUrl) {
    httpClient = axios.create({
      baseURL: baseUrl,
      timeout: 30000,
      headers: { 'Content-Type': 'application/json' },
    });
    setupInterceptors(httpClient);
    httpClientBaseUrl = baseUrl;
  }
  return httpClient;
}

/** 音频工作站 axios 实例（60s 超时，独立服务地址） */
export function getVoiceWsClient(): AxiosInstance {
  const baseUrl = getVoiceWorkstationUrl();
  if (!voiceWsClient || voiceWsClientBaseUrl !== baseUrl) {
    voiceWsClient = axios.create({
      baseURL: baseUrl,
      timeout: 60000,
      headers: { 'Content-Type': 'application/json' },
    });
    setupInterceptors(voiceWsClient);
    voiceWsClientBaseUrl = baseUrl;
  }
  return voiceWsClient;
}

// ── 错误归一化 ──

export function normalizeError(error: unknown): Error {
  if (error instanceof AxiosError) {
    if (error.response) {
      // 错误信息回退链：依次尝试后端常见错误字段，全部缺失时退回 statusText
      const data = error.response.data as {
        message?: string;
        error?: string;
        error_message?: string;
        detail?: string;
      } | undefined;
      const message =
        data?.message ||
        data?.error ||
        data?.error_message ||
        data?.detail ||
        error.response.statusText;
      return new Error(`请求失败: ${message}`);
    }
    if (error.request) {
      return new Error('无法连接到服务器，请检查后端服务是否启动');
    }
  }
  return error instanceof Error ? error : new Error('未知错误');
}

// ── GET 缓存（LRU，默认 60s TTL，上限 100 条） ──

const CACHE_MAX_ENTRIES = 100;
const cache = new Map<string, { data: unknown; timestamp: number; ttl: number }>();

/** 稳定序列化：key 排序 + 剔除 undefined，保证缓存 key 一致 */
function stableStringify(value: unknown): string {
  const seen = new WeakSet<object>();
  const stringify = (v: unknown): string => {
    if (v === null || typeof v !== 'object') {
      return JSON.stringify(v ?? null);
    }
    if (seen.has(v as object)) return '"[Circular]"';
    seen.add(v as object);
    if (Array.isArray(v)) {
      return '[' + v.map((item) => stringify(item)).join(',') + ']';
    }
    const obj = v as Record<string, unknown>;
    const keys = Object.keys(obj)
      .filter((k) => obj[k] !== undefined)
      .sort();
    return '{' + keys.map((k) => JSON.stringify(k) + ':' + stringify(obj[k])).join(',') + '}';
  };
  return stringify(value);
}

function getCacheKey(url: string, params?: Record<string, unknown>): string {
  return `${url}?${stableStringify(params ?? {})}`;
}

function getFromCache(key: string): unknown | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (Date.now() - entry.timestamp > entry.ttl) {
    cache.delete(key);
    return null;
  }
  // 命中后刷新 LRU 顺序
  cache.delete(key);
  cache.set(key, entry);
  return entry.data;
}

function setCache(key: string, data: unknown, ttl = 60000): void {
  cache.delete(key);
  cache.set(key, { data, timestamp: Date.now(), ttl });
  while (cache.size > CACHE_MAX_ENTRIES) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) break;
    cache.delete(oldestKey);
  }
}

/**
 * 精确匹配清除缓存：pattern 视为 URL 路径段，
 * 仅当 key 的 path 与 pattern 相等或以 `${pattern}/`、`${pattern}?` 开头时匹配。
 */
export function clearApiCache(pattern?: string): void {
  if (!pattern) {
    cache.clear();
    return;
  }
  for (const key of cache.keys()) {
    const path = key.split('?', 1)[0];
    if (path === pattern || path.startsWith(`${pattern}/`) || path.startsWith(`${pattern}?`)) {
      cache.delete(key);
    }
  }
}

// ── 统一请求入口 ──

/** 主后端请求：自动错误归一化；GET 可选用 LRU 缓存 */
export async function request<T>(config: AxiosRequestConfig, useCache = false): Promise<T> {
  const cacheKey = getCacheKey(config.url ?? '', config.params as Record<string, unknown>);
  const isGet = (config.method ?? 'get').toLowerCase() === 'get';

  if (useCache && isGet) {
    const cached = getFromCache(cacheKey);
    if (cached !== null) return cached as T;
  }

  try {
    const response = await getHttpClient().request<T>(config);
    if (useCache && isGet) {
      setCache(cacheKey, response.data);
    }
    return response.data;
  } catch (error) {
    throw normalizeError(error);
  }
}

/** 音频工作站请求（独立服务地址） */
export async function voiceWorkstationRequest<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    const response = await getVoiceWsClient().request<T>(config);
    return response.data;
  } catch (error) {
    throw normalizeError(error);
  }
}
