import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockPatch = vi.fn();
const mockDelete = vi.fn();

const mockRequest = vi.fn(async (config: { url?: string; method?: string; data?: unknown; params?: unknown }) => {
  const method = (config.method || 'get').toLowerCase();
  const url = config.url || '';
  const paramsObj = config.params as Record<string, unknown> | undefined;
  const hasParams = paramsObj && Object.keys(paramsObj).length > 0;
  if (method === 'get') return hasParams ? mockGet(url, { params: config.params }) : mockGet(url);
  if (method === 'post') return mockPost(url, config.data);
  if (method === 'put') return mockPut(url, config.data);
  if (method === 'patch') return mockPatch(url, config.data);
  if (method === 'delete') return hasParams ? mockDelete(url, { params: config.params }) : mockDelete(url);
  return hasParams ? mockGet(url, { params: config.params }) : mockGet(url);
});

vi.mock('axios', () => {
  class MockAxiosError extends Error {
    response?: unknown;
    config?: unknown;
    constructor(message?: string) {
      super(message);
      this.name = 'AxiosError';
    }
  }
  return {
    default: {
      create: vi.fn(() => ({
        request: mockRequest,
        get: mockGet,
        post: mockPost,
        put: mockPut,
        delete: mockDelete,
        interceptors: {
          request: { use: vi.fn() },
          response: { use: vi.fn() },
        },
      })),
    },
    AxiosError: MockAxiosError,
  };
});

