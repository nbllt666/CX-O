/**
 * 聊天状态存储：Agent 列表/当前 Agent、会话列表/当前会话、对话展开状态。
 * 行为口径对齐 CX-O-Frontend src/store/chatStore.ts，
 * 数据面改用 APP-Frontend 的 agentsApi / chatApi 域客户端。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';
import { agentsApi } from '../api/clients/agents';
import { chatApi } from '../api/clients/chat';
import type { Agent, Session } from '../api/types';

interface ChatState {
  agents: Agent[];
  currentAgentId: string | null;
  isLoadingAgents: boolean;
  agentsError: string | null;
  setAgents: (agents: Agent[]) => void;
  setCurrentAgentId: (id: string | null) => void;
  fetchAgents: () => Promise<void>;

  sessions: Session[];
  currentSessionId: string | null;
  isLoadingSessions: boolean;
  sessionsError: string | null;
  setSessions: (sessions: Session[]) => void;
  setCurrentSessionId: (id: string | null) => void;
  fetchSessions: () => Promise<void>;
  createSession: (agentId?: string) => Promise<string | null>;
  deleteSession: (sessionId: string) => Promise<void>;

  isChatExpanded: boolean;
  setIsChatExpanded: (expanded: boolean) => void;
}

// 各刷新动作的单调请求序号（模式同 nekoStore）：多窗口并发触发时，
// 旧请求的迟到响应不回填陈旧列表、不覆盖派生写入（如 currentAgentId 归零）。
let fetchAgentsSeq = 0;
let fetchSessionsSeq = 0;

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      agents: [],
      currentAgentId: null,
      isLoadingAgents: false,
      agentsError: null,

      setAgents: (agents) => set({ agents }),

      setCurrentAgentId: (id) => set({ currentAgentId: id }),

      fetchAgents: async () => {
        const seq = ++fetchAgentsSeq;
        set({ isLoadingAgents: true, agentsError: null });
        try {
          const agentsList = await agentsApi.getAgents();
          if (seq !== fetchAgentsSeq) return; // 过期响应丢弃，不回填陈旧列表
          const filteredAgents = agentsList.filter((agent) => agent.id !== 'memory-agent');
          set({ agents: filteredAgents });

          const { currentAgentId } = get();
          const stillExists =
            currentAgentId !== null && filteredAgents.some((a) => a.id === currentAgentId);
          if (!currentAgentId || !stillExists) {
            if (filteredAgents.length > 0) {
              const defaultAgent = filteredAgents.find((a) => a.is_default) || filteredAgents[0];
              set({ currentAgentId: defaultAgent.id });
            } else {
              set({ currentAgentId: null });
            }
          }
        } catch (error: unknown) {
          console.error('Failed to fetch agents:', error);
          if (seq !== fetchAgentsSeq) return; // 过期失败也不污染最新状态
          set({ agentsError: '加载失败' });
        } finally {
          if (seq === fetchAgentsSeq) set({ isLoadingAgents: false });
        }
      },

      sessions: [],
      currentSessionId: null,
      isLoadingSessions: false,
      sessionsError: null,

      setSessions: (sessions) => set({ sessions }),

      setCurrentSessionId: (id) => set({ currentSessionId: id }),

      fetchSessions: async () => {
        const seq = ++fetchSessionsSeq;
        set({ isLoadingSessions: true, sessionsError: null });
        try {
          const sessions = await chatApi.getSessions();
          if (seq !== fetchSessionsSeq) return; // 过期响应丢弃，不回填陈旧列表
          set({ sessions });
        } catch (error: unknown) {
          console.error('Failed to fetch sessions:', error);
          if (seq !== fetchSessionsSeq) return;
          set({ sessionsError: '加载失败' });
        } finally {
          if (seq === fetchSessionsSeq) set({ isLoadingSessions: false });
        }
      },

      createSession: async (agentId?: string) => {
        try {
          const aid = agentId ?? get().currentAgentId ?? 'default';
          const data = await chatApi.createSession('新对话', aid);
          if (data.session_id) {
            if (agentId) {
              set({ currentAgentId: agentId });
            }
            set({ currentSessionId: data.session_id });
            await get().fetchSessions();
            return data.session_id;
          }
          return null;
        } catch (error: unknown) {
          console.error('Failed to create session:', error);
          return null;
        }
      },

      deleteSession: async (sessionId: string) => {
        try {
          await chatApi.deleteSession(sessionId);
          const { currentSessionId } = get();
          if (currentSessionId === sessionId) {
            set({ currentSessionId: null });
          }
          await get().fetchSessions();
        } catch (error: unknown) {
          console.error('Failed to delete session:', error);
          throw error;
        }
      },

      isChatExpanded: false,
      setIsChatExpanded: (expanded) => set({ isChatExpanded: expanded }),
    }),
    {
      name: 'cxo-pet-chat',
      storage: createStorage(),
      partialize: (state) => ({
        currentAgentId: state.currentAgentId,
        currentSessionId: state.currentSessionId,
        isChatExpanded: state.isChatExpanded,
      }),
    },
  ),
);
