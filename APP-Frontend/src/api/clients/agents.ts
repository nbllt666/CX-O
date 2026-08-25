/**
 * agents 域客户端：Agent CRUD + ACP 多智能体互通。
 * 端点面对齐 CX-O-Frontend clients/agents.ts。
 */
import { clearApiCache, request } from '../base';
import type { AcpAgentRow, AcpMessage, AcpStats, Agent } from '../types';

export const agentsApi = {
  async getAgents(): Promise<Agent[]> {
    const response = await request<{ status: string; agents: Agent[]; total: number }>(
      { url: '/api/agents' },
      true,
    );
    return response.agents || [];
  },

  async getAgent(agentId: string): Promise<Agent> {
    const response = await request<{ status: string; agent: Agent }>({
      url: `/api/agents/${agentId}`,
    });
    return response.agent;
  },

  async createAgent(data: Partial<Agent>): Promise<Agent> {
    const response = await request<{ status: string; agent: Agent; message: string }>({
      url: '/api/agents',
      method: 'post',
      data,
    });
    clearApiCache('/api/agents');
    return response.agent;
  },

  async updateAgent(agentId: string, data: Partial<Agent>): Promise<Agent> {
    const response = await request<{ status: string; agent: Agent; message: string }>({
      url: `/api/agents/${agentId}`,
      method: 'put',
      data,
    });
    clearApiCache('/api/agents');
    return response.agent;
  },

  async deleteAgent(agentId: string): Promise<void> {
    await request({ url: `/api/agents/${agentId}`, method: 'delete' });
    clearApiCache('/api/agents');
  },

  async cloneAgent(agentId: string): Promise<Agent> {
    const response = await request<{ status: string; agent: Agent; message: string }>({
      url: `/api/agents/${agentId}/clone`,
      method: 'post',
    });
    return response.agent;
  },

  /** 将指定 Agent 设为默认 Agent（全局唯一），返回更新后的默认 Agent */
  async setDefaultAgent(agentId: string): Promise<Agent> {
    const response = await request<{ status: string; agent: Agent; message: string }>({
      url: `/api/agents/${agentId}/default`,
      method: 'post',
    });
    clearApiCache('/api/agents');
    return response.agent;
  },

  async getAvailableModels(): Promise<{ models: string[] }> {
    // 真实端点是 /api/service/models，返回 { providers[{id,name}], ollama_models[{name}] }；
    // 映射为前端约定的 { models: string[] }（取各 provider 模型名 + ollama 模型名，去重）。
    const data = await request<{
      status: string;
      providers: Array<{ id: string; name?: string }>;
      ollama_models: Array<{ name: string }>;
    }>({ url: '/api/service/models' });
    const names: string[] = [];
    for (const p of data.providers ?? []) {
      if (p.name) names.push(p.name);
    }
    for (const m of data.ollama_models ?? []) {
      if (m?.name) names.push(m.name);
    }
    return { models: Array.from(new Set(names)) };
  },

  /** 获取 Agent 上下文（历史消息） */
  async getAgentContext(
    agentId: string,
    limit = 20,
  ): Promise<{ recent_messages: Array<{ role: string; content: string; created_at?: string }> }> {
    const response = await request<{
      status: string;
      recent_messages: Array<{ role: string; content: string; created_at?: string }>;
    }>({ url: `/api/agents/${agentId}/context`, params: { limit } });
    return { recent_messages: response.recent_messages || [] };
  },

  async clearAgentContext(agentId: string): Promise<void> {
    await request({ url: `/api/agents/${agentId}/context`, method: 'delete' });
  },

  // ── ACP ──

  async getAcpStats(): Promise<AcpStats> {
    const response = await request<{ status?: string; statistics: Record<string, number> }>({
      url: '/api/acp/stats',
    });
    const stats = response.statistics || {};
    return {
      total_agents: stats.total_agents ?? 0,
      active_agents: stats.online_agents ?? stats.active_agents ?? 0,
      total_messages: stats.total_messages ?? 0,
      total_conversations: stats.total_messages ?? 0,
    };
  },

  async getAcpAgents(): Promise<AcpAgentRow[]> {
    const response = await request<{ status?: string; agents: AcpAgentRow[] }>({
      url: '/api/acp/agents',
    });
    return response.agents || [];
  },

  createAcpAgent(data: {
    name: string;
    description?: string;
    capabilities?: string[];
  }): Promise<AcpAgentRow> {
    return request<AcpAgentRow>({
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
  },

  updateAcpAgent(agentId: string, data: Record<string, unknown>): Promise<AcpAgentRow> {
    return request<AcpAgentRow>({ url: `/api/acp/agents/${agentId}`, method: 'patch', data });
  },

  async deleteAcpAgent(agentId: string): Promise<void> {
    await request({ url: `/api/acp/agents/${agentId}`, method: 'delete' });
  },

  /** 查询指定 agent 的 ACP 消息历史（含本地 agent 互通消息） */
  getAcpMessages(
    agentId: string,
    limit = 50,
  ): Promise<{ status: string; messages: AcpMessage[]; total: number }> {
    return request<{ status: string; messages: AcpMessage[]; total: number }>({
      url: '/api/acp/messages',
      params: { agent_id: agentId, limit },
    });
  },

  /** 通过 ACP 协议向指定 agent 发送消息（触发对方自动回复） */
  sendAcpMessage(
    toAgentId: string,
    message: string,
    msgType = 'chat',
  ): Promise<{ status: string; message_id: string; message: string }> {
    return request<{ status: string; message_id: string; message: string }>({
      url: '/api/acp/send',
      method: 'post',
      data: {
        to_agent_id: toAgentId,
        msg_type: msgType,
        content: { text: message },
      },
    });
  },
};
