/**
 * vector 域客户端：向量统计 / 向量 CRUD / 搜索 / 同步重建。
 * 端点面对齐 CX-O-Frontend clients/vector.ts。
 */
import { request } from '../base';
import type { VectorData } from '../types';

export interface VectorStats {
  vector_enabled: boolean;
  total_vectors: number;
  total_memories: number;
  indexed_ratio: number;
  backend: string;
  collection_info: Record<string, unknown>;
}

export const vectorApi = {
  /** 后端返回 { status: "success", stats: {...} }，解包后返回 */
  async getVectorStats(): Promise<VectorStats> {
    const resp = await request<{ status: string; stats: VectorStats }>({ url: '/api/vector/stats' });
    return resp.stats;
  },

  getVector(memoryId: number): Promise<VectorData> {
    return request<VectorData>({ url: `/api/vector/vectors/${memoryId}` });
  },

  async deleteVector(memoryId: number): Promise<void> {
    await request({ url: `/api/vector/vectors/${memoryId}`, method: 'delete' });
  },

  listVectors(limit?: number, offset?: number, memoryType?: string): Promise<{ vectors: VectorData[]; total: number }> {
    const params = new URLSearchParams();
    if (limit) params.append('limit', String(limit));
    if (offset) params.append('offset', String(offset));
    if (memoryType) params.append('memory_type', memoryType);
    const qs = params.toString();
    return request({ url: `/api/vector/vectors${qs ? `?${qs}` : ''}` });
  },

  /** 后端为 POST /api/vector/search，query/limit 走 query string */
  searchVectors(query: string, limit?: number): Promise<{ results: VectorData[] }> {
    const params = new URLSearchParams();
    params.append('query', query);
    if (limit) params.append('limit', String(limit));
    return request({ url: `/api/vector/search?${params.toString()}`, method: 'post' });
  },

  syncVectors(): Promise<{ status: string }> {
    return request({ url: '/api/vector/sync', method: 'post' });
  },

  rebuildVectors(): Promise<{ status: string }> {
    return request({ url: '/api/vector/rebuild', method: 'post' });
  },
};
