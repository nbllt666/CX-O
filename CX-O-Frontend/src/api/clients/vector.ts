/**
 * ApiClient mixin: vectors
 * Extracted from client.ts as part of M16 split.
 */
import { _ApiClientBase } from './_common';
import type { VectorData } from './_types';

export class _VectorClientMixin extends _ApiClientBase {
  async getVectorStats(): Promise<{
    vector_enabled: boolean;
    total_vectors: number;
    total_memories: number;
    indexed_ratio: number;
    backend: string;
    collection_info: Record<string, unknown>;
  }> {
    // 后端返回 { status: "success", stats: {...} }，解包后返回
    const resp = await this.request<{
      status: string;
      stats: {
        vector_enabled: boolean;
        total_vectors: number;
        total_memories: number;
        indexed_ratio: number;
        backend: string;
        collection_info: Record<string, unknown>;
      };
    }>({ url: '/api/vector/stats' });
    return resp.stats;
  }

  async getVector(memoryId: number): Promise<VectorData> {
    return this.request<VectorData>({ url: `/api/vector/vectors/${memoryId}` });
  }

  async deleteVector(memoryId: number): Promise<void> {
    await this.request({ url: `/api/vector/vectors/${memoryId}`, method: 'delete' });
  }

  async listVectors(limit?: number, offset?: number, memoryType?: string): Promise<{ vectors: VectorData[]; total: number }> {
    const params = new URLSearchParams();
    if (limit) params.append('limit', String(limit));
    if (offset) params.append('offset', String(offset));
    if (memoryType) params.append('memory_type', memoryType);
    return this.request({ url: `/api/vector/vectors?${params.toString()}` });
  }

  async searchVectors(query: string, limit?: number): Promise<{ results: VectorData[] }> {
    const params = new URLSearchParams();
    params.append('query', query);
    if (limit) params.append('limit', String(limit));
    // 后端为 POST /api/vector/search，query/limit 走 query string
    return this.request({ url: `/api/vector/search?${params.toString()}`, method: 'post' });
  }

  async syncVectors(): Promise<{ status: string }> {
    return this.request({ url: '/api/vector/sync', method: 'post' });
  }

  async rebuildVectors(): Promise<{ status: string }> {
    return this.request({ url: '/api/vector/rebuild', method: 'post' });
  }
}
