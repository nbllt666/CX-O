import axios, { AxiosInstance, AxiosError } from 'axios';
import type { AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8100';
const CONTROL_SERVICE_URL = import.meta.env.VITE_CONTROL_SERVICE_URL || 'http://localhost:8100';
export const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8100';

interface RetryConfig extends InternalAxiosRequestConfig {
  retryCount?: number;
}

// Type definitions
export interface Agent {
  id: string;
  name: string;
  description?: string;
  is_default?: boolean;
  model?: string;
  temperature?: number;
  max_tokens?: number;
  system_prompt?: string;
  use_memory?: boolean;
  memory_scene?: string;
  tools?: string[];
  capabilities?: string[];
}

class ApiClient {
  private client: AxiosInstance;
  private controlClient: AxiosInstance;
  private maxRetries: number = 3;
  private retryDelay: number = 1000;
  private cache: Map<string, { data: unknown; timestamp: number; ttl: number }>;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.controlClient = axios.create({
      baseURL: CONTROL_SERVICE_URL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
      },
    });

    this.cache = new Map();
    this._setupInterceptors(this.client);
    this._setupInterceptors(this.controlClient);
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
        if (error.response?.status === 401) {
          localStorage.removeItem('cxhms-token');
          window.location.href = '/login';
          return Promise.reject(error);
        }

        if (error.response?.status === 503) {
          return Promise.reject(error);
        }

        const config = error.config as RetryConfig | undefined;
        if (!config || !config.retryCount) {
          if (config) config.retryCount = 0;
        }

        if (config && config.retryCount !== undefined && config.retryCount < this.maxRetries) {
          config.retryCount += 1;
          await new Promise((resolve) =>
            setTimeout(resolve, this.retryDelay * (config.retryCount || 1))
          );
          return axiosInstance.request(config as AxiosRequestConfig);
        }

        return Promise.reject(error);
      }
    );
  }

  // ========== Control Service APIs (Port 8765) ==========

  // Check control service health
  async getControlServiceHealth() {
    const response = await this.controlClient.get('/health');
    return response.data;
  }

  // Get main backend status via control service
  async getMainBackendStatus() {
    const response = await this.controlClient.get('/control/status');
    return response.data;
  }

  // Start main backend service
  async startMainBackend() {
    const response = await this.controlClient.post('/control/start');
    return response.data;
  }

  // Stop main backend service
  async stopMainBackend() {
    const response = await this.controlClient.post('/control/stop');
    return response.data;
  }

  // Restart main backend service
  async restartMainBackend() {
    const response = await this.controlClient.post('/control/restart');
    return response.data;
  }

  // ========== Main Backend APIs (Port 8000) ==========

  // Service Management (via main backend when running)
  async getServiceStatus() {
    const response = await this.client.get('/api/service/status');
    return response.data;
  }

  async startService(config: {
    host?: string;
    port?: number;
    log_level?: string;
    reload?: boolean;
    use_conda?: boolean;
  }) {
    const response = await this.client.post('/api/service/start', config);
    return response.data;
  }

  async stopService() {
    const response = await this.client.post('/api/service/stop');
    return response.data;
  }

  async restartService(config: {
    host?: string;
    port?: number;
    log_level?: string;
    reload?: boolean;
    use_conda?: boolean;
  }) {
    const response = await this.client.post('/api/service/restart', config);
    return response.data;
  }

  async getServiceLogs(lines: number = 100) {
    const response = await this.client.get('/api/service/logs', { params: { lines } });
    return response.data;
  }

  async getServiceConfig() {
    const response = await this.client.get('/api/service/config');
    return response.data;
  }

  async updateServiceConfig(config: Record<string, unknown>) {
    const response = await this.client.post('/api/service/config', config);
    return response.data;
  }

  async getGatewayServicesConfig() {
    const response = await this.client.get('/api/config/services');
    return response.data;
  }

  async updateGatewayServicesConfig(config: Record<string, unknown>) {
    const response = await this.client.post('/api/config/services', config);
    return response.data;
  }

  async getEnvironmentInfo() {
    const response = await this.client.get('/api/service/environment');
    return response.data;
  }

  // Agent Memory Tables
  async getAgentMemoryTables() {
    const response = await this.client.get('/api/memories/agents');
    return response.data;
  }

  // Memories
  async getMemories(params?: {
    type?: string;
    limit?: number;
    offset?: number;
    query?: string;
    agent_id?: string;
  }) {
    const response = await this.client.get('/api/memories', { params });
    return response.data;
  }

  async createMemory(data: {
    content: string;
    type?: string;
    importance?: number;
    tags?: string[];
    agent_id?: string;
  }) {
    const response = await this.client.post('/api/memories', data);
    return response.data;
  }

  async updateMemory(
    id: number,
    data: Partial<{
      content: string;
      type: string;
      importance: number;
      tags: string[];
    }>,
    agentId?: string
  ) {
    const response = await this.client.put(`/api/memories/${id}`, {
      ...data,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async deleteMemory(id: number, soft_delete: boolean = false) {
    const response = await this.client.delete(`/api/memories/${id}`, {
      params: { soft_delete },
    });
    return response.data;
  }

  // Permanent Memories
  async getPermanentMemories(params?: { limit?: number; offset?: number; workspace_id?: string }) {
    const response = await this.client.get('/api/memories/permanent', { params });
    return response.data;
  }

  async createPermanentMemory(data: {
    content: string;
    importance?: number;
    tags?: string[];
    metadata?: Record<string, unknown>;
  }) {
    const response = await this.client.post('/api/memories/permanent', data);
    return response.data;
  }

  async updatePermanentMemory(
    id: number,
    data: Partial<{
      content: string;
      importance: number;
      tags: string[];
      metadata: Record<string, unknown>;
    }>
  ) {
    const response = await this.client.put(`/api/memories/permanent/${id}`, data);
    return response.data;
  }

  async deletePermanentMemory(id: number) {
    const response = await this.client.delete(`/api/memories/permanent/${id}`);
    return response.data;
  }

  async searchMemories(
    query: string,
    options?: {
      type?: string;
      limit?: number;
    }
  ) {
    const response = await this.client.post('/api/memories/search', {
      query,
      ...options,
    });
    return response.data;
  }

  async semanticSearch(
    query: string,
    options?: {
      limit?: number;
      min_score?: number;
    }
  ) {
    const response = await this.client.post('/api/memories/semantic-search', {
      query,
      ...options,
    });
    return response.data;
  }

  // Archive
  async getArchiveStats() {
    const response = await this.client.get('/api/archive/stats');
    return response.data;
  }

  async getArchivedMemories(params?: { limit?: number; offset?: number; agent_id?: string }) {
    const response = await this.client.get('/api/archive/list', { params });
    return response.data;
  }

  async restoreMemory(memoryId: number, agentId?: string) {
    const response = await this.client.post('/api/memories/batch/restore', {
      ids: [memoryId],
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async archiveMemory(memoryId: number, targetLevel: number = 1) {
    const response = await this.client.post('/api/archive/memory', {
      memory_id: memoryId,
      target_level: targetLevel,
    });
    return response.data;
  }

  async mergeMemories(memoryIds: number[]) {
    const response = await this.client.post('/api/archive/merge', {
      memory_ids: memoryIds,
    });
    return response.data;
  }

  async detectDuplicates() {
    const response = await this.client.post('/api/archive/deduplicate');
    return response.data;
  }

  async autoArchiveProcess() {
    const response = await this.client.post('/api/archive/auto-process');
    return response.data;
  }

  // Memory Chat
  async memoryChat(message: string, sessionId: string = 'default') {
    const response = await this.client.post('/api/memory-chat', {
      message,
      session_id: sessionId,
    });
    return response.data;
  }

  // Chat
  async sendMessage(message: string, sessionId?: string, agentId?: string) {
    const response = await this.client.post('/api/chat', {
      message,
      session_id: sessionId,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  // Context
  async getSessions() {
    const cacheKey = this._getCacheKey('/api/context/sessions');
    const cached = this._getFromCache(cacheKey);
    if (cached) return cached;

    const response = await this.client.get('/api/context/sessions');
    this._setCache(cacheKey, response.data, 30000);
    return response.data;
  }

  async createSession(title?: string) {
    this._clearCache('/api/context/sessions');
    const response = await this.client.post('/api/context/sessions', {
      workspace_id: 'default',
      title: title || '新对话',
    });
    return response.data;
  }

  async deleteSession(sessionId: string) {
    this._clearCache('/api/context/sessions');
    this._clearCache(`/api/context/sessions/${sessionId}`);
    const response = await this.client.delete(`/api/context/sessions/${sessionId}`);
    return response.data;
  }

  async clearAllSessions() {
    this._clearCache('/api/context/sessions');
    const response = await this.client.delete('/api/context/sessions/all');
    return response.data;
  }

  // Admin
  async getHealth() {
    const response = await this.client.get('/health');
    return response.data;
  }

  async getChatHistory(agentId: string) {
    const response = await this.client.get(`/api/chat/history/agent-${agentId}`);
    return response.data;
  }

  // ========== ACP APIs ==========

  async getAcpStats() {
    const response = await this.client.get('/api/acp/stats');
    return response.data;
  }

  async getAcpAgents() {
    const response = await this.client.get('/api/acp/agents');
    return response.data;
  }

  async createAcpAgent(data: {
    name: string;
    description?: string;
    capabilities?: string[];
    status?: 'active' | 'inactive';
  }) {
    const response = await this.client.post('/api/acp/agents', data);
    return response.data;
  }

  async updateAcpAgent(
    id: string,
    data: Partial<{
      name: string;
      description: string;
      capabilities: string[];
      status: 'active' | 'inactive';
    }>
  ) {
    const response = await this.client.put(`/api/acp/agents/${id}`, data);
    return response.data;
  }

  async deleteAcpAgent(id: string) {
    const response = await this.client.delete(`/api/acp/agents/${id}`);
    return response.data;
  }

  // ========== Chat Agent APIs ==========

  async getAgents() {
    const cacheKey = this._getCacheKey('/api/agents');
    const cached = this._getFromCache(cacheKey);
    if (cached) return cached;

    const response = await this.client.get('/api/agents');
    this._setCache(cacheKey, response.data, 300000);
    return response.data;
  }

  async getAgent(id: string) {
    const cacheKey = this._getCacheKey(`/api/agents/${id}`);
    const cached = this._getFromCache(cacheKey);
    if (cached) return cached;

    const response = await this.client.get(`/api/agents/${id}`);
    this._setCache(cacheKey, response.data, 300000);
    return response.data;
  }

  async createAgent(data: {
    name: string;
    description?: string;
    system_prompt?: string;
    model?: string;
    temperature?: number;
    max_tokens?: number;
    use_memory?: boolean;
    use_tools?: boolean;
    vision_enabled?: boolean;
    memory_scene?: string;
  }) {
    this._clearCache('/api/agents');
    const response = await this.client.post('/api/agents', data);
    return response.data;
  }

  async updateAgent(
    id: string,
    data: Partial<{
      name: string;
      description: string;
      system_prompt: string;
      model: string;
      temperature: number;
      max_tokens: number;
      use_memory: boolean;
      use_tools: boolean;
      vision_enabled: boolean;
      memory_scene: string;
    }>
  ) {
    this._clearCache('/api/agents');
    this._clearCache(`/api/agents/${id}`);
    const response = await this.client.put(`/api/agents/${id}`, data);
    return response.data;
  }

  async deleteAgent(id: string) {
    this._clearCache('/api/agents');
    this._clearCache(`/api/agents/${id}`);
    const response = await this.client.delete(`/api/agents/${id}`);
    return response.data;
  }

  async cloneAgent(id: string) {
    const response = await this.client.post(`/api/agents/${id}/clone`);
    return response.data;
  }

  // ========== Tools APIs ==========

  async getToolsStats() {
    const response = await this.client.get('/api/tools/stats');
    return response.data;
  }

  async getTools(type?: string) {
    const params: Record<string, string> = {};
    // type 参数映射到 category
    if (type && type !== 'all' && type !== 'builtin') {
      params['category'] = type;
    }
    if (type === 'builtin') {
      params['include_builtin'] = 'true';
    }
    const response = await this.client.get('/api/tools', { params });
    return response.data;
  }

  async createTool(data: {
    name: string;
    description?: string;
    type: 'mcp' | 'native' | 'custom';
    icon?: string;
    config?: Record<string, unknown>;
  }) {
    const response = await this.client.post('/api/tools', data);
    return response.data;
  }

  async updateTool(
    id: string,
    data: Partial<{
      name: string;
      description: string;
      type: 'mcp' | 'native' | 'custom';
      icon: string;
      config: Record<string, unknown>;
      status: 'active' | 'inactive';
    }>
  ) {
    const response = await this.client.put(`/api/tools/${id}`, data);
    return response.data;
  }

  async deleteTool(id: string) {
    const response = await this.client.delete(`/api/tools/${id}`);
    return response.data;
  }

  async testTool(id: string, params: Record<string, unknown>) {
    const response = await this.client.post(`/api/tools/${id}/test`, params);
    return response.data;
  }

  // ========== Streaming Chat API ==========

  async sendMessageStream(
    message: string,
    onChunk: (chunk: {
      type: string;
      content?: string;
      done?: boolean;
      error?: string;
      session_id?: string;
      tool_call?: Record<string, unknown>;
      tool_name?: string;
      result?: unknown;
    }) => void,
    agentId?: string,
    images?: string[]
  ) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('cxhms-token') || ''}`,
        },
        body: JSON.stringify({
          message,
          agent_id: agentId || 'default',
          images: images && images.length > 0 ? images : undefined,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error');
        onChunk({ type: 'error', error: `HTTP ${response.status}: ${errorText}` });
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        onChunk({ type: 'error', error: 'No response body' });
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();

          if (value) {
            buffer += decoder.decode(value, { stream: true });
          }

          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.trim().startsWith('data: ')) {
              try {
                const data = JSON.parse(line.trim().slice(6));
                onChunk(data);
              } catch (e) {
                console.error('Failed to parse SSE data:', e);
              }
            }
          }

          if (done) {
            // 处理buffer中剩余的数据
            if (buffer.trim().startsWith('data: ')) {
              try {
                const data = JSON.parse(buffer.trim().slice(6));
                onChunk(data);
              } catch (e) {
                console.error('Failed to parse remaining buffer:', e);
              }
            }
            break;
          }
        }
      } catch (streamError) {
        onChunk({
          type: 'error',
          error: `Stream error: ${streamError instanceof Error ? streamError.message : 'Unknown error'}`,
        });
      } finally {
        reader.releaseLock();
      }
    } catch (fetchError) {
      onChunk({
        type: 'error',
        error: `Fetch error: ${fetchError instanceof Error ? fetchError.message : 'Unknown error'}`,
      });
    }
  }

  // ========== Batch Memory Operations APIs ==========

  async batchDeleteMemories(ids: number[], agentId?: string) {
    const response = await this.client.post('/api/memories/batch/delete', {
      ids,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async batchUpdateTags(
    ids: number[],
    tags: string[],
    operation: 'add' | 'remove' | 'set' = 'add',
    agentId?: string
  ) {
    const response = await this.client.post('/api/memories/batch/tags', {
      ids,
      tags,
      operation,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async batchArchiveMemories(ids: number[], agentId?: string) {
    const response = await this.client.post('/api/memories/batch/archive', {
      ids,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async batchRestoreMemories(ids: number[], agentId?: string) {
    const response = await this.client.post('/api/memories/batch/restore', {
      ids,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async batchUpdateMemories(
    ids: number[],
    data: { content?: string; tags?: string[]; importance?: number },
    agentId?: string
  ) {
    const response = await this.client.post('/api/memories/batch/update', {
      ids,
      data,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async batchTagByQuery(
    query: string,
    tags: string[],
    operation: 'add' | 'remove' | 'set' = 'add',
    agentId?: string
  ) {
    const response = await this.client.post('/api/memories/batch/tag-by-query', {
      query,
      tags,
      operation,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async batchDeleteByQuery(query: string, agentId?: string) {
    const response = await this.client.post('/api/memories/batch/delete-by-query', {
      query,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async batchArchiveByQuery(query: string, targetLevel: number = 1, agentId?: string) {
    const response = await this.client.post('/api/memories/batch/archive-by-query', {
      query,
      target_level: targetLevel,
      agent_id: agentId || 'default',
    });
    return response.data;
  }

  async getMemoriesByType(type: string, params?: { limit?: number; workspace_id?: string }) {
    const response = await this.client.get(`/api/memories/type/${type}`, { params });
    return response.data;
  }

  async searchByTag(tag: string, params?: { limit?: number; workspace_id?: string }) {
    const response = await this.client.get('/api/memories/search-by-tag', {
      params: { tag, ...params },
    });
    return response.data;
  }

  // ========== Memory Agent Streaming API ==========

  async sendMemoryAgentMessageStream(
    message: string,
    onChunk: (chunk: {
      type: string;
      content?: string;
      done?: boolean;
      error?: string;
      session_id?: string;
      tool_call?: Record<string, unknown>;
      tool_name?: string;
      result?: unknown;
      thinking?: string;
    }) => void
  ) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/memory-agent/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('cxhms-token') || ''}`,
        },
        body: JSON.stringify({ message }),
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error');
        onChunk({ type: 'error', error: `HTTP ${response.status}: ${errorText}` });
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        onChunk({ type: 'error', error: 'No response body' });
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.trim().startsWith('data: ')) {
              try {
                const data = JSON.parse(line.trim().slice(6));
                onChunk(data);
              } catch (e) {
                console.error('Failed to parse SSE data:', e);
              }
            }
          }
        }
      } catch (streamError) {
        onChunk({
          type: 'error',
          error: `Stream error: ${streamError instanceof Error ? streamError.message : 'Unknown error'}`,
        });
      } finally {
        reader.releaseLock();
      }
    } catch (fetchError) {
      onChunk({
        type: 'error',
        error: `Fetch error: ${fetchError instanceof Error ? fetchError.message : 'Unknown error'}`,
      });
    }
  }

  // ========== Models API ==========

  async getAvailableModels() {
    const response = await this.client.get('/api/service/models');
    return response.data;
  }

  // ========== Gateway WebSocket Actions ==========

  // Emotions API
  async getEmotions() {
    const response = await this.client.get('/api/emotions');
    return response.data;
  }

  async listEmotions(params?: { category?: string; active_only?: boolean }) {
    const response = await this.client.get('/api/emotions/list', { params });
    return response.data;
  }

  // Effects API
  async getEffects() {
    const response = await this.client.get('/api/effects');
    return response.data;
  }

  async listEffects(params?: { type?: string; active_only?: boolean }) {
    const response = await this.client.get('/api/effects/list', { params });
    return response.data;
  }

  // ASR API
  async speechToText(audioData: Blob, options?: {
    language?: string;
    model?: string;
    timestamp_granularities?: string[];
  }) {
    const formData = new FormData();
    formData.append('file', audioData, 'audio.webm');
    if (options?.language) formData.append('language', options.language);
    if (options?.model) formData.append('model', options.model);
    if (options?.timestamp_granularities) {
      formData.append('timestamp_granularities', JSON.stringify(options.timestamp_granularities));
    }

    const response = await this.client.post('/api/asr/speech-to-text', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  }

  // TTS API
  async textToSpeech(text: string, options?: {
    voice?: string;
    model?: string;
    speed?: number;
    response_format?: string;
  }) {
    const response = await this.client.post('/api/tts/synthesize', {
      text,
      ...options,
    });
    
    // Gateway 返回 JSON 格式：{ status: "success", audio_data: base64, format: "wav" }
    if (response.data && response.data.audio_data) {
      // 将 base64 转换为 Blob
      const binaryString = atob(response.data.audio_data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      return new Blob([bytes], { type: `audio/${response.data.format || 'wav'}` });
    }
    
    // 如果返回的是直接 Blob（备用路径）
    return response.data;
  }

  async synthesizeStream(
    text: string,
    onChunk: (chunk: {
      type: string;
      audio?: string;
      done?: boolean;
      error?: string;
    }) => void,
    options?: {
      voice?: string;
      model?: string;
      speed?: number;
    }
  ) {
    try {
      const response = await fetch(`${API_BASE_URL}/api/tts/synthesize-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('cxhms-token') || ''}`,
        },
        body: JSON.stringify({
          text,
          ...options,
        }),
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error');
        onChunk({ type: 'error', error: `HTTP ${response.status}: ${errorText}` });
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        onChunk({ type: 'error', error: 'No response body' });
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      try {
        while (true) {
          const { done, value } = await reader.read();

          if (value) {
            buffer += decoder.decode(value, { stream: true });
          }

          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.trim().startsWith('data: ')) {
              try {
                const data = JSON.parse(line.trim().slice(6));
                onChunk(data);
              } catch (e) {
                console.error('Failed to parse SSE data:', e);
              }
            }
          }

          if (done) {
            if (buffer.trim().startsWith('data: ')) {
              try {
                const data = JSON.parse(buffer.trim().slice(6));
                onChunk(data);
              } catch (e) {
                console.error('Failed to parse remaining buffer:', e);
              }
            }
            break;
          }
        }
      } catch (streamError) {
        onChunk({
          type: 'error',
          error: `Stream error: ${streamError instanceof Error ? streamError.message : 'Unknown error'}`,
        });
      } finally {
        reader.releaseLock();
      }
    } catch (fetchError) {
      onChunk({
        type: 'error',
        error: `Fetch error: ${fetchError instanceof Error ? fetchError.message : 'Unknown error'}`,
      });
    }
  }

  // ========== Audio Config API ==========

  async getAudioConfig() {
    const response = await this.client.get('/api/config/audio');
    return response.data;
  }

  async getStats() {
    const response = await this.client.get('/api/stats');
    return response.data;
  }

  async updateAudioConfig(config: {
    ref_audio_path?: string;
    ref_text?: string;
    speed?: number;
    cross_fade_duration?: number;
    emotion_enabled?: boolean;
    effects_enabled?: boolean;
    emotion_voices?: Record<string, { ref_audio: string; ref_text: string }>;
  }) {
    const response = await this.client.post('/api/config/audio', config);
    return response.data;
  }

  // ========== Audio File API ==========

  async getAudioFiles() {
    const response = await this.client.get('/api/audio/files');
    return response.data;
  }

  async uploadAudioFile(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    const response = await this.client.post('/api/audio/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  }

  async deleteAudioFile(filename: string) {
    const response = await this.client.delete(`/api/audio/files/${filename}`);
    return response.data;
  }

  getAudioFileUrl(filename: string) {
    return `${API_BASE_URL}/api/audio/files/${filename}`;
  }

  // ========== IndexTTS 2 API ==========

  async getIndexTTSStatus() {
    const response = await this.client.get('/api/index-tts/status');
    return response.data;
  }

  async synthesizeWithIndexTTS(data: {
    text: string;
    ref_audio?: string;
    format?: string;
    speed?: number;
    vol?: number;
    pitch?: number;
    top_p?: number;
    top_k?: number;
    temperature?: number;
    guide?: boolean;
    guide_audio?: string;
    batch_size?: number;
    seed?: number;
  }) {
    const response = await this.client.post('/api/index-tts/synthesize', data, {
      timeout: 600000,
    });
    return response.data;
  }

  // ========== Audio Generation API ==========

  async generateEmotionAudios(data: {
    ref_audio: string;
    ref_text?: string;
    emotions?: { type: string; intensity: number }[];
    template?: string;
    auto_full?: boolean;
  }) {
    const response = await this.client.post('/api/audio/generate-emotions', data, {
      timeout: 600000,
    });
    return response.data;
  }

  async getEmotionConfigs() {
    const response = await this.client.get('/api/audio/emotions/list');
    return response.data;
  }

  // ========== Live/Danmaku Config API ==========

  async getDanmakuConfig() {
    const response = await this.client.get('/api/config/danmaku');
    return response.data;
  }

  async updateDanmakuConfig(config: {
    websocket?: {
      endpoint?: string;
      max_connections?: number;
    };
    sources?: {
      bilibili?: { enabled?: boolean; websocket_url?: string };
      rdf?: { enabled?: boolean; websocket_url?: string };
    };
  }) {
    const response = await this.client.post('/api/config/danmaku', config);
    return response.data;
  }

  async getFirewallConfig() {
    const response = await this.client.get('/api/config/firewall');
    return response.data;
  }

  async updateFirewallConfig(config: {
    llm?: { default_model?: string };
    blocking?: { blacklist_enabled?: boolean; blacklist?: string[] };
    decision?: { confidence_threshold?: number; timeout_ms?: number };
  }) {
    const response = await this.client.post('/api/config/firewall', config);
    return response.data;
  }

  async getFirewallV3Config() {
    const response = await this.client.get('/api/config/firewall_v3');
    return response.data;
  }

  async updateFirewallV3Config(config: {
    interrupt?: {
      enabled?: boolean;
      mode?: 'main_llm' | 'independent_llm';
      main_llm?: { enabled?: boolean; prompt?: string };
      independent_llm?: { enabled?: boolean; model?: string };
    };
  }) {
    const response = await this.client.post('/api/config/firewall_v3', config);
    return response.data;
  }

  async getLiveClientStatus() {
    const response = await this.client.get('/api/live/status');
    return response.data;
  }

  async connectLiveClient(data: {
    client_type?: string;
    room_id?: string;
    supported_markers?: string[];
    marker_config?: Record<string, unknown>;
  }) {
    const response = await this.client.post('/api/live/connect', data);
    return response.data;
  }

  async disconnectLiveClient(client_id: string) {
    const response = await this.client.delete(`/api/live/disconnect/${client_id}`);
    return response.data;
  }

  async getVadConfig() {
    const response = await this.client.get('/api/config/vad');
    return response.data;
  }

  async updateVadConfig(config: {
    vad?: {
      mode?: 'energy' | 'webrtc' | 'silero';
      sample_rate?: number;
      frame_duration_ms?: number;
      energy_threshold?: number;
      silence_threshold_ms?: number;
      speech_threshold_ms?: number;
    };
    audio_stream?: {
      asr_interval_ms?: number;
      buffer_duration_ms?: number;
    };
    agent_interrupt?: {
      enabled?: boolean;
      interrupt_threshold_ms?: number;
      min_speech_duration_ms?: number;
      interrupt_cooldown_ms?: number;
    };
  }) {
    const response = await this.client.post('/api/config/vad', config);
    return response.data;
  }

  // ========== Graph Database APIs ==========

  async getGraphConfig() {
    const response = await this.client.get('/api/graph/config');
    return response.data;
  }

  async updateGraphConfig(config: {
    graph_enabled?: boolean;
    graph_backend?: string;
    neo4j?: {
      uri?: string;
      user?: string;
      password?: string;
      database?: string;
      max_connection_pool_size?: number;
    };
    graph_libraries?: Record<string, { enabled?: boolean; label_prefix?: string }>;
  }) {
    const response = await this.client.post('/api/graph/config', config);
    return response.data;
  }

  async getGraphStatus() {
    const response = await this.client.get('/api/graph/status');
    return response.data;
  }

  async getGraphHealth() {
    const response = await this.client.get('/api/graph/health');
    return response.data;
  }

  async testGraphConnection(config?: {
    uri?: string;
    user?: string;
    password?: string;
    database?: string;
    max_connection_pool_size?: number;
  }) {
    const response = await this.client.post('/api/graph/test-connection', config);
    return response.data;
  }

  async getGraphLibraryStats(library: string) {
    const response = await this.client.get(`/api/graph/stats/${library}`);
    return response.data;
  }

  async exportGraphLibrary(library: string) {
    const response = await this.client.post(`/api/graph/export/${library}`);
    return response.data;
  }

  // ========== Graph Data Management APIs ==========

  async listGraphEntities(library: string, params?: {
    entity_type?: string;
    search?: string;
    limit?: number;
    offset?: number;
  }) {
    const response = await this.client.get(`/api/graph/${library}/entities`, { params });
    return response.data;
  }

  async getGraphEntity(library: string, entityId: string) {
    const response = await this.client.get(`/api/graph/${library}/entities/${entityId}`);
    return response.data;
  }

  async createGraphEntity(library: string, data: {
    entity_id: string;
    name: string;
    entity_type: string;
    properties?: Record<string, unknown>;
    memory_ids?: string[];
  }) {
    const response = await this.client.post(`/api/graph/${library}/entities`, data);
    return response.data;
  }

  async updateGraphEntity(library: string, entityId: string, data: {
    name?: string;
    properties?: Record<string, unknown>;
    memory_ids?: string[];
  }) {
    const response = await this.client.put(`/api/graph/${library}/entities/${entityId}`, data);
    return response.data;
  }

  async deleteGraphEntity(library: string, entityId: string, hard: boolean = false) {
    const response = await this.client.delete(`/api/graph/${library}/entities/${entityId}`, {
      params: { hard },
    });
    return response.data;
  }

  async getGraphEntityRelations(library: string, entityId: string, params?: {
    relation_type?: string;
    depth?: number;
  }) {
    const response = await this.client.get(`/api/graph/${library}/entities/${entityId}/relations`, { params });
    return response.data;
  }

  async listGraphRelations(library: string, params?: {
    relation_type?: string;
    limit?: number;
    offset?: number;
  }) {
    const response = await this.client.get(`/api/graph/${library}/relations`, { params });
    return response.data;
  }

  async createGraphRelation(library: string, data: {
    from_entity: string;
    to_entity: string;
    relation_type: string;
    strength?: number;
    evidence_memory_ids?: string[];
  }) {
    const response = await this.client.post(`/api/graph/${library}/relations`, data);
    return response.data;
  }

  async deleteGraphRelation(library: string, params: {
    from_entity: string;
    to_entity: string;
    relation_type: string;
    hard?: boolean;
  }) {
    const response = await this.client.delete(`/api/graph/${library}/relations`, { params });
    return response.data;
  }

  async getGraphEntityTypes(library: string) {
    const response = await this.client.get(`/api/graph/${library}/entity-types`);
    return response.data;
  }

  async getGraphRelationTypes(library: string) {
    const response = await this.client.get(`/api/graph/${library}/relation-types`);
    return response.data;
  }

  async findGraphPath(library: string, params: {
    start_entity: string;
    end_entity: string;
    max_depth?: number;
  }) {
    const response = await this.client.get(`/api/graph/${library}/path`, { params });
    return response.data;
  }

  // ========== Vector Database Management APIs ==========

  async getVectorConfig() {
    const response = await this.client.get('/api/vector/config');
    return response.data;
  }

  async getVectorStatus() {
    const response = await this.client.get('/api/vector/status');
    return response.data;
  }

  async getVectorHealth() {
    const response = await this.client.get('/api/vector/health');
    return response.data;
  }

  async listVectors(params?: {
    limit?: number;
    offset?: number;
    memory_type?: string;
  }) {
    const response = await this.client.get('/api/vector/vectors', { params });
    return response.data;
  }

  async getVector(memoryId: number) {
    const response = await this.client.get(`/api/vector/vectors/${memoryId}`);
    return response.data;
  }

  async deleteVector(memoryId: number) {
    const response = await this.client.delete(`/api/vector/vectors/${memoryId}`);
    return response.data;
  }

  async syncVectors() {
    const response = await this.client.post('/api/vector/sync');
    return response.data;
  }

  async rebuildVectors() {
    const response = await this.client.post('/api/vector/rebuild');
    return response.data;
  }

  async searchVectors(params: {
    query: string;
    limit?: number;
    min_score?: number;
    memory_type?: string;
  }) {
    const response = await this.client.post('/api/vector/search', null, { params });
    return response.data;
  }

  async getVectorStats() {
    const response = await this.client.get('/api/vector/stats');
    return response.data;
  }
}

export const api = new ApiClient();
