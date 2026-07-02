/**
 * ApiClient mixin: agents & ACP agents
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';
import type { Agent, AcpStats, AcpAgentRow } from './_types';

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
}