describe('API Client', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let api: any;

  beforeEach(async () => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
    mockPut.mockReset();
    mockPatch.mockReset();
    mockDelete.mockReset();
    mockRequest.mockReset();
    mockRequest.mockImplementation(async (config: { url?: string; method?: string; data?: unknown; params?: unknown }) => {
      const method = (config.method || 'get').toLowerCase();
      const url = config.url || '';
      const paramsObj = config.params as Record<string, unknown> | undefined;
      const hasParams = paramsObj && Object.keys(paramsObj).length > 0;
      if (method === 'get') return hasParams ? mockGet(url, { params: config.params }) : mockGet(url);
      if (method === 'post') return mockPost(url, config.data);
      if (method === 'put') return mockPut(url, config.data);
      if (method === 'patch') return mockPatch(url, config.data);
      if (method === 'delete') return hasParams ? mockDelete(url, { params: config.params }) : mockDelete(url);
      return hasParams ? mockGet(url, { params: config.params }) : mockGet(url);
    });
    localStorage.clear();

    api = await import('./client').then((m) => m.api);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('Health Check', () => {
    it('should check health successfully', async () => {
      const mockResponse = { status: 'healthy', service: 'CXHMS' };
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      const result = await api.getHealth();
      expect(result).toEqual(mockResponse);
      expect(mockGet).toHaveBeenCalledWith('/health');
    });
  });

  describe('Chat API', () => {
    it('should send message successfully', async () => {
      const mockResponse = {
        status: 'success',
        response: 'AI response',
        session_id: 'session-1',
      };
      mockPost.mockResolvedValueOnce({ data: mockResponse });

      const result = await api.sendMessage('Hello', 'default', 'agent-1');
      expect(result).toEqual({ response: 'AI response', session_id: 'session-1' });
    });

    it('should get chat history', async () => {
      const mockHistory = {
        messages: [
          { id: '1', role: 'user', content: 'Hello' },
          { id: '2', role: 'assistant', content: 'Hi!' },
        ],
      };
      mockGet.mockResolvedValueOnce({ data: mockHistory });

      const result = await api.getChatHistory('session-1');
      expect(result.messages).toHaveLength(2);
    });

    it('should create session', async () => {
      const mockSession = { status: 'success', session_id: 'new-session', message: 'ok' };
      mockPost.mockResolvedValueOnce({ data: mockSession });

      const result = await api.createSession('New Chat');
      expect(result.session_id).toBe('new-session');
    });

    it('should get sessions', async () => {
      const mockSessions = [
        { id: '1', title: 'Chat 1' },
        { id: '2', title: 'Chat 2' },
      ];
      mockGet.mockResolvedValueOnce({ data: { sessions: mockSessions } });

      const result = await api.getSessions();
      expect(result).toHaveLength(2);
    });

    it('should delete session', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteSession('session-1');
      expect(mockDelete).toHaveBeenCalledWith('/api/context/sessions/session-1');
    });
  });

  describe('Agent API', () => {
    it('should get all agents', async () => {
      const mockAgents = [{ id: 'default', name: 'Default Agent' }];
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agents: mockAgents, total: 1 } });

      const result = await api.getAgents();
      expect(result).toHaveLength(1);
    });

    it('should get agent by id', async () => {
      const mockAgent = { id: 'default', name: 'Default Agent' };
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agent: mockAgent } });

      const result = await api.getAgent('default');
      expect(result.id).toBe('default');
    });

    it('should create agent', async () => {
      const mockAgent = { id: 'new-agent', name: 'New Agent' };
      mockPost.mockResolvedValueOnce({ data: { status: 'success', agent: mockAgent, message: 'ok' } });

      const result = await api.createAgent({ name: 'New Agent' });
      expect(result.id).toBe('new-agent');
    });

    it('should update agent', async () => {
      const mockAgent = { id: 'default', name: 'Updated Agent' };
      mockPut.mockResolvedValueOnce({ data: { status: 'success', agent: mockAgent, message: 'ok' } });

      const result = await api.updateAgent('default', { name: 'Updated Agent' });
      expect(result.name).toBe('Updated Agent');
    });

    it('should delete agent', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteAgent('agent-1');
      expect(mockDelete).toHaveBeenCalledWith('/api/agents/agent-1');
    });

    it('should clone agent', async () => {
      const mockClonedAgent = { id: 'cloned-agent', name: 'Default Agent (Copy)' };
      mockPost.mockResolvedValueOnce({ data: { status: 'success', agent: mockClonedAgent, message: 'ok' } });

      const result = await api.cloneAgent('default');
      expect(result.id).toBe('cloned-agent');
    });
  });

  describe('Memory API', () => {
    it('should get all memories', async () => {
      const mockResponse = {
        memories: [{ id: '1', content: 'Test memory' }],
        total: 1,
      };
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      const result = await api.getMemories();
      expect(result.memories).toHaveLength(1);
      expect(result.total).toBe(1);
    });

    it('should get memories with params', async () => {
      const mockResponse = { memories: [], total: 0 };
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      await api.getMemories({ type: 'long_term', limit: 10, offset: 0 });
      expect(mockGet).toHaveBeenCalledWith('/api/memories', {
        params: { type: 'long_term', limit: 10, offset: 0 },
      });
    });

    it('should create memory', async () => {
      const mockMemory = { id: '1', content: 'New memory' };
      mockPost.mockResolvedValueOnce({ data: mockMemory });

      const result = await api.createMemory({ content: 'New memory' });
      expect(result.content).toBe('New memory');
    });

    it('should create memory with all fields', async () => {
      const mockMemory = {
        id: '1',
        content: 'New memory',
        type: 'long_term',
        importance: 4,
        tags: ['tag1'],
      };
      mockPost.mockResolvedValueOnce({ data: mockMemory });

      const result = await api.createMemory({
        content: 'New memory',
        type: 'long_term',
        importance: 4,
        tags: ['tag1'],
      });
      expect(result.type).toBe('long_term');
      expect(result.importance).toBe(4);
    });

    it('should update memory', async () => {
      const mockMemory = { id: 1, content: 'Updated memory' };
      mockPut.mockResolvedValueOnce({ data: mockMemory });

      const result = await api.updateMemory(1, { content: 'Updated memory' });
      expect(result.content).toBe('Updated memory');
    });

    it('should delete memory', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteMemory(1);
      expect(mockDelete).toHaveBeenCalled();
    });

    it('should delete memory with hard delete', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteMemory(1, false);
      expect(mockDelete).toHaveBeenCalledWith('/api/memories/1', {
        params: { soft: false },
      });
    });

    it('should search memories', async () => {
      const mockResults = { memories: [{ id: '1', content: 'Test', score: 0.9 }] };
      mockPost.mockResolvedValueOnce({ data: mockResults });

      const result = await api.searchMemories('test query');
      expect(result.memories).toHaveLength(1);
    });

    it('should semantic search memories', async () => {
      const mockResults = { results: [{ id: '1', content: 'Test', score: 0.95 }] };
      mockPost.mockResolvedValueOnce({ data: mockResults });

      const result = await api.semanticSearch('test query', { limit: 5, min_score: 0.8 });
      expect(result.results).toHaveLength(1);
    });

    it('should get memories by type', async () => {
      const mockResponse = { memories: [{ id: '1', type: 'long_term' }] };
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      await api.getMemoriesByType('long_term', { limit: 10 });
      expect(mockGet).toHaveBeenCalledWith('/api/memories/type/long_term', {
        params: { limit: 10 },
      });
    });

    it('should search by tag', async () => {
      const mockResponse = { memories: [{ id: '1', tags: ['important'] }] };
      mockPost.mockResolvedValueOnce({ data: mockResponse });

      await api.searchByTag('important', { limit: 10 });
      expect(mockPost).toHaveBeenCalledWith('/api/memories/tag', { tag: 'important', limit: 10 });
    });
  });

  describe('ACP API', () => {
    it('should get ACP stats', async () => {
      const mockStats = { total_agents: 5, online_agents: 3, total_messages: 10 };
      mockGet.mockResolvedValueOnce({ data: { status: 'success', statistics: mockStats } });

      const result = await api.getAcpStats();
      expect(result.total_agents).toBe(5);
      expect(result.total_conversations).toBe(10);
    });

    it('should get ACP agents', async () => {
      const mockAgents = [{ id: 'agent-1', name: 'Agent 1', status: 'online', capabilities: [] }];
      mockGet.mockResolvedValueOnce({ data: { agents: mockAgents } });

      const result = await api.getAcpAgents();
      expect(result).toHaveLength(1);
      expect(result[0].name).toBe('Agent 1');
    });

    it('should create ACP agent', async () => {
      mockPost.mockResolvedValueOnce({ data: { status: 'success' } });

      await api.createAcpAgent({ name: 'New Agent', capabilities: ['chat'] });
      expect(mockPost).toHaveBeenCalledWith('/api/acp/agents', {
        name: 'New Agent',
        description: '',
        capabilities: ['chat'],
        host: '127.0.0.1',
        port: 0,
      });
    });

    it('should update ACP agent', async () => {
      mockPatch.mockResolvedValueOnce({ data: { status: 'success' } });

      await api.updateAcpAgent('agent-1', { name: 'Updated Agent' });
      expect(mockPatch).toHaveBeenCalled();
    });

    it('should delete ACP agent', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteAcpAgent('agent-1');
      expect(mockDelete).toHaveBeenCalledWith('/api/acp/agents/agent-1');
    });
  });

  describe('Tools API', () => {
    it('should get tools stats', async () => {
      const mockStats = { total_tools: 10, active_tools: 8, enabled_tools: 8, mcp_tools: 2, native_tools: 3, total_calls: 1 };
      mockGet.mockResolvedValueOnce({ data: { status: 'success', statistics: mockStats } });

      const result = await api.getToolsStats();
      expect(result.total_tools).toBe(10);
    });

    it('should get all tools', async () => {
      const mockTools = { t1: { name: 'Tool 1', type: 'mcp' } };
      mockGet.mockResolvedValueOnce({ data: { tools: mockTools } });

      const result = await api.getTools();
      expect(Object.keys(result.tools)).toHaveLength(1);
    });

    it('should get tools by type', async () => {
      const mockTools = { t1: { name: 'Tool 1', type: 'mcp' } };
      mockGet.mockResolvedValueOnce({ data: { tools: mockTools } });

      await api.getTools('mcp');
      expect(mockGet).toHaveBeenCalledWith('/api/tools', { params: { category: 'mcp' } });
    });

    it('should create tool', async () => {
      mockPost.mockResolvedValueOnce({ data: { status: 'success' } });

      await api.createTool({ name: 'New Tool', type: 'mcp' });
      expect(mockPost).toHaveBeenCalled();
    });

    it('should update tool', async () => {
      mockPatch.mockResolvedValueOnce({ data: { status: 'success' } });

      await api.updateTool('tool-1', { name: 'Updated Tool' });
      expect(mockPatch).toHaveBeenCalled();
    });

    it('should delete tool', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteTool('tool-1');
      expect(mockDelete).toHaveBeenCalledWith('/api/tools/tool-1');
    });

    it('should test tool', async () => {
      const mockResult = { status: 'success', result: { ok: true } };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.testTool('tool-1', { param: 'value' });
      expect(result.result).toEqual({ ok: true });
    });
  });

  describe('Archive API', () => {
    it('should get archive stats', async () => {
      const mockStats = {
        total_archived: 100,
        archive_level_counts: { 1: 50, 2: 30, 3: 20 },
        merge_count: 0,
        duplicate_count: 0,
      };
      mockGet.mockResolvedValueOnce({ data: { status: 'success', statistics: mockStats } });

      const result = await api.getArchiveStats();
      expect(result.total_archived).toBe(100);
    });

    it('should archive memory', async () => {
      mockPost.mockResolvedValueOnce({ data: { status: 'success' } });

      await api.archiveMemory(1, 2);
      expect(mockPost).toHaveBeenCalledWith('/api/archive/memory', {
        memory_id: 1,
        target_level: 2,
      });
    });

    it('should merge memories', async () => {
      const mockResult = { success: true, merged_memory_id: 10 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.mergeMemories([1, 2, 3]);
      expect(result.success).toBe(true);
      expect(result.merged_memory_id).toBe(10);
    });

    it('should detect duplicates', async () => {
      const mockResult = { duplicate_groups: [{ ids: [1, 2] }] };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.detectDuplicates();
      expect(result.duplicate_groups).toHaveLength(1);
    });

    it('should auto archive process', async () => {
      const mockResult = {
        results: { archived: [], merged: [], errors: [] },
        summary: { archived_count: 15, merged_count: 2, error_count: 0 },
      };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.autoArchiveProcess();
      expect(result.summary?.archived_count).toBe(15);
    });
  });

  describe('Service API', () => {
    it('should get service status', async () => {
      const mockStatus = { status: 'running' };
      mockGet.mockResolvedValueOnce({ data: mockStatus });

      const result = await api.getServiceStatus();
      expect(result.status).toBe('running');
    });

    it('should start service', async () => {
      const mockResult = { status: 'started' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.startService({ port: 8000 });
      expect(result.status).toBe('started');
    });

    it('should stop service', async () => {
      const mockResult = { status: 'stopped' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.stopService();
      expect(result.status).toBe('stopped');
    });

    it('should restart service', async () => {
      const mockResult = { status: 'restarted' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.restartService({ port: 8000 });
      expect(result.status).toBe('restarted');
    });

    it('should get service logs', async () => {
      const mockLogs = { logs: 'line 1\nline 2' };
      mockGet.mockResolvedValueOnce({ data: mockLogs });

      await api.getServiceLogs(50);
      expect(mockGet).toHaveBeenCalledWith('/api/service/logs', { params: { lines: 50 } });
    });

    it('should get service config', async () => {
      const mockConfig = { port: 8000, log_level: 'info' };
      mockGet.mockResolvedValueOnce({ data: mockConfig });

      const result = await api.getServiceConfig();
      expect(result.port).toBe(8000);
    });

    it('should update service config', async () => {
      mockPut.mockResolvedValueOnce({ data: {} });

      await api.updateServiceConfig({ log_level: 'debug' });
      expect(mockPut).toHaveBeenCalledWith('/api/service/config', { log_level: 'debug' });
    });

    it('should get environment info', async () => {
      const mockEnv = { python_version: '3.11', platform: 'linux' };
      mockGet.mockResolvedValueOnce({ data: mockEnv });

      const result = await api.getEnvironmentInfo();
      expect(result.python_version).toBe('3.11');
    });
  });

  describe('Control Service API', () => {
    it('should get control service health', async () => {
      const mockHealth = { status: 'healthy', service: 'control' };
      mockGet.mockResolvedValueOnce({ data: mockHealth });

      const result = await api.getControlServiceHealth();
      expect(result.status).toBe('healthy');
    });

    it('should start main backend', async () => {
      const mockResult = { status: 'started' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.startMainBackend();
      expect(result.status).toBe('started');
    });

    it('should stop main backend', async () => {
      const mockResult = { status: 'stopped' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.stopMainBackend();
      expect(result.status).toBe('stopped');
    });

    it('should restart main backend', async () => {
      const mockResult = { status: 'restarted' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.restartMainBackend();
      expect(result.status).toBe('restarted');
    });
  });

  describe('Batch Operations API', () => {
    it('should batch delete memories', async () => {
      mockPost.mockResolvedValueOnce({ data: {} });

      await api.batchDeleteMemories([1, 2, 3]);
      expect(mockPost).toHaveBeenCalledWith('/api/memories/batch-delete', { ids: [1, 2, 3] });
    });

    it('should batch update tags', async () => {
      mockPost.mockResolvedValueOnce({ data: {} });

      await api.batchUpdateTags([1, 2, 3, 4, 5], ['tag1', 'tag2'], 'add');
      expect(mockPost).toHaveBeenCalledWith('/api/memories/batch-update-tags', {
        ids: [1, 2, 3, 4, 5],
        tags: ['tag1', 'tag2'],
        operation: 'add',
      });
    });

    it('should batch archive memories', async () => {
      mockPost.mockResolvedValueOnce({ data: {} });

      await api.batchArchiveMemories([1, 2]);
      expect(mockPost).toHaveBeenCalledWith('/api/memories/batch-archive', { ids: [1, 2] });
    });

    it('should batch restore memories', async () => {
      mockPost.mockResolvedValueOnce({ data: {} });

      await api.batchRestoreMemories([1, 2]);
      expect(mockPost).toHaveBeenCalledWith('/api/memories/batch-restore', { ids: [1, 2] });
    });

    it('should batch update memories', async () => {
      mockPost.mockResolvedValueOnce({ data: {} });

      await api.batchUpdateMemories([1, 2, 3], { importance: 5 });
      expect(mockPost).toHaveBeenCalledWith('/api/memories/batch-update', {
        ids: [1, 2, 3],
        updates: { importance: 5 },
      });
    });

    it('should batch tag by query', async () => {
      const mockResult = { updated: 10 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchTagByQuery('python', ['programming'], 'add');
      expect(result.updated).toBe(10);
    });

    it('should batch delete by query', async () => {
      const mockResult = { success: true, deleted: 5 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchDeleteByQuery('test');
      expect(result.deleted).toBe(5);
    });

    it('should batch archive by query', async () => {
      const mockResult = { success: true, archived: 3 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchArchiveByQuery('old', 2);
      expect(result.archived).toBe(3);
    });
  });

  describe('Memory Chat API', () => {
    it('should send memory chat message', async () => {
      const mockResponse = { response: 'Memory agent response', session_id: 'session-1' };
      mockPost.mockResolvedValueOnce({ data: mockResponse });

      const result = await api.memoryChat('What do you know about me?', 'session-1');
      expect(result.response).toBe('Memory agent response');
      expect(mockPost).toHaveBeenCalledWith('/api/memory-chat', {
        message: 'What do you know about me?',
        session_id: 'session-1',
      });
    });
  });

  describe('Admin API', () => {
    it('should get stats', async () => {
      const mockStats = { total_memories: 100, total_sessions: 50, total_agents: 3, archived_memories: 10, total_messages: 500 };
      mockGet.mockResolvedValueOnce({ data: { status: 'success', data: mockStats } });

      const result = await api.getStats();
      expect(result.total_memories).toBe(100);
      expect(result.total_messages).toBe(500);
    });
  });

  describe('Error Handling', () => {
    it('should handle network error', async () => {
      mockGet.mockRejectedValueOnce(new Error('Network Error'));

      await expect(api.getHealth()).rejects.toThrow('Network Error');
    });

    it('should handle 404 error', async () => {
      const error = new Error('Not Found') as Error & { response: { status: number } };
      error.response = { status: 404 };
      mockGet.mockRejectedValueOnce(error);

      await expect(api.getAgent('non-existent')).rejects.toThrow();
    });

    it('should handle 500 error', async () => {
      const error = new Error('Internal Server Error') as Error & { response: { status: number } };
      error.response = { status: 500 };
      mockGet.mockRejectedValueOnce(error);

      await expect(api.getMemories()).rejects.toThrow();
    });
  });

  describe('Cache Functionality', () => {
    it('should fetch sessions on each call (sessions list is not cached)', async () => {
      const mockSessions = [{ id: '1', title: 'Session 1' }];
      mockGet.mockResolvedValue({ data: { sessions: mockSessions } });

      await api.getSessions();
      await api.getSessions();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should cache agents response', async () => {
      const mockAgents = [{ id: 'default', name: 'Default' }];
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agents: mockAgents, total: 1 } });

      await api.getAgents();
      await api.getAgents();

      expect(mockGet).toHaveBeenCalledTimes(1);
    });

    it('should fetch single agent on each call (no cache)', async () => {
      const mockAgent = { id: 'default', name: 'Default Agent' };
      mockGet.mockResolvedValue({ data: { status: 'success', agent: mockAgent } });

      await api.getAgent('default');
      await api.getAgent('default');

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on session creation', async () => {
      mockGet.mockResolvedValueOnce({ data: { sessions: [] } });
      mockPost.mockResolvedValueOnce({ data: { status: 'success', session_id: 'new' } });
      mockGet.mockResolvedValueOnce({ data: { sessions: [{ id: 'new', title: 'New' }] } });

      await api.getSessions();
      await api.createSession('New');
      await api.getSessions();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on session deletion', async () => {
      mockGet.mockResolvedValueOnce({ data: { sessions: [{ id: '1', title: 'S' }] } });
      mockDelete.mockResolvedValueOnce({ data: {} });
      mockGet.mockResolvedValueOnce({ data: { sessions: [] } });

      await api.getSessions();
      await api.deleteSession('1');
      await api.getSessions();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on agent creation', async () => {
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agents: [], total: 0 } });
      mockPost.mockResolvedValueOnce({
        data: { status: 'success', agent: { id: 'new', name: 'New' }, message: 'ok' },
      });
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agents: [{ id: 'new', name: 'New' }], total: 1 } });

      await api.getAgents();
      await api.createAgent({ name: 'New' });
      await api.getAgents();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on agent update', async () => {
      const agentBefore = { id: 'default', name: 'Default' };
      const agentAfter = { id: 'default', name: 'Updated' };
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agent: agentBefore } });
      mockPut.mockResolvedValueOnce({ data: { status: 'success', agent: agentAfter, message: 'ok' } });
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agent: agentAfter } });

      await api.getAgent('default');
      await api.updateAgent('default', { name: 'Updated' });
      await api.getAgent('default');

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on agent deletion', async () => {
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agents: [{ id: 'agent-1', name: 'A' }], total: 1 } });
      mockDelete.mockResolvedValueOnce({ data: {} });
      mockGet.mockResolvedValueOnce({ data: { status: 'success', agents: [], total: 0 } });

      await api.getAgents();
      await api.deleteAgent('agent-1');
      await api.getAgents();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });
  });
});
