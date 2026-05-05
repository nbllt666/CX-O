import axios, { AxiosInstance, AxiosError } from 'axios';
import type { AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';

const getApiBaseUrl = () => localStorage.getItem('cxhms-backend-url') || import.meta.env.VITE_API_URL || 'http://localhost:8100';
const getControlServiceUrl = () => localStorage.getItem('cxhms-control-url') || import.meta.env.VITE_CONTROL_SERVICE_URL || 'http://localhost:8100';
const getWsBaseUrl = () => localStorage.getItem('cxhms-ws-url') || import.meta.env.VITE_WS_URL || 'ws://localhost:8100';

export const WS_BASE_URL = getWsBaseUrl();

export const getApiUrl = () => getApiBaseUrl();
export const getControlUrl = () => getControlServiceUrl();

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
  type: 'builtin' | 'custom' | 'mcp';
  status: 'active' | 'inactive' | 'error';
  config: Record<string, unknown>;
  icon?: string;
  created_at: string;
  last_used?: string;
  use_count: number;
  parameters?: Record<string, unknown>;
  examples?: string[];
  tags?: string[];
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
  private get client(): AxiosInstance {
    return axios.create({
      baseURL: getApiBaseUrl(),
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  private get controlClient(): AxiosInstance {
    return axios.create({
      baseURL: getControlServiceUrl(),
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });
  }

  private maxRetries: number = 3;
  private retryDelay: number = 1000;
  private cache: Map<string, { data: unknown; timestamp: number; ttl: number }>;

  constructor() {
    this.cache = new Map();
  }

  private _getCacheKey(url: string, params?: Record<string, unknown>): string {
    return `${url}?${JSON.stringify(params || {})}`;
  }

  private _getFromCache(key: string): unknown | null {
    const cached = this.cache.get(key);
    if (!cached) return null;

    if (Date.now() - cached.timestamp > cached.ttl) {
      this.cache.delete(key);
      return null;
    }

    return cached.data;
  }

  private _setCache(key: string, data: unknown, ttl: number = 60000): void {
    this.cache.set(key, {
      data,
      timestamp: Date.now(),
      ttl,
    });
  }

  private _clearCache(pattern?: string): void {
    if (pattern) {
      for (const key of this.cache.keys()) {
        if (key.includes(pattern)) {
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
        if (!config || config.retryCount !== undefined) {
          return Promise.reject(error);
        }

        const retryCount = (config.retryCount || 0) + 1;
        if (retryCount <= this.maxRetries) {
          config.retryCount = retryCount;
          await new Promise((resolve) => setTimeout(resolve, this.retryDelay * retryCount));
          return axiosInstance(config);
        }

        return Promise.reject(error);
      }
    );
  }

  async request<T>(config: AxiosRequestConfig, useCache: boolean = false): Promise<T> {
    const cacheKey = this._getCacheKey(config.url || '', config.params as Record<string, unknown>);

    if (useCache && config.method === 'get') {
      const cached = this._getFromCache(cacheKey);
      if (cached) return cached as T;
    }

    try {
      const axiosInstance = this.client;
      this._setupInterceptors(axiosInstance);
      const response = await axiosInstance.request<T>(config);

      if (useCache && config.method === 'get') {
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
      this._setupInterceptors(axiosInstance);
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

  async getBackendStatus(): Promise<{ running: boolean; version?: string }> {
    return this.request<{ running: boolean; version?: string }>({ url: '/api/status' });
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
    return response.agent;
  }

  async updateAgent(agentId: string, data: Partial<Agent>): Promise<Agent> {
    const response = await this.request<{ status: string; agent: Agent; message: string }>({ url: `/api/agents/${agentId}`, method: 'put', data });
    return response.agent;
  }

  async deleteAgent(agentId: string): Promise<void> {
    await this.request<{ status: string; message: string }>({ url: `/api/agents/${agentId}`, method: 'delete' });
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

  async updateConfig(section: string, data: Record<string, unknown>): Promise<void> {
    await this.request({ url: '/api/config', method: 'put', data: { section, data } });
    this._clearCache();
  }

  async sendMessage(message: string, agentId: string = 'default', sessionId?: string): Promise<{ response: string; session_id: string }> {
    const response = await this.request<{ status: string; response: string; session_id: string }>({
      url: '/api/chat/send',
      method: 'post',
      data: { message, agent_id: agentId, session_id: sessionId }
    });
    return { response: response.response, session_id: response.session_id };
  }

  async getChatHistory(agentId: string = 'default'): Promise<{ messages: ChatMessage[] }> {
    return this.request<{ messages: ChatMessage[] }>({ url: `/api/context/history/${agentId}` });
  }

  async createSession(title: string, agentId: string = 'default'): Promise<Session> {
    return this.request<Session>({ url: '/api/context/sessions', method: 'post', data: { title, agent_id: agentId } });
  }

  async getSessions(): Promise<Session[]> {
    return this.request<Session[]>({ url: '/api/context/sessions' });
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
    return this.request<ArchiveStats>({ url: '/archive/stats' });
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
    return this.request<{ tools: Record<string, Tool> }>({ url: '/api/tools', params: filter ? { filter } : undefined });
  }

  async getToolsStats(): Promise<ToolStats> {
    return this.request<ToolStats>({ url: '/api/tools/stats' });
  }

  async deleteTool(toolId: string): Promise<void> {
    await this.request({ url: `/api/tools/${toolId}`, method: 'delete' });
  }

  async testTool(toolId: string, params?: Record<string, unknown>): Promise<{ result: Record<string, unknown> }> {
    return this.request<{ result: Record<string, unknown> }>({ url: `/api/tools/${toolId}/test`, method: 'post', data: params });
  }

  async getAcpStats(): Promise<AcpStats> {
    return this.request<AcpStats>({ url: '/api/acp/stats' });
  }

  async getAcpAgents(): Promise<AcpAgentRow[]> {
    return this.request<AcpAgentRow[]>({ url: '/api/acp/agents' });
  }

  async createAcpAgent(data: { name: string; description?: string; capabilities?: string[] }): Promise<AcpAgentRow> {
    return this.request<AcpAgentRow>({ url: '/api/acp/agents', method: 'post', data });
  }

  async updateAcpAgent(agentId: string, data: Record<string, unknown>): Promise<AcpAgentRow> {
    return this.request<AcpAgentRow>({ url: `/api/acp/agents/${agentId}`, method: 'put', data });
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

  async getCosyVoiceStatus(): Promise<{ status: string; engine?: string }> {
    return this.request<{ status: string; engine?: string }>({ url: '/api/audio/cosyvoice/status' });
  }

  async getCosyVoiceRefsStatus(): Promise<{ 
    emotions_count: number; 
    transitions_count: number; 
    total_count: number; 
    is_complete: boolean;
    expected_total: number;
  }> {
    return this.request<{ 
      emotions_count: number; 
      transitions_count: number; 
      total_count: number; 
      is_complete: boolean;
      expected_total: number;
    }>({ url: '/api/audio/cosyvoice/refs-status' });
  }

  async pregenerateEmotionRefs(data: { 
    base_audio_path: string;
    sample_text?: string;
    transition_text?: string;
  }): Promise<{ 
    status: string; 
    emotions_count: number; 
    transitions_count: number; 
    total: number;
  }> {
    return this.request<{ 
      status: string; 
      emotions_count: number; 
      transitions_count: number; 
      total: number;
    }>({ 
      url: '/api/audio/cosyvoice/pregenerate-refs', 
      method: 'POST',
      data
    });
  }

  async getIndexTTSStatus(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/audio/cosyvoice/status' });
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
    return this.request<Record<string, unknown>>({ url: '/api/sense-voice-streaming/config' });
  }

  async getAdaptivePollingConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/adaptive-polling/config' });
  }

  async getGraphConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/graph/config' });
  }

  async textToSpeech(text: string): Promise<Blob> {
    const response = await this.request<ArrayBuffer>({
      url: '/api/tts',
      method: 'post',
      data: { text },
      responseType: 'arraybuffer',
    });
    return new Blob([response], { type: 'audio/mp3' });
  }

  async speechToText(audioBlob: Blob): Promise<{ text: string }> {
    const formData = new FormData();
    formData.append('audio', audioBlob);
    
    const axiosInstance = this.client;
    this._setupInterceptors(axiosInstance);
    
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
    const axiosInstance = this.client;
    this._setupInterceptors(axiosInstance);

    const response = await axiosInstance.post('/api/chat/stream', {
      message,
      agent_id: agentId,
      images,
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
          // Ignore parse errors
        }
      }
    }
  }

  async uploadAudioFile(file: File): Promise<{ filename: string; url: string }> {
    const formData = new FormData();
    formData.append('file', file);
    
    const axiosInstance = this.client;
    this._setupInterceptors(axiosInstance);
    
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
    return this.request({ url: `/api/tools/${toolId}`, method: 'put', data: toolData });
  }

  async sendMemoryAgentMessageStream(
    message: string,
    onChunk: (chunk: Record<string, unknown>) => void,
    sessionId?: string
  ): Promise<void> {
    const axiosInstance = this.client;
    this._setupInterceptors(axiosInstance);

    const response = await axiosInstance.post('/api/memory-agent/stream', {
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
          // Ignore parse errors
        }
      }
    }
  }

  getAudioFileUrl(filename: string): string {
    return `${getApiBaseUrl()}/api/audio/files/${filename}`;
  }
}

export const api = new ApiClient();