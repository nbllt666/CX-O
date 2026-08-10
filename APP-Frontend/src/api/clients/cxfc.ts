/**
 * cxfc 域客户端：CXFC 插件 / 技能管理。
 * 端点面对齐 CX-O-Frontend clients/cxfc.ts。
 */
import { request } from '../base';
import type { CxfcDiscoveredPlugin, CxfcPlugin, CxfcSkill } from '../types';

export const cxfcApi = {
  async getCxfcPlugins(): Promise<CxfcPlugin[]> {
    const response = await request<{ plugins: CxfcPlugin[] }>({ url: '/api/cxfc/plugins' });
    return response.plugins || [];
  },

  async getCxfcSkills(): Promise<CxfcSkill[]> {
    const response = await request<{ skills: CxfcSkill[] }>({ url: '/api/cxfc/skills' });
    return response.skills || [];
  },

  connectCxfcPlugin(host: string, port: number): Promise<{ status: string; plugin_id: string }> {
    return request<{ status: string; plugin_id: string }>({
      url: '/api/cxfc/connect',
      method: 'post',
      data: { host, port },
    });
  },

  disconnectCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return request<{ status: string }>({
      url: `/api/cxfc/plugins/${encodeURIComponent(pluginId)}/disconnect`,
      method: 'post',
    });
  },

  refreshCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return request<{ status: string }>({
      url: `/api/cxfc/plugins/${encodeURIComponent(pluginId)}/refresh`,
      method: 'post',
    });
  },

  discoverCxfcPlugins(scan = false): Promise<{ remote: CxfcDiscoveredPlugin[] }> {
    return request<{ remote: CxfcDiscoveredPlugin[] }>({
      url: '/api/cxfc/discover',
      params: scan ? { scan: true } : undefined,
    });
  },
};
