/**
 * ApiClient mixin: Service control domain operations.
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';

export class _ServiceClientMixin extends _ApiClientBase {
  async getServiceStatus(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/status' });
  }

  async startService(data?: { port?: number }): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/start', method: 'post', data });
  }

  async stopService(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/stop', method: 'post' });
  }

  async restartService(data?: { port?: number }): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/service/restart', method: 'post', data });
  }

  async getServiceLogs(lines: number = 50): Promise<{ logs: string }> {
    return this.request<{ logs: string }>({ url: '/api/service/logs', params: { lines } });
  }

  async getServiceConfig(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/service/config' });
  }

  async updateServiceConfig(config: Record<string, unknown>): Promise<void> {
    await this.request({ url: '/api/service/config', method: 'put', data: config });
  }

  async getEnvironmentInfo(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>({ url: '/api/service/env' });
  }

  async getControlServiceHealth(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/health' });
  }

  async getMainBackendStatus(): Promise<{ running: boolean; version?: string }> {
    return this.controlRequest<{ running: boolean; version?: string }>({ url: '/api/status' });
  }

  async startMainBackend(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/api/start', method: 'post' });
  }

  async stopMainBackend(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/api/stop', method: 'post' });
  }

  async restartMainBackend(): Promise<{ status: string }> {
    return this.controlRequest<{ status: string }>({ url: '/api/restart', method: 'post' });
  }
}