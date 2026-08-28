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

export const healthApi = {
  /** GET /health —— 连接检测门使用的轻量探活端点 */
  getHealth(): Promise<HealthStatus> {
    return request<HealthStatus>({ url: '/health' });
  },

  getGraphStats(): Promise<GraphStats> {
    return request<GraphStats>({ url: '/api/graph/stats' });
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

  getLiveClientStatus(): Promise<{ status: string }> {
    return request<{ status: string }>({ url: '/api/live/client/status' });
  },

  async disconnectLiveClient(clientId: string): Promise<void> {
    await request({ url: `/api/live/client/${clientId}/disconnect`, method: 'post' });
  },
};
