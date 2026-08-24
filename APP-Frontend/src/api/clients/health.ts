/**
 * health 域客户端：健康检查与状态查询。
 * 端点面对齐 CX-O-Frontend clients/health.ts。
 */
import { request, voiceWorkstationRequest } from '../base';
import type { GraphStats, HealthStatus } from '../types';

export interface VectorStatus {
  vector_enabled: boolean;
  vector_backend: string;
  connected: boolean;
  collection_info: Record<string, unknown>;
}

export interface RefsStatus {
  emotions_count: number;
  transitions_count: number;
  total_count: number;
  is_complete: boolean;
  expected_total: number;
}

export const healthApi = {
  /** GET /health —— 连接检测门使用的轻量探活端点 */
  getHealth(): Promise<HealthStatus> {
    return request<HealthStatus>({ url: '/health' });
  },

  getGraphHealth(): Promise<{ connected: boolean; message?: string }> {
    return request<{ connected: boolean; message?: string }>({ url: '/api/graph/health' });
  },

  getGraphStats(): Promise<GraphStats> {
    return request<GraphStats>({ url: '/api/graph/stats' });
  },

  async testGraphConnection(): Promise<{ status: string; message: string }> {
    const data = await request<Record<string, unknown>>({ url: '/api/graph/health' });
    const overall = String(data.overall ?? 'unknown');
    return { status: overall === 'healthy' ? 'connected' : 'error', message: overall };
  },

  /** 后端返回 { status, vector_status }，解包后返回 */
  async getVectorStatus(): Promise<VectorStatus> {
    const resp = await request<{ status: string; vector_status: VectorStatus }>({
      url: '/api/vector/status',
    });
    return resp.vector_status;
  },

  getGraphStatus(): Promise<GraphStats> {
    return request<GraphStats>({ url: '/api/graph/status' });
  },

  getVoiceWorkstationStatus(): Promise<{ status: string }> {
    return voiceWorkstationRequest<{ status: string }>({ url: '/health' });
  },

  getRefsStatus(): Promise<RefsStatus> {
    return voiceWorkstationRequest<RefsStatus>({ url: '/refs-status' });
  },

  getLiveClientStatus(): Promise<{ status: string }> {
    return request<{ status: string }>({ url: '/api/live/client/status' });
  },

  async disconnectLiveClient(clientId: string): Promise<void> {
    await request({ url: `/api/live/client/${clientId}/disconnect`, method: 'post' });
  },
};
