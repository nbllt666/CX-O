import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useChatStore } from './chatStore';

describe('chatStore', () => {
  beforeEach(() => {
    useChatStore.setState({
      agents: [],
      currentAgentId: null,
      sessions: [],
      currentSessionId: null,
      isChatExpanded: false,
    });
    localStorage.clear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe('initial state', () => {
    it('should have correct initial state', () => {
      const state = useChatStore.getState();
      expect(state.agents).toEqual([]);
      expect(state.sessions).toEqual([]);
      expect(state.currentSessionId).toBeNull();
      expect(state.currentAgentId).toBeNull();
      expect(state.isChatExpanded).toBe(false);
    });
  });

  describe('setCurrentSessionId', () => {
    it('should set current session id', () => {
      useChatStore.getState().setCurrentSessionId('session-1');
      expect(useChatStore.getState().currentSessionId).toBe('session-1');
    });

    it('should set current session id to null', () => {
      useChatStore.getState().setCurrentSessionId('session-1');
      useChatStore.getState().setCurrentSessionId(null);
      expect(useChatStore.getState().currentSessionId).toBeNull();
    });

    it('should overwrite existing session id', () => {
      useChatStore.getState().setCurrentSessionId('session-1');
      useChatStore.getState().setCurrentSessionId('session-2');
      expect(useChatStore.getState().currentSessionId).toBe('session-2');
    });
  });

  describe('setSessions', () => {
    it('should set sessions', () => {
      const mockSessions = [
        { id: '1', title: 'Session 1', message_count: 5, created_at: new Date().toISOString() },
        { id: '2', title: 'Session 2', message_count: 3, created_at: new Date().toISOString() },
      ];
      useChatStore.getState().setSessions(mockSessions);
      expect(useChatStore.getState().sessions).toHaveLength(2);
      expect(useChatStore.getState().sessions[0].title).toBe('Session 1');
    });

    it('should set empty sessions array', () => {
      const mockSessions = [
        { id: '1', title: 'Session 1', message_count: 5, created_at: new Date().toISOString() },
      ];
      useChatStore.getState().setSessions(mockSessions);
      useChatStore.getState().setSessions([]);
      expect(useChatStore.getState().sessions).toHaveLength(0);
    });

    it('should replace existing sessions', () => {
      const mockSessions1 = [
        { id: '1', title: 'Session 1', message_count: 5, created_at: new Date().toISOString() },
      ];
      const mockSessions2 = [
        { id: '2', title: 'Session 2', message_count: 3, created_at: new Date().toISOString() },
        { id: '3', title: 'Session 3', message_count: 1, created_at: new Date().toISOString() },
      ];
      useChatStore.getState().setSessions(mockSessions1);
      useChatStore.getState().setSessions(mockSessions2);
      expect(useChatStore.getState().sessions).toHaveLength(2);
      expect(useChatStore.getState().sessions[0].id).toBe('2');
    });

    it('should handle sessions with all fields', () => {
      const mockSessions = [
        {
          id: '1',
          title: 'Session 1',
          agent_id: 'agent-1',
          message_count: 5,
          created_at: '2024-01-15T10:30:00Z',
        },
      ];
      useChatStore.getState().setSessions(mockSessions);
      expect(useChatStore.getState().sessions[0].agent_id).toBe('agent-1');
    });
  });

  describe('setAgents', () => {
    it('should set agents', () => {
      const mockAgents = [
        {
          id: 'default',
          name: 'Default Agent',
          description: 'Test agent',
          system_prompt: 'You are a helpful assistant',
          model: 'gpt-4',
          temperature: 0.7,
          max_tokens: 2000,
          use_memory: true,
          use_tools: false,
          memory_scene: 'default',
        },
      ];
      useChatStore.getState().setAgents(mockAgents);
      expect(useChatStore.getState().agents).toHaveLength(1);
      expect(useChatStore.getState().agents[0].name).toBe('Default Agent');
    });

    it('should set empty agents array', () => {
      const mockAgents = [
        {
          id: 'default',
          name: 'Default Agent',
          description: '',
          system_prompt: '',
          model: 'gpt-4',
          temperature: 0.7,
          max_tokens: 2000,
          use_memory: false,
          use_tools: false,
          memory_scene: '',
        },
      ];
      useChatStore.getState().setAgents(mockAgents);
      useChatStore.getState().setAgents([]);
      expect(useChatStore.getState().agents).toHaveLength(0);
    });

    it('should handle agents with optional fields', () => {
      const mockAgents = [
        {
          id: 'agent-1',
          name: 'Agent 1',
          description: 'Test agent',
          system_prompt: 'You are helpful',
          model: 'gpt-4',
          temperature: 0.5,
          max_tokens: 1000,
          use_memory: true,
          use_tools: true,
          memory_scene: 'custom',
          is_default: true,
        },
      ];
      useChatStore.getState().setAgents(mockAgents);
      expect(useChatStore.getState().agents[0].is_default).toBe(true);
    });

    it('should replace existing agents', () => {
      const mockAgents1 = [
        {
          id: 'default',
          name: 'Default Agent',
          description: '',
          system_prompt: '',
          model: 'gpt-4',
          temperature: 0.7,
          max_tokens: 2000,
          use_memory: false,
          use_tools: false,
          memory_scene: '',
        },
      ];
      const mockAgents2 = [
        {
          id: 'agent-2',
          name: 'Agent 2',
          description: '',
          system_prompt: '',
          model: 'gpt-3.5',
          temperature: 0.8,
          max_tokens: 1500,
          use_memory: false,
          use_tools: false,
          memory_scene: '',
        },
      ];
      useChatStore.getState().setAgents(mockAgents1);
      useChatStore.getState().setAgents(mockAgents2);
      expect(useChatStore.getState().agents).toHaveLength(1);
      expect(useChatStore.getState().agents[0].id).toBe('agent-2');
    });
  });

  describe('setCurrentAgentId', () => {
    it('should set current agent id', () => {
      useChatStore.getState().setCurrentAgentId('agent-1');
      expect(useChatStore.getState().currentAgentId).toBe('agent-1');
    });

    it('should set current agent id to null', () => {
      useChatStore.getState().setCurrentAgentId('agent-1');
      useChatStore.getState().setCurrentAgentId(null);
      expect(useChatStore.getState().currentAgentId).toBeNull();
    });

    it('should overwrite existing agent id', () => {
      useChatStore.getState().setCurrentAgentId('agent-1');
      useChatStore.getState().setCurrentAgentId('agent-2');
      expect(useChatStore.getState().currentAgentId).toBe('agent-2');
    });
  });

  describe('setIsChatExpanded', () => {
    it('should set chat expanded state', () => {
      useChatStore.getState().setIsChatExpanded(true);
      expect(useChatStore.getState().isChatExpanded).toBe(true);
    });

    it('should toggle chat expanded state', () => {
      useChatStore.getState().setIsChatExpanded(false);
      expect(useChatStore.getState().isChatExpanded).toBe(false);

      useChatStore.getState().setIsChatExpanded(true);
      expect(useChatStore.getState().isChatExpanded).toBe(true);
    });

    it('should set to false', () => {
      useChatStore.getState().setIsChatExpanded(true);
      useChatStore.getState().setIsChatExpanded(false);
      expect(useChatStore.getState().isChatExpanded).toBe(false);
    });
  });

  describe('multiple state updates', () => {
    it('should handle multiple sequential updates', () => {
      useChatStore.getState().setCurrentAgentId('agent-1');
      useChatStore.getState().setCurrentSessionId('session-1');
      useChatStore.getState().setIsChatExpanded(true);

      const state = useChatStore.getState();
      expect(state.currentAgentId).toBe('agent-1');
      expect(state.currentSessionId).toBe('session-1');
      expect(state.isChatExpanded).toBe(true);
    });

    it('should handle setting agents and sessions together', () => {
      const mockAgents = [
        {
          id: 'default',
          name: 'Default Agent',
          description: '',
          system_prompt: '',
          model: 'gpt-4',
          temperature: 0.7,
          max_tokens: 2000,
          use_memory: false,
          use_tools: false,
          memory_scene: '',
        },
      ];
      const mockSessions = [
        { id: '1', title: 'Session 1', message_count: 5, created_at: new Date().toISOString() },
      ];

      useChatStore.getState().setAgents(mockAgents);
      useChatStore.getState().setSessions(mockSessions);

      const state = useChatStore.getState();
      expect(state.agents).toHaveLength(1);
      expect(state.sessions).toHaveLength(1);
    });
  });

  describe('edge cases', () => {
    it('should handle very long session id', () => {
      const longId = 'a'.repeat(1000);
      useChatStore.getState().setCurrentSessionId(longId);
      expect(useChatStore.getState().currentSessionId).toBe(longId);
    });

    it('should handle special characters in session id', () => {
      const specialId = 'session-@#$%^&*()_+-=[]{}|;:,.<>?';
      useChatStore.getState().setCurrentSessionId(specialId);
      expect(useChatStore.getState().currentSessionId).toBe(specialId);
    });

    it('should handle unicode in agent name', () => {
      const mockAgents = [
        {
          id: 'agent-1',
          name: '智能助手 🤖',
          description: '',
          system_prompt: '',
          model: 'gpt-4',
          temperature: 0.7,
          max_tokens: 2000,
          use_memory: false,
          use_tools: false,
          memory_scene: '',
        },
      ];
      useChatStore.getState().setAgents(mockAgents);
      expect(useChatStore.getState().agents[0].name).toBe('智能助手 🤖');
    });

    it('should handle session with zero message count', () => {
      const mockSessions = [
        { id: '1', title: 'Empty Session', message_count: 0, created_at: new Date().toISOString() },
      ];
      useChatStore.getState().setSessions(mockSessions);
      expect(useChatStore.getState().sessions[0].message_count).toBe(0);
    });

    it('should handle agent with extreme temperature values', () => {
      const mockAgents = [
        {
          id: 'agent-1',
          name: 'Agent 1',
          description: '',
          system_prompt: '',
          model: 'gpt-4',
          temperature: 0,
          max_tokens: 1,
          use_memory: false,
          use_tools: false,
          memory_scene: '',
        },
        {
          id: 'agent-2',
          name: 'Agent 2',
          description: '',
          system_prompt: '',
          model: 'gpt-4',
          temperature: 2,
          max_tokens: 100000,
          use_memory: false,
          use_tools: false,
          memory_scene: '',
        },
      ];
      useChatStore.getState().setAgents(mockAgents);
      expect(useChatStore.getState().agents[0].temperature).toBe(0);
      expect(useChatStore.getState().agents[1].temperature).toBe(2);
    });
  });
});
