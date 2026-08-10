/**
 * config 域客户端：后端配置读取/更新与各子系统配置查询。
 * 端点面对齐 CX-O-Frontend clients/config.ts。
 */
import { clearApiCache, request } from '../base';
import type { FrontendLimits } from '../types';

export const DEFAULT_LIMITS: FrontendLimits = {
  max_upload_size_mb: 500,
  max_chat_images: 20,
  avatar_min_width: 100,
  avatar_max_width: 1200,
  temperature_max: 5,
  speed_max: 3,
};

export const configApi = {
  getConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/config' });
  },

  /** 获取前端限制参数；失败时回退默认值（与现有前端口径一致） */
  async getLimits(): Promise<FrontendLimits> {
    try {
      return await request<FrontendLimits>({ url: '/api/config/limits' });
    } catch {
      return { ...DEFAULT_LIMITS };
    }
  },

  async updateConfig(section: string, data: Record<string, unknown>): Promise<void> {
    await request({ url: '/api/config', method: 'put', data: { section, data } });
    clearApiCache();
  },

  getDanmakuConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/danmaku/config' });
  },

  getFirewallConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/firewall/config' });
  },

  getFirewallV3Config(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/firewall/v3/config' });
  },

  getVadConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/vad/config' });
  },

  getSenseVoiceStreamingConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/config/sensevoice-streaming' });
  },

  getAdaptivePollingConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/config/adaptive-polling' });
  },

  getGraphConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/graph/config' });
  },
};
