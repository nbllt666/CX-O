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

  async getVectorStatus(): Promise<{ status: string; backend: string; connected: boolean }> {
    return this.request<{ status: string; backend: string; connected: boolean }>({ url: '/api/vector/status' });
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

  async getF5TTSFinetuneStatus(): Promise<{
    status: string;
    progress?: number;
    message?: string;
  }> {
    return this.voiceWorkstationRequest<{
      status: string;
      progress?: number;
      message?: string;
    }>({ url: '/f5tts/finetune/status' });
  }

  async stopSoVITSSVCTrain(): Promise<{ status: string }> {
    return this.voiceWorkstationRequest<{ status: string }>({
      url: '/sovits-svc/train/stop',
      method: 'POST',
    });
  }

  async getSoVITSSVCStatus(): Promise<{
    status: string;
    progress?: number;
    message?: string;
    models?: string[];
  }> {
    return this.voiceWorkstationRequest<{
      status: string;
      progress?: number;
      message?: string;
      models?: string[];
    }>({ url: '/sovits-svc/status' });
  }

  async getVoxCPMStatus(): Promise<{ status: string; model_path: string }> {
    return this.voiceWorkstationRequest<{ status: string; model_path: string }>({
      url: '/api/voxcpm/status',
    });
  }

  async getLiveClientStatus(): Promise<{ status: string }> {
    return this.request<{ status: string }>({ url: '/api/live/client/status' });
  }

  async disconnectLiveClient(clientId: string): Promise<void> {
    await this.request({ url: `/api/live/client/${clientId}/disconnect`, method: 'post' });
  }
}
