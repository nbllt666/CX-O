import axios, { AxiosInstance, AxiosError } from 'axios';
import type { AxiosRequestConfig } from 'axios';
import type { RetryConfig } from './_types';

// ── Cached backend / WS URLs ──
export let _cachedBackendUrl: string | null = null;
export let _cachedWsUrl: string | null = null;

export const getApiBaseUrl = () => {
  if (_cachedBackendUrl) return _cachedBackendUrl;
  return localStorage.getItem('cxhms-backend-url') || import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
};
export const getControlServiceUrl = () => localStorage.getItem('cxhms-control-url') || import.meta.env.VITE_CONTROL_SERVICE_URL || 'http://127.0.0.1:8000';
export const getWsBaseUrl = () => {
  if (_cachedWsUrl) return _cachedWsUrl;
  return localStorage.getItem('cxhms-ws-url') || import.meta.env.VITE_WS_URL || httpToWsUrl(getApiBaseUrl());
};
export const getVoiceWorkstationUrl = () => localStorage.getItem('cxhms-voicews-url') || import.meta.env.VITE_VOICE_WS_URL || (import.meta.env.DEV ? '/voice-station' : 'http://127.0.0.1:8200');

export function getWS_BASE_URL() {
  return getWsBaseUrl();
}

/**
 * 将 HTTP(S) base URL 转换为对应的 WS(S) base URL。
 * 通过 new URL().protocol 切换，避免在 base URL 含 "http" 子串时被错误转换。
 */
export const httpToWsUrl = (httpBaseUrl: string): string => {
  try {
    const u = new URL(httpBaseUrl);
    u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return u.toString().replace(/\/$/, '');
  } catch {
    // 解析失败时退化为朴素替换作为兜底
    return httpBaseUrl.replace(/^http/i, httpBaseUrl.startsWith('https') ? 'wss' : 'ws').replace(/\/$/, '');
  }
};

/** Set the cached backend URL and persist to localStorage (and optionally IPC). */
export function setCachedBackendUrl(url: string) {
  _cachedBackendUrl = url;
  localStorage.setItem('cxhms-backend-url', url);
  if (window.electronAPI) {
    window.electronAPI.setBackendUrl(url).catch(() => {});
  }
}

/** Set the cached WS URL and persist to localStorage. */
export function setCachedWsUrl(url: string) {
  _cachedWsUrl = url;
  localStorage.setItem('cxhms-ws-url', url);
}

/**
 * Initialise the backend URL with Electron IPC priority.
 * Priority: Electron IPC > localStorage > env > default
 * Must be called early in the app lifecycle (before first API call).
 */
export async function initBackendUrl(): Promise<string> {
  if (window.electronAPI) {
    try {
      const ipcUrl = await window.electronAPI.getBackendUrl();
      if (ipcUrl) {
        _cachedBackendUrl = ipcUrl;
        localStorage.setItem('cxhms-backend-url', ipcUrl);
        // Auto-derive WS URL from backend URL
        const derivedWs = httpToWsUrl(ipcUrl);
        _cachedWsUrl = derivedWs;
        localStorage.setItem('cxhms-ws-url', derivedWs);
        return ipcUrl;
      }
    } catch {
      // IPC failed, fall through
    }
  }
  const url = localStorage.getItem('cxhms-backend-url') || import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
  _cachedBackendUrl = url;
  // Also cache WS URL
  if (!_cachedWsUrl) {
    _cachedWsUrl = localStorage.getItem('cxhms-ws-url') || import.meta.env.VITE_WS_URL || httpToWsUrl(url);
  }
  return url;
}

export const getApiUrl = () => getApiBaseUrl();
export const getControlUrl = () => getControlServiceUrl();
export const getVoiceWorkstationUrlFn = () => getVoiceWorkstationUrl();

export class _ApiClientBase {
  private _client: AxiosInstance | null = null;
  private _clientBaseUrl: string | null = null;
  private _controlClient: AxiosInstance | null = null;
  private _controlClientBaseUrl: string | null = null;
  private _voiceWorkstationClient: AxiosInstance | null = null;
  private _voiceWorkstationClientBaseUrl: string | null = null;

