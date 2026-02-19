import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPut = vi.fn();
const mockDelete = vi.fn();

vi.mock('axios', () => ({
  default: {
    create: vi.fn(() => ({
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
}));

describe('API Client', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let api: any;

  beforeEach(async () => {
    vi.resetModules();
    mockGet.mockReset();
    mockPost.mockReset();
    mockPut.mockReset();
    mockDelete.mockReset();
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
      expect(result).toEqual(mockResponse);
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
      const mockSession = { id: 'new-session', title: 'New Chat' };
      mockPost.mockResolvedValueOnce({ data: mockSession });

      const result = await api.createSession('New Chat');
      expect(result.id).toBe('new-session');
    });

    it('should get sessions', async () => {
      const mockSessions = [
        { id: '1', title: 'Chat 1' },
        { id: '2', title: 'Chat 2' },
      ];
      mockGet.mockResolvedValueOnce({ data: mockSessions });

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
      mockGet.mockResolvedValueOnce({ data: mockAgents });

      const result = await api.getAgents();
      expect(result).toHaveLength(1);
    });

    it('should get agent by id', async () => {
      const mockAgent = { id: 'default', name: 'Default Agent' };
      mockGet.mockResolvedValueOnce({ data: mockAgent });

      const result = await api.getAgent('default');
      expect(result.id).toBe('default');
    });

    it('should create agent', async () => {
      const mockAgent = { id: 'new-agent', name: 'New Agent' };
      mockPost.mockResolvedValueOnce({ data: mockAgent });

      const result = await api.createAgent({ name: 'New Agent' });
      expect(result.id).toBe('new-agent');
    });

    it('should update agent', async () => {
      const mockAgent = { id: 'default', name: 'Updated Agent' };
      mockPut.mockResolvedValueOnce({ data: mockAgent });

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
      mockPost.mockResolvedValueOnce({ data: mockClonedAgent });

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
        params: { soft_delete: false },
      });
    });

    it('should search memories', async () => {
      const mockResults = [{ id: '1', content: 'Test', score: 0.9 }];
      mockPost.mockResolvedValueOnce({ data: mockResults });

      const result = await api.searchMemories('test query');
      expect(result).toHaveLength(1);
    });

    it('should semantic search memories', async () => {
      const mockResults = [{ id: '1', content: 'Test', score: 0.95 }];
      mockPost.mockResolvedValueOnce({ data: mockResults });

      const result = await api.semanticSearch('test query', { limit: 5, min_score: 0.8 });
      expect(result).toHaveLength(1);
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
      mockGet.mockResolvedValueOnce({ data: mockResponse });

      await api.searchByTag('important', { limit: 10 });
      expect(mockGet).toHaveBeenCalledWith('/api/memories/search-by-tag', {
        params: { tag: 'important', limit: 10 },
      });
    });
  });

  describe('ACP API', () => {
    it('should get ACP stats', async () => {
      const mockStats = { total_agents: 5, active_agents: 3 };
      mockGet.mockResolvedValueOnce({ data: mockStats });

      const result = await api.getAcpStats();
      expect(result.total_agents).toBe(5);
    });

    it('should get ACP agents', async () => {
      const mockAgents = [{ id: 'agent-1', name: 'Agent 1', status: 'active' }];
      mockGet.mockResolvedValueOnce({ data: mockAgents });

      const result = await api.getAcpAgents();
      expect(result).toHaveLength(1);
    });

    it('should create ACP agent', async () => {
      const mockAgent = { id: 'new-acp-agent', name: 'New Agent' };
      mockPost.mockResolvedValueOnce({ data: mockAgent });

      const result = await api.createAcpAgent({ name: 'New Agent', capabilities: ['chat'] });
      expect(result.id).toBe('new-acp-agent');
    });

    it('should update ACP agent', async () => {
      const mockAgent = { id: 'agent-1', name: 'Updated Agent' };
      mockPut.mockResolvedValueOnce({ data: mockAgent });

      const result = await api.updateAcpAgent('agent-1', { name: 'Updated Agent' });
      expect(result.name).toBe('Updated Agent');
    });

    it('should delete ACP agent', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteAcpAgent('agent-1');
      expect(mockDelete).toHaveBeenCalledWith('/api/acp/agents/agent-1');
    });
  });

  describe('Tools API', () => {
    it('should get tools stats', async () => {
      const mockStats = { total: 10, active: 8 };
      mockGet.mockResolvedValueOnce({ data: mockStats });

      const result = await api.getToolsStats();
      expect(result.total).toBe(10);
    });

    it('should get all tools', async () => {
      const mockTools = [{ id: 'tool-1', name: 'Tool 1', type: 'mcp' }];
      mockGet.mockResolvedValueOnce({ data: mockTools });

      const result = await api.getTools();
      expect(result).toHaveLength(1);
    });

    it('should get tools by type', async () => {
      const mockTools = [{ id: 'tool-1', type: 'mcp' }];
      mockGet.mockResolvedValueOnce({ data: mockTools });

      await api.getTools('mcp');
      expect(mockGet).toHaveBeenCalledWith('/api/tools', { params: { category: 'mcp' } });
    });

    it('should create tool', async () => {
      const mockTool = { id: 'new-tool', name: 'New Tool' };
      mockPost.mockResolvedValueOnce({ data: mockTool });

      const result = await api.createTool({ name: 'New Tool', type: 'mcp' });
      expect(result.id).toBe('new-tool');
    });

    it('should update tool', async () => {
      const mockTool = { id: 'tool-1', name: 'Updated Tool' };
      mockPut.mockResolvedValueOnce({ data: mockTool });

      const result = await api.updateTool('tool-1', { name: 'Updated Tool' });
      expect(result.name).toBe('Updated Tool');
    });

    it('should delete tool', async () => {
      mockDelete.mockResolvedValueOnce({ data: {} });

      await api.deleteTool('tool-1');
      expect(mockDelete).toHaveBeenCalledWith('/api/tools/tool-1');
    });

    it('should test tool', async () => {
      const mockResult = { success: true, output: 'test output' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.testTool('tool-1', { param: 'value' });
      expect(result.success).toBe(true);
    });
  });

  describe('Archive API', () => {
    it('should get archive stats', async () => {
      const mockStats = { total_archived: 100, levels: { 1: 50, 2: 30, 3: 20 } };
      mockGet.mockResolvedValueOnce({ data: mockStats });

      const result = await api.getArchiveStats();
      expect(result.total_archived).toBe(100);
    });

    it('should archive memory', async () => {
      const mockResult = { success: true, memory_id: 1, level: 2 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.archiveMemory(1, 2);
      expect(result.success).toBe(true);
    });

    it('should merge memories', async () => {
      const mockResult = { success: true, merged_id: 10 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.mergeMemories([1, 2, 3]);
      expect(result.success).toBe(true);
    });

    it('should detect duplicates', async () => {
      const mockResult = { duplicates_found: 5, groups: [] };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.detectDuplicates();
      expect(result.duplicates_found).toBe(5);
    });

    it('should auto archive process', async () => {
      const mockResult = { processed: 20, archived: 15 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.autoArchiveProcess();
      expect(result.processed).toBe(20);
    });
  });

  describe('Service API', () => {
    it('should get service status', async () => {
      const mockStatus = { running: true, uptime: 3600 };
      mockGet.mockResolvedValueOnce({ data: mockStatus });

      const result = await api.getServiceStatus();
      expect(result.running).toBe(true);
    });

    it('should start service', async () => {
      const mockResult = { success: true, pid: 12345 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.startService({ port: 8000 });
      expect(result.success).toBe(true);
    });

    it('should stop service', async () => {
      const mockResult = { success: true };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.stopService();
      expect(result.success).toBe(true);
    });

    it('should restart service', async () => {
      const mockResult = { success: true, pid: 12346 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.restartService({ port: 8000 });
      expect(result.success).toBe(true);
    });

    it('should get service logs', async () => {
      const mockLogs = { logs: ['line 1', 'line 2'] };
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
      const mockResult = { success: true };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.updateServiceConfig({ log_level: 'debug' });
      expect(result.success).toBe(true);
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

    it('should get main backend status', async () => {
      const mockStatus = { running: true, uptime: 7200 };
      mockGet.mockResolvedValueOnce({ data: mockStatus });

      const result = await api.getMainBackendStatus();
      expect(result.running).toBe(true);
    });

    it('should start main backend', async () => {
      const mockResult = { success: true, message: 'Backend started' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.startMainBackend();
      expect(result.success).toBe(true);
    });

    it('should stop main backend', async () => {
      const mockResult = { success: true, message: 'Backend stopped' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.stopMainBackend();
      expect(result.success).toBe(true);
    });

    it('should restart main backend', async () => {
      const mockResult = { success: true, message: 'Backend restarted' };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.restartMainBackend();
      expect(result.success).toBe(true);
    });
  });

  describe('Batch Operations API', () => {
    it('should batch delete memories', async () => {
      const mockResult = { success: true, deleted: 3 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchDeleteMemories([1, 2, 3]);
      expect(result.deleted).toBe(3);
    });

    it('should batch update tags', async () => {
      const mockResult = { success: true, updated: 5 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchUpdateTags([1, 2, 3, 4, 5], ['tag1', 'tag2'], 'add');
      expect(result.updated).toBe(5);
    });

    it('should batch archive memories', async () => {
      const mockResult = { success: true, archived: 2 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchArchiveMemories([1, 2]);
      expect(result.archived).toBe(2);
    });

    it('should batch restore memories', async () => {
      const mockResult = { success: true, restored: 2 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchRestoreMemories([1, 2]);
      expect(result.restored).toBe(2);
    });

    it('should batch update memories', async () => {
      const mockResult = { success: true, updated: 3 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchUpdateMemories([1, 2, 3], { importance: 5 });
      expect(result.updated).toBe(3);
    });

    it('should batch tag by query', async () => {
      const mockResult = { success: true, tagged: 10 };
      mockPost.mockResolvedValueOnce({ data: mockResult });

      const result = await api.batchTagByQuery('python', ['programming'], 'add');
      expect(result.tagged).toBe(10);
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
    });
  });

  describe('Admin API', () => {
    it('should get stats', async () => {
      const mockStats = { total_memories: 100, total_sessions: 50 };
      mockGet.mockResolvedValueOnce({ data: mockStats });

      const result = await api.getStats();
      expect(result.total_memories).toBe(100);
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
    it('should cache sessions response', async () => {
      const mockSessions = [{ id: '1', title: 'Session 1' }];
      mockGet.mockResolvedValueOnce({ data: mockSessions });

      await api.getSessions();
      await api.getSessions();

      expect(mockGet).toHaveBeenCalledTimes(1);
    });

    it('should cache agents response', async () => {
      const mockAgents = [{ id: 'default', name: 'Default' }];
      mockGet.mockResolvedValueOnce({ data: mockAgents });

      await api.getAgents();
      await api.getAgents();

      expect(mockGet).toHaveBeenCalledTimes(1);
    });

    it('should cache single agent response', async () => {
      const mockAgent = { id: 'default', name: 'Default Agent' };
      mockGet.mockResolvedValueOnce({ data: mockAgent });

      await api.getAgent('default');
      await api.getAgent('default');

      expect(mockGet).toHaveBeenCalledTimes(1);
    });

    it('should clear cache on session creation', async () => {
      mockGet.mockResolvedValueOnce({ data: [] });
      mockPost.mockResolvedValueOnce({ data: { id: 'new' } });
      mockGet.mockResolvedValueOnce({ data: [{ id: 'new' }] });

      await api.getSessions();
      await api.createSession('New');
      await api.getSessions();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on session deletion', async () => {
      mockGet.mockResolvedValueOnce({ data: [{ id: '1' }] });
      mockDelete.mockResolvedValueOnce({ data: {} });
      mockGet.mockResolvedValueOnce({ data: [] });

      await api.getSessions();
      await api.deleteSession('1');
      await api.getSessions();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on agent creation', async () => {
      mockGet.mockResolvedValueOnce({ data: [] });
      mockPost.mockResolvedValueOnce({ data: { id: 'new' } });
      mockGet.mockResolvedValueOnce({ data: [{ id: 'new' }] });

      await api.getAgents();
      await api.createAgent({ name: 'New' });
      await api.getAgents();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on agent update', async () => {
      mockGet.mockResolvedValueOnce({ data: [{ id: 'default' }] });
      mockPut.mockResolvedValueOnce({ data: { id: 'default' } });
      mockGet.mockResolvedValueOnce({ data: [{ id: 'default', name: 'Updated' }] });

      await api.getAgent('default');
      await api.updateAgent('default', { name: 'Updated' });
      await api.getAgent('default');

      expect(mockGet).toHaveBeenCalledTimes(2);
    });

    it('should clear cache on agent deletion', async () => {
      mockGet.mockResolvedValueOnce({ data: [{ id: 'agent-1' }] });
      mockDelete.mockResolvedValueOnce({ data: {} });
      mockGet.mockResolvedValueOnce({ data: [] });

      await api.getAgents();
      await api.deleteAgent('agent-1');
      await api.getAgents();

      expect(mockGet).toHaveBeenCalledTimes(2);
    });
  });
});
