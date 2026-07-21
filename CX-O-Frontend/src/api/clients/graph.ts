/**
 * ApiClient mixin: Graph domain operations.
 * Extracted from client.ts as part of M16 split.
 *
 * 迁移自 CXHMS graph.ts：添加完整 GraphNode/GraphEdge API（路径 /api/graph/*），
 * 支持 agent_id per-agent 隔离。保留旧版 entity/relation API 以兼容 GraphDataPage
 * （阶段1-5 替换 GraphDataPage 后可删除旧方法）。
 * 详见 .trae/documents/20260720_模块0_从CXHMS迁移图数据库.md
 */
import { _ApiClientBase } from './_common';
import type { GraphEntity, GraphRelation } from './_types';

// ============ Type Definitions (迁移自 CXHMS) ============

export interface GraphNode {
  id: string;
  type: string;
  properties?: Record<string, unknown>;
  text_content?: string;
  agent_id?: string;
  created_at?: string;
  updated_at?: string;
}

export interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
  properties?: Record<string, unknown>;
  text_content?: string;
  agent_id?: string;
  created_at?: string;
  updated_at?: string;
}

export interface SemanticSearchResultItem {
  node_id: string;
  node_type?: string;
  text_content?: string;
  score: number;
}

export interface GraphStats {
  node_count: number;
  edge_count: number;
  node_types?: Record<string, number>;
  edge_types?: Record<string, number>;
}

export interface GraphHealth {
  database: string;
  semantic: string;
  overall: string;
}

export interface NodeCreateInput {
  type: string;
  properties?: Record<string, unknown>;
  text_content?: string;
}

export interface EdgeCreateInput {
  source_id: string;
  target_id: string;
  relation_type: string;
  properties?: Record<string, unknown>;
  text_content?: string;
}

export class _GraphClientMixin extends _ApiClientBase {
  // ============ 新版 GraphNode/GraphEdge API（迁移自 CXHMS，路径 /api/graph/*） ============

  async createNode(data: NodeCreateInput, agentId: string = 'default'): Promise<GraphNode> {
    return this.request<GraphNode>({
      url: '/api/graph/nodes',
      method: 'post',
      data: { ...data, agent_id: agentId },
    });
  }

  async getNode(nodeId: string, agentId: string = 'default'): Promise<GraphNode | null> {
    try {
      return await this.request<GraphNode>({
        url: `/api/graph/nodes/${nodeId}`,
        params: { agent_id: agentId },
      });
    } catch {
      return null;
    }
  }

  async updateNode(
    nodeId: string,
    data: { type?: string; properties?: Record<string, unknown>; text_content?: string },
    agentId: string = 'default',
  ): Promise<GraphNode | null> {
    return this.request<GraphNode>({
      url: `/api/graph/nodes/${nodeId}`,
      method: 'put',
      data,
      params: { agent_id: agentId },
    });
  }

  async deleteNode(nodeId: string, cascade: boolean = true, agentId: string = 'default'): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>({
      url: `/api/graph/nodes/${nodeId}`,
      method: 'delete',
      params: { cascade, agent_id: agentId },
    });
  }

  async getNodes(params?: {
    node_type?: string;
    limit?: number;
    offset?: number;
    agent_id?: string;
  }): Promise<{
    items?: GraphNode[];
    nodes?: GraphNode[]; // 兼容字段（若后端返回 nodes 而非 items）
    total?: number;
    offset?: number;
    limit?: number;
    has_more?: boolean;
  }> {
    return this.request<{
      items?: GraphNode[];
      nodes?: GraphNode[];
      total?: number;
      offset?: number;
      limit?: number;
      has_more?: boolean;
    }>({
      url: '/api/graph/nodes/search',
      params,
    });
  }

  async getNodeNeighbors(
    nodeId: string,
    params?: { max_depth?: number; direction?: string; agent_id?: string },
  ): Promise<{
    node_id: string;
    neighbors: { node: GraphNode; edges: GraphEdge[] }[];
  }> {
    return this.request({
      url: `/api/graph/nodes/${nodeId}/neighbors`,
      params,
    });
  }

  async createEdge(data: EdgeCreateInput, agentId: string = 'default'): Promise<GraphEdge> {
    return this.request<GraphEdge>({
      url: '/api/graph/edges',
      method: 'post',
      data: { ...data, agent_id: agentId },
    });
  }

  async getEdge(edgeId: string, agentId: string = 'default'): Promise<GraphEdge | null> {
    try {
      return await this.request<GraphEdge>({
        url: `/api/graph/edges/${edgeId}`,
        params: { agent_id: agentId },
      });
    } catch {
      return null;
    }
  }

  async deleteEdge(edgeId: string, agentId: string = 'default'): Promise<{ status: string; message: string }> {
    return this.request<{ status: string; message: string }>({
      url: `/api/graph/edges/${edgeId}`,
      method: 'delete',
      params: { agent_id: agentId },
    });
  }

  async getEdges(params?: {
    relation_type?: string;
    source_id?: string;
    target_id?: string;
    limit?: number;
    offset?: number;
    agent_id?: string;
  }): Promise<{
    items?: GraphEdge[];
    edges?: GraphEdge[]; // 兼容字段
    total?: number;
    offset?: number;
    limit?: number;
    has_more?: boolean;
  }> {
    return this.request<{
      items?: GraphEdge[];
      edges?: GraphEdge[];
      total?: number;
      offset?: number;
      limit?: number;
      has_more?: boolean;
    }>({
      url: '/api/graph/edges/search',
      params,
    });
  }

  async graphSemanticSearch(data: {
    query: string;
    node_type?: string;
    limit?: number;
    agent_id?: string;
  }): Promise<{ query: string; results: SemanticSearchResultItem[] }> {
    return this.request({
      url: '/api/graph/semantic/search',
      method: 'post',
      data,
    });
  }

  async graphHybridSearch(data: {
    query: string;
    node_type?: string;
    properties_filter?: Record<string, unknown>;
    limit?: number;
    agent_id?: string;
  }): Promise<{ query: string; results: SemanticSearchResultItem[] }> {
    return this.request({
      url: '/api/graph/semantic/hybrid',
      method: 'post',
      data,
    });
  }

  async getGraphStatsV2(agentId: string = 'default'): Promise<GraphStats> {
    return this.request<GraphStats>({
      url: '/api/graph/stats',
      params: { agent_id: agentId },
    });
  }

  async getGraphHealthV2(agentId: string = 'default'): Promise<GraphHealth> {
    return this.request<GraphHealth>({
      url: '/api/graph/health',
      params: { agent_id: agentId },
    });
  }

  async getImportantNodes(params?: { limit?: number; agent_id?: string }): Promise<{
    limit: number;
    nodes: { node: GraphNode; pagerank: number }[];
  }> {
    return this.request({
      url: '/api/graph/algorithm/important-nodes',
      params,
    });
  }

  async pageRank(params?: { damping?: number; max_iterations?: number; agent_id?: string }): Promise<{
    damping: number;
    scores: Record<string, number>;
  }> {
    return this.request({
      url: '/api/graph/algorithm/pagerank',
      params,
    });
  }

  // ============ 旧版 Entity/Relation API（兼容 GraphDataPage，阶段1-5 后可删除） ============

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
