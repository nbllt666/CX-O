/**
 * ApiClient mixin: agents & ACP agents
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';
import type { Agent, AcpStats, AcpAgentRow } from './_types';

// ACP 消息类型（迁移自 CXHMS: frontend/src/api/agent.ts AcpMessage）
// 与后端 ACPMessageInfo.to_dict() 字段对齐
export interface AcpMessage {
  id: string;
  type: string;
  from_agent_id: string;
  from_agent_name: string;
  to_agent_id: string | null;
  to_group_id: string | null;
  content: Record<string, unknown> | string;
  timestamp: string;
  is_read: boolean;
  is_sent: boolean;
  metadata: Record<string, unknown>;
}

export class _AgentsClientMixin extends _ApiClientBase {
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

  /**
   * 获取 Agent 上下文（历史消息）
   * 迁移自 CXHMS: 用于 MemoryAgentPage 加载历史对话
   */
  async getAgentContext(
    agentId: string,
    limit: number = 20
  ): Promise<{
    recent_messages: Array<{ role: string; content: string; created_at?: string }>;
  }> {
    const response = await this.request<{
      status: string;
      recent_messages: Array<{ role: string; content: string; created_at?: string }>;
    }>({ url: `/api/agents/${agentId}/context`, params: { limit } });
    return { recent_messages: response.recent_messages || [] };
  }

  /**
   * 清空 Agent 上下文
   * 迁移自 CXHMS: 用于 MemoryAgentPage clearChat
   */
  async clearAgentContext(agentId: string): Promise<void> {
    await this.request({ url: `/api/agents/${agentId}/context`, method: 'delete' });
  }

  /**
   * 查询指定 agent 的 ACP 消息历史（含本地 agent 互通消息）
   * 迁移自 CXHMS: frontend/src/api/agent.ts getAcpMessages
   */
  async getAcpMessages(
    agentId: string,
    limit: number = 50
  ): Promise<{ status: string; messages: AcpMessage[]; total: number }> {
    const response = await this.request<{
      status: string;
      messages: AcpMessage[];
      total: number;
    }>({ url: '/api/acp/messages', params: { agent_id: agentId, limit } });
    return response;
  }

  /**
   * 通过 ACP 协议向指定 agent 发送消息（触发对方自动回复）
   * 迁移自 CXHMS: frontend/src/api/agent.ts sendAcpMessage
   */
  async sendAcpMessage(
    toAgentId: string,
    message: string,
    msgType: string = 'chat'
  ): Promise<{ status: string; message_id: string; message: string }> {
    return this.request<{
      status: string;
      message_id: string;
      message: string;
    }>({
      url: '/api/acp/send',
      method: 'post',
      data: {
        to_agent_id: toAgentId,
        msg_type: msgType,
        content: { text: message },
      },
    });
  }
}
