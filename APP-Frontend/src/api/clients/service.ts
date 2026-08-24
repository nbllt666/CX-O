/**
 * service 域客户端：服务控制（自身服务 + 主后端进程管理）。
 * 端点面对齐 CX-O-Frontend clients/service.ts。
 * 控制服务地址默认与主后端同源，可经 localStorage `cxo-control-url` 或
 * VITE_CONTROL_SERVICE_URL 独立覆盖（见 base.ts getControlServiceUrl）。
 */
import { controlRequest, request } from '../base';

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

  // ── 控制服务端点（control service） ──

  getControlServiceHealth(): Promise<{ status: string }> {
    return controlRequest<{ status: string }>({ url: '/health' });
  },

  getMainBackendStatus(): Promise<{ running: boolean; version?: string }> {
    return controlRequest<{ running: boolean; version?: string }>({ url: '/api/status' });
  },

  startMainBackend(): Promise<{ status: string }> {
    return controlRequest<{ status: string }>({ url: '/api/start', method: 'post' });
  },

  stopMainBackend(): Promise<{ status: string }> {
    return controlRequest<{ status: string }>({ url: '/api/stop', method: 'post' });
  },

  restartMainBackend(): Promise<{ status: string }> {
    return controlRequest<{ status: string }>({ url: '/api/restart', method: 'post' });
  },
};
