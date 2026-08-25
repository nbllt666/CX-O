/**
 * service 域客户端：服务控制（主后端 /api/service/*）。
 * 端点面对齐 CX-O-Frontend clients/service.ts。
 */
import { request } from '../base';

export const serviceApi = {
  // ── 自身服务控制（主后端 /api/service/*） ──

  getServiceStatus(): Promise<{ status: string }> {
    return request<{ status: string }>({ url: '/api/service/status' });
  },

  startService(data?: { port?: number }): Promise<{ status: string }> {
    return request<{ status: string }>({ url: '/api/service/start', method: 'post', data });
  },

  stopService(): Promise<{ status: string }> {
    return request<{ status: string }>({ url: '/api/service/stop', method: 'post' });
  },

  restartService(data?: { port?: number }): Promise<{ status: string }> {
    return request<{ status: string }>({ url: '/api/service/restart', method: 'post', data });
  },

  getServiceLogs(lines = 50): Promise<{ logs: string }> {
    return request<{ logs: string }>({ url: '/api/service/logs', params: { lines } });
  },

  getServiceConfig(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/service/config' });
  },

  async updateServiceConfig(config: Record<string, unknown>): Promise<void> {
    await request({ url: '/api/service/config', method: 'put', data: config });
  },

  getEnvironmentInfo(): Promise<Record<string, unknown>> {
    return request<Record<string, unknown>>({ url: '/api/service/environment' });
  },
};
