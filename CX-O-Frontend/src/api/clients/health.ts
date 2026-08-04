/**
 * ApiClient mixin: health & status 查询
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';
import type { HealthStatus, GraphStats } from './_types';

export class _HealthClientMixin extends _ApiClientBase {
  async getHealth(): Promise<HealthStatus> {
    return this.request<HealthStatus>({ url: '/health' });
  }

  async getGraphHealth(): Promise<{ connected: boolean; message?: string }> {
    return this.request<{ connected: boolean; message?: string }>({ url: '/api/graph/health' });
  }

  async getGraphStats(): Promise<GraphStats> {
    return this.request<GraphStats>({ url: '/api/graph/stats' });
  }

  async testGraphConnection(): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>({ url: '/api/graph/test' });
  }

  async getVectorStatus(): Promise<{
    vector_enabled: boolean;
    vector_backend: string;
    connected: boolean;
    collection_info: Record<string, unknown>;
  }> {
    // 后端返回 { status: "success", vector_status: {...} }，解包后返回
    const resp = await this.request<{
      status: string;
      vector_status: {
        vector_enabled: boolean;
        vector_backend: string;
        connected: boolean;
        collection_info: Record<string, unknown>;
      };
    }>({ url: '/api/vector/status' });
    return resp.vector_status;
  }

  async getGraphStatus(): Promise<GraphStats> {
    return this.request<GraphStats>({ url: '/api/graph/status' });
  }

  async getVoiceWorkstationStatus(): Promise<{ status: string }> {
    return this.voiceWorkstationRequest<{ status: string }>({ url: '/health' });
  }

  async getRefsStatus(): Promise<{
    emotions_count: number;
    transitions_count: number;
    total_count: number;
    is_complete: boolean;
    expected_total: number;
  }> {
    return this.voiceWorkstationRequest<{
      emotions_count: number;
      transitions_count: number;
      total_count: number;
      is_complete: boolean;
      expected_total: number;
    }>({ url: '/refs-status' });
  }

  async getLiveClientStatus(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/live/client/status' });
  }

  async disconnectLiveClient(clientId: string): Promise<void> {
    await this.request({ url: `/api/live/client/${clientId}/disconnect`, method: 'post' });
  }
}
