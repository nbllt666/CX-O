import axios, { AxiosInstance, AxiosError } from 'axios';
import type { AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';

// ── Cached backend / WS URLs ──
let _cachedBackendUrl: string | null = null;
let _cachedWsUrl: string | null = null;

const getApiBaseUrl = () => {
  if (_cachedBackendUrl) return _cachedBackendUrl;
  return localStorage.getItem('cxhms-backend-url') || import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000';
};
const getControlServiceUrl = () => localStorage.getItem('cxhms-control-url') || import.meta.env.VITE_CONTROL_SERVICE_URL || 'http://127.0.0.1:8000';
const getWsBaseUrl = () => {
  if (_cachedWsUrl) return _cachedWsUrl;
  return localStorage.getItem('cxhms-ws-url') || import.meta.env.VITE_WS_URL || httpToWsUrl(getApiBaseUrl());
};
const getVoiceWorkstationUrl = () => localStorage.getItem('cxhms-voicews-url') || import.meta.env.VITE_VOICE_WS_URL || (import.meta.env.DEV ? '/voice-station' : 'http://127.0.0.1:8200');

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

interface RetryConfig extends InternalAxiosRequestConfig {
  retryCount?: number;
}

export interface Agent {
  id: string;
  name: string;
  description?: string;
  is_default?: boolean;
  model?: string;
  memory_scene?: string;
  tools?: string[];
  capabilities?: string[];
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  use_memory?: boolean;
  use_tools?: boolean;
  decay_model?: string;
  vision_enabled?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface HealthStatus {
  status: string;
  version?: string;
  components?: Record<string, boolean>;
  timestamp?: string;
  database?: { status: string };
  memory?: { status: string };
  vector_store?: { status: string };
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  graph_enabled: boolean;
  avg_degree?: number;
  graph_density?: number;
  node_types?: string[];
  edge_types?: string[];
  connected?: boolean;
  libraries?: Record<string, { entity_count: number; relation_count: number }>;
}

export interface AcpStats {
  total_agents: number;
  active_agents: number;
  total_messages: number;
  total_conversations?: number;
  avg_response_time?: number;
}

export interface AcpAgentRow {
  id: string;
  name: string;
  description?: string;
  capabilities?: string[];
  status?: string;
}

export interface ArchiveStats {
  total_memories: number;
  archived_memories: number;
  active_memories: number;
  total_archived?: number;
  merge_count?: number;
  duplicate_count?: number;
  archive_level_counts?: Record<string, number>;
}

export interface ToolStats {
  total_tools: number;
  enabled_tools: number;
  builtin_tools: number;
  custom_tools: number;
  active_tools?: number;
  mcp_tools?: number;
  total_calls?: number;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  type: 'builtin' | 'custom' | 'mcp' | 'cxfc';
  status: 'active' | 'inactive' | 'error';
  config: Record<string, unknown>;
  icon?: string;
  created_at: string;
  last_used?: string;
  use_count: number;
  parameters?: Record<string, unknown>;
  examples?: string[];
  tags?: string[];
  source_plugin_id?: string;
}

export interface CxfcPlugin {
  plugin_id: string;
  host: string;
  port: number;
  name?: string;
  version?: string;
  capabilities: string[];
  status: 'connected' | 'disconnected';
  last_seen?: string | null;
  tools: Array<{ name: string; description?: string }>;
  skills: Array<{ name: string; description?: string }>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface CxfcSkill {
  name: string;
  description?: string;
  prompt_template?: string;
  trigger_keywords: string[];
  trigger_events: string[];
  auto_inject: boolean;
  source_plugin_id: string;
}

export interface CxfcDiscoveredPlugin {
  host: string;
  port: number;
  name?: string;
  capabilities: string[];
  version?: string;
}

export interface FrontendLimits {
  max_upload_size_mb: number;
  max_chat_images: number;
  avatar_min_width: number;
  avatar_max_width: number;
  temperature_max: number;
  speed_max: number;
}

export interface GraphEntity {
  id: string;
  type: string;
  name?: string;
  properties?: Record<string, unknown>;
  created_at?: string;
}

export interface GraphRelation {
  id: string;
  type: string;
  source_id: string;
  target_id: string;
  properties?: Record<string, unknown>;
  created_at?: string;
}

export interface VectorData {
  memory_id: number;
  content: string;
  memory_type: string;
  importance: number;
  created_at: string;
  has_vector: boolean;
}

export interface DuplicateGroup {
  group_id: string;
  memory_ids: number[];
  canonical_id: number;
  similarity_matrix: Record<string, number>;
}

export interface ArchiveResult {
  archived_count: number;
  merged_count: number;
  errors?: string[];
  results?: {
    archived?: unknown[];
    merged?: unknown[];
  };
}

export interface Memory {
  id: number;
  content: string;
  type: string;
  importance: number;
  tags: string[];
  created_at: string;
  is_archived: boolean;
  archived_at?: string;
  emotion_score?: number;
  metadata?: Record<string, unknown>;
}

export interface Session {
  id: string;
  title: string;
  agent_id: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
  session_id?: string;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

class ApiClient {
  private _client: AxiosInstance | null = null;
  private _clientBaseUrl: string | null = null;
  private _controlClient: AxiosInstance | null = null;
  private _controlClientBaseUrl: string | null = null;
  private _voiceWorkstationClient: AxiosInstance | null = null;
  private _voiceWorkstationClientBaseUrl: string | null = null;

  private get client(): AxiosInstance {
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

  private get voiceWorkstationClient(): AxiosInstance {
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
  private _clearCache(pattern?: string): void {
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

  async getHealth(): Promise<HealthStatus> {
    return this.request<HealthStatus>({ url: '/health' });
  }

  async getGraphHealth(): Promise<{ connected: boolean; message?: string }> {
    return this.request<{ connected: boolean; message?: string }>({ url: '/api/graph/health' });
  }

  async getGraphStats(): Promise<GraphStats> {
    return this.request<GraphStats>({ url: '/api/graph/stats' });
  }

  async testGraphConnection(): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>({ url: '/api/graph/test' });
  }

  async getAgents(): Promise<Agent[]> {
    const response = await this.request<{ status: string; agents: Agent[]; total: number }>({ url: '/api/agents' }, true);
    return response.agents || [];
  }

  async getAgent(agentId: string): Promise<Agent> {
    const response = await this.request<{ status: string; agent: Agent }>({ url: `/api/agents/${agentId}` });
    return response.agent;
  }

  async createAgent(data: Partial<Agent>): Promise<Agent> {
    const response = await this.request<{ status: string; agent: Agent; message: string }>({ url: '/api/agents', method: 'post', data });
    this._clearCache('/api/agents');
    return response.agent;
  }

  async updateAgent(agentId: string, data: Partial<Agent>): Promise<Agent> {
    const response = await this.request<{ status: string; agent: Agent; message: string }>({ url: `/api/agents/${agentId}`, method: 'put', data });
    this._clearCache('/api/agents');
    return response.agent;
  }

  async deleteAgent(agentId: string): Promise<void> {
    await this.request<{ status: string; message: string }>({ url: `/api/agents/${agentId}`, method: 'delete' });
    this._clearCache('/api/agents');
  }

  async cloneAgent(agentId: string): Promise<Agent> {
    const response = await this.request<{ status: string; agent: Agent; message: string }>({ url: `/api/agents/${agentId}/clone`, method: 'post' });
    return response.agent;
  }

  async getAvailableModels(): Promise<{ models: string[] }> {
    return this.request<{ models: string[] }>({ url: '/api/models' });
  }

  async getConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/config' });
  }

  async getLimits(): Promise<FrontendLimits> {
    try {
      return await this.request<FrontendLimits>({ url: '/api/config/limits' });
    } catch {
      return {
        max_upload_size_mb: 500,
        max_chat_images: 20,
        avatar_min_width: 100,
        avatar_max_width: 1200,
        temperature_max: 5,
        speed_max: 3,
      };
    }
  }

  async updateConfig(section: string, data: Record<string, unknown>): Promise<void> {
    await this.request({ url: '/api/config', method: 'put', data: { section, data } });
    this._clearCache();
  }

  async sendMessage(message: string, agentId: string = 'default', sessionId?: string): Promise<{ response: string; session_id: string }> {
    const response = await this.request<{ status: string; response: string; session_id: string }>({
      url: '/api/chat',
      method: 'post',
      data: { message, agent_id: agentId, session_id: sessionId }
    });
    return { response: response.response, session_id: response.session_id };
  }

  async getChatHistory(agentId: string = 'default'): Promise<{ messages: ChatMessage[] }> {
    const sessionId = `agent-${agentId}`;
    const response = await this.request<{ status: string; messages: ChatMessage[] }>({ url: `/api/chat/history/${sessionId}` });
    return { messages: response.messages || [] };
  }

  async createSession(title: string, agentId: string = 'default'): Promise<Session> {
    return this.request<Session>({ url: '/api/context/sessions', method: 'post', data: { title, agent_id: agentId } });
  }

  async getSessions(): Promise<Session[]> {
    const response = await this.request<{ status: string; sessions: Session[]; total: number }>({ url: '/api/context/sessions' });
    return response.sessions || [];
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request({ url: `/api/context/sessions/${sessionId}`, method: 'delete' });
  }

  async getMemories(params?: {
    type?: string;
    memory_type?: string;
    limit?: number;
    offset?: number;
    agent_id?: string;
  }): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({
      url: '/api/memories',
      method: 'get',
      params
    });
  }

  async getAgentMemoryTables(): Promise<{ agents: { agent_id: string; table_name: string; created_at: string }[] }> {
    return this.request<{ agents: { agent_id: string; table_name: string; created_at: string }[] }>({ url: '/api/memories/agents' });
  }

  async createMemory(data: {
    content: string;
    type?: string;
    importance?: number;
    tags?: string[];
    agent_id?: string;
  }): Promise<Memory> {
    return this.request<Memory>({ url: '/api/memories', method: 'post', data });
  }

  async updateMemory(memoryId: number, data: Partial<Memory>): Promise<Memory> {
    return this.request<Memory>({ url: `/api/memories/${memoryId}`, method: 'put', data });
  }

  async deleteMemory(memoryId: number, softDelete: boolean = true): Promise<void> {
    await this.request({ url: `/api/memories/${memoryId}`, method: 'delete', params: { soft: softDelete } });
  }

  async archiveMemory(memoryId: number, targetLevel: number = 1): Promise<void> {
    await this.request({ url: '/api/archive/memory', method: 'post', data: { memory_id: memoryId, target_level: targetLevel } });
  }

  async searchMemories(query: string): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({ url: '/api/memories/search', method: 'post', data: { query } });
  }

  async semanticSearch(query: string, options?: { limit?: number; min_score?: number }): Promise<{ results: Memory[] }> {
    return this.request<{ results: Memory[] }>({ url: '/api/memories/semantic-search', method: 'post', data: { query, ...options } });
  }

  async getMemoriesByType(type: string, params?: { limit?: number }): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({ url: `/api/memories/type/${type}`, params });
  }

  async searchByTag(tag: string, params?: { limit?: number }): Promise<{ memories: Memory[] }> {
    return this.request<{ memories: Memory[] }>({ url: '/api/memories/tag', method: 'post', data: { tag, ...params } });
  }

  async batchDeleteMemories(memoryIds: number[]): Promise<void> {
    await this.request({ url: '/api/memories/batch-delete', method: 'post', data: { ids: memoryIds } });
  }

  async batchUpdateTags(memoryIds: number[], tags: string[], operation: 'add' | 'remove' | 'set'): Promise<void> {
    await this.request({ url: '/api/memories/batch-update-tags', method: 'post', data: { ids: memoryIds, tags, operation } });
  }

  async batchArchiveMemories(memoryIds: number[]): Promise<void> {
    await this.request({ url: '/api/memories/batch-archive', method: 'post', data: { ids: memoryIds } });
  }

  async batchRestoreMemories(memoryIds: number[]): Promise<void> {
    await this.request({ url: '/api/memories/batch-restore', method: 'post', data: { ids: memoryIds } });
  }

  async batchUpdateMemories(memoryIds: number[], updates: Partial<Memory>): Promise<void> {
    await this.request({ url: '/api/memories/batch-update', method: 'post', data: { ids: memoryIds, updates } });
  }

  async batchTagByQuery(query: string, tags: string[], operation: 'add' | 'remove' | 'set'): Promise<{ updated: number }> {
    return this.request<{ updated: number }>({ url: '/api/memories/batch-tag-by-query', method: 'post', data: { query, tags, operation } });
  }

  async batchDeleteByQuery(query: string): Promise<{ deleted: number }> {
    return this.request<{ deleted: number }>({ url: '/api/memories/batch-delete-by-query', method: 'post', data: { query } });
  }

  async batchArchiveByQuery(query: string, targetLevel: number = 1): Promise<{ archived: number }> {
    return this.request<{ archived: number }>({ url: '/api/memories/batch-archive-by-query', method: 'post', data: { query, target_level: targetLevel } });
  }

  async memoryChat(message: string, sessionId: string): Promise<{ response: string }> {
    return this.request<{ response: string }>({ url: '/api/memory-chat', method: 'post', data: { message, session_id: sessionId } });
  }

  async getStats(): Promise<{
    total_memories: number;
    total_sessions: number;
    total_agents: number;
    archived_memories: number;
  }> {
    return this.request<{
      total_memories: number;
      total_sessions: number;
      total_agents: number;
      archived_memories: number;
    }>({ url: '/api/stats' });
  }

  async getArchiveStats(): Promise<ArchiveStats> {
    const response = await this.request<{ status?: string; statistics: ArchiveStats }>({ url: '/api/archive/stats' });
    return response.statistics;
  }

  async mergeMemories(memoryIds: number[]): Promise<{ success: boolean; merged_memory_id?: number }> {
    return this.request<{ success: boolean; merged_memory_id?: number }>({ url: '/api/archive/merge', method: 'post', data: { memory_ids: memoryIds } });
  }

  async detectDuplicates(): Promise<{ duplicate_groups: DuplicateGroup[] }> {
    return this.request<{ duplicate_groups: DuplicateGroup[] }>({ url: '/api/archive/deduplicate', method: 'post', data: {} });
  }

  async autoArchiveProcess(): Promise<ArchiveResult> {
    return this.request<ArchiveResult>({ url: '/api/archive/auto-process', method: 'post' });
  }

  async getTools(filter?: string): Promise<{ tools: Record<string, Tool> }> {
    return this.request<{ tools: Record<string, Tool> }>({ url: '/api/tools', params: filter ? { category: filter } : undefined });
  }

  async getToolsStats(): Promise<ToolStats> {
    const response = await this.request<{ status?: string; statistics: ToolStats }>({ url: '/api/tools/stats' });
    return response.statistics;
  }

  async deleteTool(toolId: string): Promise<void> {
    await this.request({ url: `/api/tools/${toolId}`, method: 'delete' });
  }

  async testTool(toolId: string, params?: Record<string, unknown>): Promise<{ result: Record<string, unknown> }> {
    return this.request<{ result: Record<string, unknown> }>({ url: `/api/tools/${toolId}/test`, method: 'post', data: params });
  }

  async getAcpStats(): Promise<AcpStats> {
    const response = await this.request<{ status?: string; statistics: Record<string, number> }>({ url: '/api/acp/stats' });
    const stats = response.statistics || {};
    return {
      total_agents: stats.total_agents ?? 0,
      active_agents: stats.online_agents ?? stats.active_agents ?? 0,
      total_messages: stats.total_messages ?? 0,
      total_conversations: stats.total_messages ?? 0,
    };
  }

  async getAcpAgents(): Promise<AcpAgentRow[]> {
    const response = await this.request<{ status?: string; agents: AcpAgentRow[] }>({ url: '/api/acp/agents' });
    return response.agents || [];
  }

  async createAcpAgent(data: { name: string; description?: string; capabilities?: string[] }): Promise<AcpAgentRow> {
    return this.request<AcpAgentRow>({
      url: '/api/acp/agents',
      method: 'post',
      data: {
        name: data.name,
        description: data.description ?? '',
        capabilities: data.capabilities ?? [],
        host: '127.0.0.1',
        port: 0,
      },
    });
  }

  async updateAcpAgent(agentId: string, data: Record<string, unknown>): Promise<AcpAgentRow> {
    return this.request<AcpAgentRow>({ url: `/api/acp/agents/${agentId}`, method: 'patch', data });
  }

  async deleteAcpAgent(agentId: string): Promise<void> {
    await this.request({ url: `/api/acp/agents/${agentId}`, method: 'delete' });
  }

  async getServiceStatus(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/status' });
  }

  async startService(data?: { port?: number }): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/start', method: 'post', data });
  }

  async stopService(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/stop', method: 'post' });
  }

  async restartService(data?: { port?: number }): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/restart', method: 'post', data });
  }

  async getServiceLogs(lines: number = 50): Promise<{ logs: string }> {
    return this.request<{ logs: string }>({ url: '/api/service/logs', params: { lines } });
  }

  async getServiceConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/service/config' });
  }

  async updateServiceConfig(config: Record<string, unknown>): Promise<void> {
    await this.request({ url: '/api/service/config', method: 'put', data: config });
  }

  async getEnvironmentInfo(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/service/env' });
  }

  async getControlServiceHealth(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/health' });
  }

  async getMainBackendStatus(): Promise<{ running: boolean; version?: string }> {
    return this.controlRequest<{ running: boolean; version?: string }>({ url: '/api/status' });
  }

  async startMainBackend(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/api/start', method: 'post' });
  }

  async stopMainBackend(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/api/stop', method: 'post' });
  }

  async restartMainBackend(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/api/restart', method: 'post' });
  }

  async getVectorStatus(): Promise<{ status: string; backend: string; connected: boolean }> {
    return this.request<{ status: string; backend: string; connected: boolean }>({ url: '/api/vector/status' });
  }

  async getVectorStats(): Promise<{ total: number; by_type: Record<string, number> }> {
    return this.request<{ total: number; by_type: Record<string, number> }>({ url: '/api/vector/stats' });
  }

  async getVector(memoryId: number): Promise<VectorData> {
    return this.request<VectorData>({ url: `/api/vector/${memoryId}` });
  }

  async deleteVector(memoryId: number): Promise<void> {
    await this.request({ url: `/api/vector/${memoryId}`, method: 'delete' });
  }

  async getGraphStatus(): Promise<GraphStats> {
    return this.request<GraphStats>({ url: '/api/graph/status' });
  }

  async getGraphEntityTypes(library: string = 'thing'): Promise<{ types: string[]; entity_types?: string[] }> {
    return this.request<{ types: string[]; entity_types?: string[] }>({ url: `/api/graph/${library}/entity-types` });
  }

  async getGraphRelationTypes(library: string = 'thing'): Promise<{ types: string[]; relation_types?: string[] }> {
    return this.request<{ types: string[]; relation_types?: string[] }>({ url: `/api/graph/${library}/relation-types` });
  }

  async deleteGraphEntity(library: string, entityId: string): Promise<void> {
    await this.request({ url: `/api/graph/${library}/entities/${entityId}`, method: 'delete' });
  }

  async deleteGraphRelation(library: string, params: { source_id: string; target_id: string; relation_type: string }): Promise<void> {
    await this.request({ url: `/api/graph/${library}/relations`, method: 'delete', data: params });
  }

  async getAudioConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/audio/config' });
  }

  async getAudioFiles(): Promise<{ files: { name: string; size: number; modified: string }[] }> {
    return this.request<{ files: { name: string; size: number; modified: string }[] }>({ url: '/api/audio/files' });
  }

  async deleteAudioFile(filename: string): Promise<void> {
    await this.request({ url: `/api/audio/files/${filename}`, method: 'delete' });
  }

  async getVoiceWorkstationStatus(): Promise<{ status: string }> {
    return this.voiceWorkstationRequest<{ status: string }>({ url: '/health' });
  }

  async pregenerateRefs(data: {
    base_audio_path: string;
    sample_text?: string;
    transition_text?: string;
  }): Promise<{
    status: string;
    emotions_count: number;
    transitions_count: number;
    total: number;
  }> {
    return this.voiceWorkstationRequest<{
      status: string;
      emotions_count: number;
      transitions_count: number;
      total: number;
    }>({
      url: '/pregenerate-refs',
      method: 'POST',
      data,
    });
  }

  async getRefsStatus(): Promise<{
    emotions_count: number;
    transitions_count: number;
    total_count: number;
    is_complete: boolean;
    expected_total: number;
  }> {
    return this.voiceWorkstationRequest<{
      emotions_count: number;
      transitions_count: number;
      total_count: number;
      is_complete: boolean;
      expected_total: number;
    }>({ url: '/refs-status' });
  }

  async startF5TTSFinetune(data: {
    ref_audio_path: string;
    ref_text: string;
    epochs?: number;
  }): Promise<{ status: string; task_id: string }> {
    return this.voiceWorkstationRequest<{ status: string; task_id: string }>({
      url: '/f5tts/finetune',
      method: 'POST',
      data,
    });
  }

  async getF5TTSFinetuneStatus(): Promise<{
    status: string;
    progress?: number;
    message?: string;
  }> {
    return this.voiceWorkstationRequest<{
      status: string;
      progress?: number;
      message?: string;
    }>({ url: '/f5tts/finetune/status' });
  }

  async startSoVITSSVCTrain(data: {
    training_data_dir: string;
    model_name?: string;
    epochs?: number;
    batch_size?: number;
    learning_rate?: number;
  }): Promise<{ status: string; task_id: string }> {
    return this.voiceWorkstationRequest<{ status: string; task_id: string }>({
      url: '/sovits-svc/train',
      method: 'POST',
      data,
    });
  }

  async stopSoVITSSVCTrain(): Promise<{ status: string }> {
    return this.voiceWorkstationRequest<{ status: string }>({
      url: '/sovits-svc/train/stop',
      method: 'POST',
    });
  }

  async getSoVITSSVCStatus(): Promise<{
    status: string;
    progress?: number;
    message?: string;
    models?: string[];
  }> {
    return this.voiceWorkstationRequest<{
      status: string;
      progress?: number;
      message?: string;
      models?: string[];
    }>({ url: '/sovits-svc/status' });
  }

  async sovitsSVCInfer(data: {
    input_audio_path: string;
    ref_audio_path?: string;
  }): Promise<{ status: string; output_path: string }> {
    return this.voiceWorkstationRequest<{ status: string; output_path: string }>({
      url: '/sovits-svc/infer',
      method: 'POST',
      data,
    });
  }

  async generateVoxCPM(data: {
    mode: 'design' | 'controllable_clone' | 'ultimate_clone';
    text: string;
    control?: string;
    reference_audio_path?: string;
    prompt_audio_path?: string;
    prompt_text?: string;
    output_path?: string;
    cfg_value?: number;
    inference_timesteps?: number;
  }): Promise<{ status: string; output_path: string }> {
    return this.voiceWorkstationRequest<{ status: string; output_path: string }>({
      url: '/api/voxcpm/generate',
      method: 'POST',
      data,
    });
  }

  async getVoxCPMStatus(): Promise<{ status: string; model_path: string }> {
    return this.voiceWorkstationRequest<{ status: string; model_path: string }>({
      url: '/api/voxcpm/status',
    });
  }

  async exportEmotionRefsZip(data: {
    base_audio_path: string;
    sample_text?: string;
    transition_text?: string;
  }): Promise<Blob> {
    const axiosInstance = this.voiceWorkstationClient;
    const response = await axiosInstance.post('/api/ref-audio/export-zip', data, {
      responseType: 'blob',
    });
    return response.data;
  }

  async importEmotionRefsZip(file: File): Promise<{
    status: string;
    meta: {
      emotions: Array<{ file: string; emotion: string; text: string; instruct_text: string }>;
      transitions: Array<{ file: string; from_emotion: string; to_emotion: string; text: string; instruct_text: string }>;
    };
  }> {
    const formData = new FormData();
    formData.append('file', file);
    const axiosInstance = this.voiceWorkstationClient;
    const response = await axiosInstance.post('/api/ref-audio/import-zip', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  }

  async sovitsSVCPreprocess(data: {
    training_data_dir: string;
    speaker_name: string;
  }): Promise<{ status: string; results: Record<string, unknown> }> {
    return this.voiceWorkstationRequest<{ status: string; results: Record<string, unknown> }>({
      url: '/api/sovits-svc/preprocess',
      method: 'POST',
      data,
    });
  }

  async getDanmakuConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/danmaku/config' });
  }

  async getFirewallConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/firewall/config' });
  }

  async getFirewallV3Config(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/firewall/v3/config' });
  }

  async getLiveClientStatus(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/live/client/status' });
  }

  async getVadConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/vad/config' });
  }

  async getSenseVoiceStreamingConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/config/sensevoice-streaming' });
  }

  async getAdaptivePollingConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/config/adaptive-polling' });
  }

  async getGraphConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/graph/config' });
  }

  async textToSpeech(text: string): Promise<Blob> {
    // BUG-F48: 单独走 axios 配置 responseType: 'arraybuffer'，确保返回正确的二进制数据
    const axiosInstance = this.client;
    const response = await axiosInstance.post<ArrayBuffer>(
      '/api/tts',
      { text },
      { responseType: 'arraybuffer' }
    );
    return new Blob([response.data], { type: 'audio/mp3' });
  }

  async speechToText(audioBlob: Blob): Promise<{ text: string }> {
    const formData = new FormData();
    formData.append('audio', audioBlob);

    const axiosInstance = this.client;
    const response = await axiosInstance.post<{ text: string }>('/api/asr', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  }

  async sendMessageStream(
    message: string,
    onChunk: (chunk: Record<string, unknown>) => void,
    agentId: string = 'default',
    images?: string[]
  ): Promise<void> {
    const baseUrl = getApiBaseUrl();
    const token = localStorage.getItem('cxhms-token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(`${baseUrl}/api/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ message, agent_id: agentId, images }),
    });

    if (!response.ok || !response.body) {
      const errorText = await response.text().catch(() => '');
      throw new Error(`请求失败: ${response.status} ${response.statusText} ${errorText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let streamDone = false;

    const flushLine = (rawLine: string) => {
      if (!rawLine) return;
      const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
      if (!line.startsWith('data:')) return;
      const dataPayload = line.startsWith('data: ') ? line.slice(6) : line.slice(5);
      if (!dataPayload) return;
      if (dataPayload.trim() === '[DONE]') {
        streamDone = true;
        return;
      }
      try {
        const chunk = JSON.parse(dataPayload) as Record<string, unknown>;
        onChunk(chunk);
      } catch {
        // 忽略单行解析错误
      }
    };

    while (!streamDone) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // 按行处理；保留最后未换行的部分到 buffer
      const parts = buffer.split('\n');
      buffer = parts.pop() ?? '';
      for (const line of parts) {
        flushLine(line);
      }
    }

    // 处理流结束时 buffer 中可能残留的最后一帧（无 \n 终止）
    if (buffer.length > 0) {
      flushLine(buffer);
    }
  }

  async uploadAudioFile(file: File): Promise<{ filename: string; url: string }> {
    const formData = new FormData();
    formData.append('file', file);

    const axiosInstance = this.client;
    const response = await axiosInstance.post<{ filename: string; url: string }>('/api/audio/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data;
  }

  async disconnectLiveClient(clientId: string): Promise<void> {
    await this.request({ url: `/api/live/client/${clientId}/disconnect`, method: 'post' });
  }

  async listGraphEntities(entityType?: string, limit?: number): Promise<{ entities: GraphEntity[] }> {
    const params = new URLSearchParams();
    if (entityType) params.append('entity_type', entityType);
    if (limit) params.append('limit', String(limit));
    return this.request({ url: `/api/graph/entities?${params.toString()}` });
  }

  async listGraphRelations(relationType?: string, limit?: number): Promise<{ relations: GraphRelation[] }> {
    const params = new URLSearchParams();
    if (relationType) params.append('relation_type', relationType);
    if (limit) params.append('limit', String(limit));
    return this.request({ url: `/api/graph/relations?${params.toString()}` });
  }

  async createGraphEntity(entityType: string, entityData: Record<string, unknown>): Promise<GraphEntity> {
    return this.request({ url: '/api/graph/entities', method: 'post', data: { entity_type: entityType, ...entityData } });
  }

  async createGraphRelation(relationType: string, sourceId: string, targetId: string, relationData?: Record<string, unknown>): Promise<GraphRelation> {
    return this.request({ url: '/api/graph/relations', method: 'post', data: { relation_type: relationType, source_id: sourceId, target_id: targetId, ...relationData } });
  }

  async findGraphPath(sourceId: string, targetId: string, maxDepth?: number): Promise<{ path: GraphEntity[] }> {
    const params = new URLSearchParams();
    params.append('source_id', sourceId);
    params.append('target_id', targetId);
    if (maxDepth) params.append('max_depth', String(maxDepth));
    return this.request({ url: `/api/graph/path?${params.toString()}` });
  }

  async listVectors(limit?: number, offset?: number): Promise<{ vectors: VectorData[]; total: number }> {
    const params = new URLSearchParams();
    if (limit) params.append('limit', String(limit));
    if (offset) params.append('offset', String(offset));
    return this.request({ url: `/api/vectors?${params.toString()}` });
  }

  async searchVectors(query: string, limit?: number): Promise<{ results: VectorData[] }> {
    const params = new URLSearchParams();
    params.append('query', query);
    if (limit) params.append('limit', String(limit));
    return this.request({ url: `/api/vectors/search?${params.toString()}` });
  }

  async syncVectors(): Promise<{ status: string }> {
    return this.request({ url: '/api/vectors/sync', method: 'post' });
  }

  async rebuildVectors(): Promise<{ status: string }> {
    return this.request({ url: '/api/vectors/rebuild', method: 'post' });
  }

  async createTool(toolData: Record<string, unknown>): Promise<Tool> {
    return this.request({ url: '/api/tools', method: 'post', data: toolData });
  }

  async updateTool(toolId: string, toolData: Record<string, unknown>): Promise<Tool> {
    return this.request({ url: `/api/tools/${toolId}`, method: 'patch', data: toolData });
  }

  async sendMemoryAgentMessageStream(
    message: string,
    onChunk: (chunk: Record<string, unknown>) => void,
    sessionId?: string
  ): Promise<void> {
    const axiosInstance = this.client;

    const response = await axiosInstance.post('/api/memory-agent/chat/stream', {
      message,
      session_id: sessionId,
    }, {
      responseType: 'text',
      transformResponse: [(data: string) => data],
    });

    const lines = response.data.split('\n');
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const jsonStr = line.slice(6);
          if (jsonStr.trim()) {
            const chunk = JSON.parse(jsonStr) as Record<string, unknown>;
            onChunk(chunk);
          }
        } catch {
          /* 忽略无法解析的 SSE 数据行 */
        }
      }
    }
  }

  getAudioFileUrl(filename: string): string {
    return `${getApiBaseUrl()}/api/audio/files/${filename}`;
  }

  async listAvatars(type?: 'vrm' | 'live2d'): Promise<{ avatars: Array<{
    id: string;
    name: string;
    type: string;
    size: number;
    created_at: string;
    updated_at?: string;
    metadata?: Record<string, unknown>;
  }>; total: number }> {
    return this.request({
      url: '/api/avatars',
      params: type ? { type } : undefined,
    });
  }

  async uploadAvatar(
    file: File,
    avatarType: 'vrm' | 'live2d',
    name?: string,
    onProgress?: (progress: number) => void
  ): Promise<{ status: string; avatar: {
    id: string;
    name: string;
    type: string;
    size: number;
    created_at: string;
  } }> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('avatar_type', avatarType);
    if (name) formData.append('name', name);

    const axiosInstance = this.client;

    const response = await axiosInstance.post('/api/avatars/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: onProgress
        ? (progressEvent) => {
            const total = progressEvent.total || file.size;
            const progress = Math.round((progressEvent.loaded * 100) / total);
            onProgress(progress);
          }
        : undefined,
    });
    return response.data;
  }

  getAvatarFileUrl(avatarId: string, avatarType: string): string {
    return `${getApiBaseUrl()}/api/avatars/${avatarId}/file?avatar_type=${avatarType}`;
  }

  async downloadAvatarFile(avatarId: string, avatarType: string): Promise<Blob> {
    const axiosInstance = this.client;

    const response = await axiosInstance.get(`/api/avatars/${avatarId}/file`, {
      params: { avatar_type: avatarType },
      responseType: 'blob',
    });
    return response.data;
  }

  async getAvatar(avatarId: string, avatarType: string): Promise<{
    id: string;
    name: string;
    type: string;
    size: number;
    created_at: string;
    updated_at?: string;
    metadata?: Record<string, unknown>;
  }> {
    return this.request({
      url: `/api/avatars/${avatarId}`,
      params: { avatar_type: avatarType },
    });
  }

  async updateAvatar(
    avatarId: string,
    avatarType: string,
    updates: { name?: string; metadata?: Record<string, unknown> }
  ): Promise<{ status: string; avatar: unknown }> {
    return this.request({
      url: `/api/avatars/${avatarId}?avatar_type=${avatarType}`,
      method: 'put',
      data: updates,
    });
  }

  async deleteAvatar(avatarId: string, avatarType: string): Promise<{ status: string; message: string }> {
    return this.request({
      url: `/api/avatars/${avatarId}?avatar_type=${avatarType}`,
      method: 'delete',
    });
  }

  async getCxfcPlugins(): Promise<CxfcPlugin[]> {
    const response = await this.request<{ plugins: CxfcPlugin[] }>({ url: '/api/cxfc/plugins' });
    return response.plugins || [];
  }

  async getCxfcSkills(): Promise<CxfcSkill[]> {
    const response = await this.request<{ skills: CxfcSkill[] }>({ url: '/api/cxfc/skills' });
    return response.skills || [];
  }

  async connectCxfcPlugin(host: string, port: number): Promise<{ status: string; plugin_id: string }> {
    return this.request<{ status: string; plugin_id: string }>({
      url: '/api/cxfc/connect',
      method: 'post',
      data: { host, port },
    });
  }

  async disconnectCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return this.request<{ status: string }>({
      url: `/api/cxfc/plugins/${pluginId}/disconnect`,
      method: 'post',
    });
  }

  async refreshCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return this.request<{ status: string }>({
      url: `/api/cxfc/plugins/${pluginId}/refresh`,
      method: 'post',
    });
  }

  async discoverCxfcPlugins(scan: boolean = false): Promise<{ remote: CxfcDiscoveredPlugin[] }> {
    return this.request<{ remote: CxfcDiscoveredPlugin[] }>({
      url: '/api/cxfc/discover',
      params: scan ? { scan: true } : undefined,
    });
  }
}

export const api = new ApiClient();
