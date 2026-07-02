/**
 * ApiClient mixin: tools
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';
import type { Tool, ToolStats } from './_types';

export class _ToolsClientMixin extends _ApiClientBase {
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

  async createTool(toolData: Record<string, unknown>): Promise<Tool> {
    return this.request({ url: '/api/tools', method: 'post', data: toolData });
  }

  async updateTool(toolId: string, toolData: Record<string, unknown>): Promise<Tool> {
    return this.request({ url: `/api/tools/${toolId}`, method: 'patch', data: toolData });
  }
}
