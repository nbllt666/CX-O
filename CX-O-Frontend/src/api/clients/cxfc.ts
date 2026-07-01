/**
 * ApiClient mixin: CXFC plugin/skill domain operations.
 * Extracted from client.ts as part of M16 split.
 */
import type { _ApiClientBase } from './_common';
import type { CxfcPlugin, CxfcSkill, CxfcDiscoveredPlugin } from './_types';

// Declaration merging: let TypeScript know _CxfcClientMixin can access _ApiClientBase's methods
export interface _CxfcClientMixin extends _ApiClientBase {}

export class _CxfcClientMixin {
  async getCxfcPlugins(): Promise<CxfcPlugin[]> {
    const response = await this.request<{ plugins: CxfcPlugin[] }>({ url: '/api/cxfc/plugins' });
    return response.plugins || [];
  }

  async getCxfcSkills(): Promise<CxfcSkill[]> {
    const response = await this.request<{ skills: CxfcSkill[] }>({ url: '/api/cxfc/skills' });
    return response.skills || [];
  }

  async connectCxfcPlugin(host: string, port: number): Promise<{ status: string; plugin_id: string }> {
    return this.request<{ status: string; plugin_id: string }>({
      url: '/api/cxfc/connect',
      method: 'post',
      data: { host, port },
    });
  }

  async disconnectCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return this.request<{ status: string }>({
      url: `/api/cxfc/plugins/${pluginId}/disconnect`,
      method: 'post',
    });
  }

  async refreshCxfcPlugin(pluginId: string): Promise<{ status: string }> {
    return this.request<{ status: string }>({
      url: `/api/cxfc/plugins/${pluginId}/refresh`,
      method: 'post',
    });
  }

  async discoverCxfcPlugins(scan: boolean = false): Promise<{ remote: CxfcDiscoveredPlugin[] }> {
    return this.request<{ remote: CxfcDiscoveredPlugin[] }>({
      url: '/api/cxfc/discover',
      params: scan ? { scan: true } : undefined,
    });
  }
}