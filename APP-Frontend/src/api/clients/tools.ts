/**
 * tools 域客户端：工具列表 / 统计 / 测试 / CRUD。
 * 端点面对齐 CX-O-Frontend clients/tools.ts。
 */
import { request } from '../base';
import type { Tool, ToolStats } from '../types';

export const toolsApi = {
  getTools(filter?: string): Promise<{ tools: Record<string, Tool> }> {
    return request<{ tools: Record<string, Tool> }>({
      url: '/api/tools',
      params: filter ? { category: filter } : undefined,
    });
  },

  async getToolsStats(): Promise<ToolStats> {
    const response = await request<{ status?: string; statistics: ToolStats }>({
      url: '/api/tools/stats',
    });
    return response.statistics;
  },

  async deleteTool(toolId: string): Promise<void> {
    await request({ url: `/api/tools/${toolId}`, method: 'delete' });
  },

  testTool(
    toolId: string,
    params?: Record<string, unknown>,
  ): Promise<{ result: Record<string, unknown> }> {
    return request<{ result: Record<string, unknown> }>({
      url: `/api/tools/${toolId}/test`,
      method: 'post',
      // 后端 ToolTestRequest 契约要求 { arguments: {...} }，裸传 params 会被忽略（恒空参执行）
      data: { arguments: params },
    });
  },

  createTool(toolData: Record<string, unknown>): Promise<Tool> {
    return request<Tool>({ url: '/api/tools', method: 'post', data: toolData });
  },

  updateTool(toolId: string, toolData: Record<string, unknown>): Promise<Tool> {
    return request<Tool>({ url: `/api/tools/${toolId}`, method: 'patch', data: toolData });
  },
};
