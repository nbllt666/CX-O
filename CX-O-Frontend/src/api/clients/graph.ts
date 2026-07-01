/**
 * ApiClient mixin: Graph domain operations.
 * Extracted from client.ts as part of M16 split.
 */
import type { _ApiClientBase } from './_common';
import type { GraphEntity, GraphRelation } from './_types';

// Declaration merging: let TypeScript know _GraphClientMixin can access _ApiClientBase's methods
export interface _GraphClientMixin extends _ApiClientBase {}

export class _GraphClientMixin {
  async getGraphEntityTypes(library: string = 'thing'): Promise<{ types: string[]; entity_types?: string[] }> {
    return this.request<{ types: string[]; entity_types?: string[] }>({ url: `/api/graph/${library}/entity-types` });
  }

  async getGraphRelationTypes(library: string = 'thing'): Promise<{ types: string[]; relation_types?: string[] }> {
    return this.request<{ types: string[]; relation_types?: string[] }>({ url: `/api/graph/${library}/relation-types` });
  }

  async deleteGraphEntity(library: string, entityId: string): Promise<void> {
    await this.request({ url: `/api/graph/${library}/entities/${entityId}`, method: 'delete' });
  }

  async deleteGraphRelation(library: string, params: { source_id: string; target_id: string; relation_type: string }): Promise<void> {
    await this.request({ url: `/api/graph/${library}/relations`, method: 'delete', data: params });
  }

  async listGraphEntities(entityType?: string, limit?: number): Promise<{ entities: GraphEntity[] }> {
    const params = new URLSearchParams();
    if (entityType) params.append('entity_type', entityType);
    if (limit) params.append('limit', String(limit));
    return this.request({ url: `/api/graph/entities?${params.toString()}` });
  }

  async listGraphRelations(relationType?: string, limit?: number): Promise<{ relations: GraphRelation[] }> {
    const params = new URLSearchParams();
    if (relationType) params.append('relation_type', relationType);
    if (limit) params.append('limit', String(limit));
    return this.request({ url: `/api/graph/relations?${params.toString()}` });
  }

  async createGraphEntity(entityType: string, entityData: Record<string, unknown>): Promise<GraphEntity> {
    return this.request({ url: '/api/graph/entities', method: 'post', data: { entity_type: entityType, ...entityData } });
  }

  async createGraphRelation(relationType: string, sourceId: string, targetId: string, relationData?: Record<string, unknown>): Promise<GraphRelation> {
    return this.request({ url: '/api/graph/relations', method: 'post', data: { relation_type: relationType, source_id: sourceId, target_id: targetId, ...relationData } });
  }

  async findGraphPath(sourceId: string, targetId: string, maxDepth?: number): Promise<{ path: GraphEntity[] }> {
    const params = new URLSearchParams();
    params.append('source_id', sourceId);
    params.append('target_id', targetId);
    if (maxDepth) params.append('max_depth', String(maxDepth));
    return this.request({ url: `/api/graph/path?${params.toString()}` });
  }
}