  get client(): AxiosInstance {
    const baseUrl = getApiBaseUrl();
    if (!this._client || this._clientBaseUrl !== baseUrl) {
      this._client = axios.create({
        baseURL: baseUrl,
        timeout: 30000,
        headers: {
          'Content-Type': 'application/json',
        },
      });
      this._setupInterceptors(this._client);
      this._clientBaseUrl = baseUrl;
    }
    return this._client;
  }

  private get controlClient(): AxiosInstance {
    const baseUrl = getControlServiceUrl();
    if (!this._controlClient || this._controlClientBaseUrl !== baseUrl) {
      this._controlClient = axios.create({
        baseURL: baseUrl,
        timeout: 30000,
        headers: {
          'Content-Type': 'application/json',
        },
      });
      this._setupInterceptors(this._controlClient);
      this._controlClientBaseUrl = baseUrl;
    }
    return this._controlClient;
  }

  get voiceWorkstationClient(): AxiosInstance {
    const baseUrl = getVoiceWorkstationUrl();
    if (!this._voiceWorkstationClient || this._voiceWorkstationClientBaseUrl !== baseUrl) {
      this._voiceWorkstationClient = axios.create({
        baseURL: baseUrl,
        timeout: 60000,
        headers: {
          'Content-Type': 'application/json',
        },
      });
      this._setupInterceptors(this._voiceWorkstationClient);
      this._voiceWorkstationClientBaseUrl = baseUrl;
    }
    return this._voiceWorkstationClient;
  }

  private maxRetries: number = 3;
  private retryDelay: number = 1000;
  private cacheMaxEntries: number = 100;
  private cache: Map<string, { data: unknown; timestamp: number; ttl: number }>;

  constructor() {
    this.cache = new Map();
  }

  private _getCacheKey(url: string, params?: Record<string, unknown>): string {
    return `${url}?${this._stableStringify(params || {})}`;
  }

  /**
   * 稳定的 JSON 序列化：按 key 排序、移除 undefined 值，
   * 避免参数对象 key 顺序或 undefined 字段差异导致缓存 key 不一致。
   */
  private _stableStringify(value: unknown): string {
    const seen = new WeakSet<object>();
    const stringify = (v: unknown): string => {
      if (v === null || typeof v !== 'object') {
        return JSON.stringify(v ?? null);
      }
      if (seen.has(v as object)) {
        return '"[Circular]"';
      }
      seen.add(v as object);
      if (Array.isArray(v)) {
        return '[' + v.map((item) => stringify(item)).join(',') + ']';
      }
      const obj = v as Record<string, unknown>;
      const keys = Object.keys(obj)
        .filter((k) => obj[k] !== undefined)
        .sort();
      return (
        '{' +
        keys
          .map((k) => JSON.stringify(k) + ':' + stringify(obj[k]))
          .join(',') +
        '}'
      );
    };
    return stringify(value);
  }

  private _getFromCache(key: string): unknown | null {
    const cached = this.cache.get(key);
    if (!cached) return null;

    if (Date.now() - cached.timestamp > cached.ttl) {
      this.cache.delete(key);
      return null;
    }

    // 命中后刷新 LRU 顺序
    this.cache.delete(key);
    this.cache.set(key, cached);
    return cached.data;
  }

  private _setCache(key: string, data: unknown, ttl: number = 60000): void {
    if (this.cache.has(key)) {
      this.cache.delete(key);
    }
    this.cache.set(key, {
      data,
      timestamp: Date.now(),
      ttl,
    });
    // 超过容量上限时淘汰最早写入的条目
    while (this.cache.size > this.cacheMaxEntries) {
      const oldestKey = this.cache.keys().next().value;
      if (oldestKey === undefined) break;
      this.cache.delete(oldestKey);
    }
  }

  /**
   * 精确匹配清除缓存。
   * pattern 视为 URL 路径段：仅当 key 中的 path 与 pattern 相等或以 `${pattern}/`、
   * `${pattern}?` 开头时匹配；避免 `agents` 误伤 `listAgents`、`agents/123` 之外的键。
   */
  _clearCache(pattern?: string): void {
    if (pattern) {
      for (const key of this.cache.keys()) {
        const path = key.split('?', 1)[0];
        if (
          path === pattern ||
          path.startsWith(`${pattern}/`) ||
          path.startsWith(`${pattern}?`)
        ) {
          this.cache.delete(key);
        }
      }
    } else {
      this.cache.clear();
    }
  }

