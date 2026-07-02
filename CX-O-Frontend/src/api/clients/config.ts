/**
 * ApiClient mixin: Config domain operations.
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';
import type { FrontendLimits } from './_types';

export class _ConfigClientMixin extends _ApiClientBase {
  async getConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/config' });
  }

  async getLimits(): Promise<FrontendLimits> {
    try {
      return await this.request<FrontendLimits>({ url: '/api/config/limits' });
    } catch {
      return {
        max_upload_size_mb: 500,
        max_chat_images: 20,
        avatar_min_width: 100,
        avatar_max_width: 1200,
        temperature_max: 5,
        speed_max: 3,
      };
    }
  }

  async updateConfig(section: string, data: Record<string, unknown>): Promise<void> {
    await this.request({ url: '/api/config', method: 'put', data: { section, data } });
    this._clearCache();
  }

  async getDanmakuConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/danmaku/config' });
  }

  async getFirewallConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/firewall/config' });
  }

  async getFirewallV3Config(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/firewall/v3/config' });
  }

  async getVadConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/vad/config' });
  }

  async getSenseVoiceStreamingConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/config/sensevoice-streaming' });
  }

  async getAdaptivePollingConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/config/adaptive-polling' });
  }

  async getGraphConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/graph/config' });
  }
}