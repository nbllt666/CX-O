/**
 * ApiClient mixin: vectors
 * Extracted from client.ts as part of M16 split.
 */
import type { _ApiClientBase } from './_common';
import type { VectorData } from './_types';

export interface _VectorClientMixin extends _ApiClientBase {}

export class _VectorClientMixin {
  async getVectorStats(): Promise<{ total: number; by_type: Record<string, number> }> {
    return this.request<{ total: number; by_type: Record<string, number> }>({ url: '/api/vector/stats' });
  }

  async getVector(memoryId: number): Promise<VectorData> {
    return this.request<VectorData>({ url: `/api/vector/${memoryId}` });
  }

  async deleteVector(memoryId: number): Promise<void> {
    await this.request({ url: `/api/vector/${memoryId}`, method: 'delete' });
  }

  async listVectors(limit?: number, offset?: number): Promise<{ vectors: VectorData[]; total: number }> {
    const params = new URLSearchParams();
    if (limit) params.append('limit', String(limit));
    if (offset) params.append('offset', String(offset));
    return this.request({ url: `/api/vectors?${params.toString()}` });
  }

  async searchVectors(query: string, limit?: number): Promise<{ results: VectorData[] }> {
    const params = new URLSearchParams();
    params.append('query', query);
    if (limit) params.append('limit', String(limit));
    return this.request({ url: `/api/vectors/search?${params.toString()}` });
  }

  async syncVectors(): Promise<{ status: string }> {
    return this.request({ url: '/api/vectors/sync', method: 'post' });
  }

  async rebuildVectors(): Promise<{ status: string }> {
    return this.request({ url: '/api/vectors/rebuild', method: 'post' });
  }
}