  private _setupInterceptors(axiosInstance: AxiosInstance) {
    axiosInstance.interceptors.request.use(
      (config) => {
        const token = localStorage.getItem('cxhms-token');
        if (token) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    axiosInstance.interceptors.response.use(
      (response) => response,
      async (error: AxiosError) => {
        const config = error.config as RetryConfig;
        if (!config) {
          return Promise.reject(error);
        }

        // BUG-F46: 仅对 network error / 5xx / 408 / 429 触发重试，其他 4xx 不重试
        if (!this._shouldRetry(error)) {
          return Promise.reject(error);
        }

        const retryCount = (config.retryCount || 0) + 1;
        if (retryCount > this.maxRetries) {
          return Promise.reject(error);
        }
        config.retryCount = retryCount;

        // BUG-F47: 重试延迟支持 AbortController，提前检查 abort 状态
        const signal = (config.signal as AbortSignal | undefined) ?? undefined;
        if (signal?.aborted) {
          return Promise.reject(error);
        }

        try {
          await this._sleepWithAbort(this.retryDelay * retryCount, signal);
        } catch (abortErr) {
          return Promise.reject(abortErr);
        }

        if (signal?.aborted) {
          return Promise.reject(error);
        }

        return axiosInstance(config);
      }
    );
  }

  /**
   * 判断是否应当重试：仅对网络层错误或服务端临时错误（5xx / 408 / 429）触发。
   * 其他 4xx 错误（401/403/404/422 等）不重试，避免无意义的重试开销。
   */
  private _shouldRetry(error: AxiosError): boolean {
    // 网络错误：没有 response
    if (!error.response) {
      return true;
    }
    const status = error.response.status;
    if (status >= 500 && status < 600) return true;
    if (status === 408) return true; // Request Timeout
    if (status === 429) return true; // Too Many Requests
    return false;
  }

  /**
   * 带 abort 感知的 sleep：支持在等待期间被 AbortController 取消。
   */
  private _sleepWithAbort(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException('Aborted', 'AbortError'));
        return;
      }
      const timer = setTimeout(() => {
        if (signal && onAbort) {
          signal.removeEventListener('abort', onAbort);
        }
        resolve();
      }, ms);
      const onAbort = () => {
        clearTimeout(timer);
        reject(new DOMException('Aborted', 'AbortError'));
      };
      if (signal) {
        signal.addEventListener('abort', onAbort, { once: true });
      }
    });
  }

  async request<T>(config: AxiosRequestConfig, useCache: boolean = false): Promise<T> {
    const cacheKey = this._getCacheKey(config.url || '', config.params as Record<string, unknown>);
    const isGet = (config.method || 'get').toLowerCase() === 'get';

    if (useCache && isGet) {
      const cached = this._getFromCache(cacheKey);
      if (cached) return cached as T;
    }

    try {
      const axiosInstance = this.client;
      const response = await axiosInstance.request<T>(config);

      if (useCache && isGet) {
        this._setCache(cacheKey, response.data);
      }

      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  async controlRequest<T>(config: AxiosRequestConfig): Promise<T> {
    try {
      const axiosInstance = this.controlClient;
      const response = await axiosInstance.request<T>(config);
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  async voiceWorkstationRequest<T>(config: AxiosRequestConfig): Promise<T> {
    try {
      const axiosInstance = this.voiceWorkstationClient;
      const response = await axiosInstance.request<T>(config);
      return response.data;
    } catch (error) {
      throw this._handleError(error);
    }
  }

  private _handleError(error: unknown): Error {
    if (error instanceof AxiosError) {
      if (error.response) {
        const message = (error.response.data as { message?: string })?.message || error.response.statusText;
        return new Error(`请求失败: ${message}`);
      } else if (error.request) {
        return new Error('无法连接到服务器，请检查后端服务是否启动');
      }
    }
    return error instanceof Error ? error : new Error('未知错误');
  }
}
