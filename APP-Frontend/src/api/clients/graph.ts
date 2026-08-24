/**
 * graph 域客户端：图数据库节点 / 边 / 语义搜索 / 算法。
 * 端点面对齐 CX-O-Frontend clients/graph.ts（/api/graph/*，支持 agent_id 隔离；
 * 保留旧版 entity/relation API 兼容）。
 */
import { request } from '../base';
import type { GraphEntity, GraphRelation } from '../types';

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

export interface GraphStatsV2 {
  node_count: number;
  edge_count: number;
  node_types?: Record<string, number>;
  edge_types?: Record<string, number>;
}

export interface GraphHealthV2 {
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

interface PageResult<T> {
  items?: T[];
  nodes?: T[];
  edges?: T[];
  total?: number;
  offset?: number;
  limit?: number;
  has_more?: boolean;
}

export const graphApi = {
  // ── 新版 Node/Edge API（/api/graph/*） ──

  createNode(data: NodeCreateInput, agentId = 'default'): Promise<GraphNode> {
    return request<GraphNode>({
      url: '/api/graph/nodes',
      method: 'post',
      data: { ...data, agent_id: agentId },
    });
  },

  async getNode(nodeId: string, agentId = 'default'): Promise<GraphNode | null> {
    try {
      return await request<GraphNode>({
        url: `/api/graph/nodes/${encodeURIComponent(nodeId)}`,
        params: { agent_id: agentId },
      });
    } catch {
      return null;
    }
  },

  updateNode(
    nodeId: string,
    data: { type?: string; properties?: Record<string, unknown>; text_content?: string },
    agentId = 'default',
  ): Promise<GraphNode | null> {
    return request<GraphNode | null>({
      url: `/api/graph/nodes/${encodeURIComponent(nodeId)}`,
      method: 'put',
      data,
      params: { agent_id: agentId },
    });
  },

  deleteNode(
    nodeId: string,
    cascade = true,
    agentId = 'default',
  ): Promise<{ status: string; message: string }> {
    return request<{ status: string; message: string }>({
      url: `/api/graph/nodes/${encodeURIComponent(nodeId)}`,
      method: 'delete',
      params: { cascade, agent_id: agentId },
    });
  },

  getNodes(params?: {
    node_type?: string;
    limit?: number;
    offset?: number;
    agent_id?: string;
  }): Promise<PageResult<GraphNode>> {
    return request<PageResult<GraphNode>>({ url: '/api/graph/nodes/search', params });
  },

  getNodeNeighbors(
    nodeId: string,
    params?: { max_depth?: number; direction?: string; agent_id?: string },
  ): Promise<{ node_id: string; neighbors: { node: GraphNode; edges: GraphEdge[] }[] }> {
    return request({
      url: `/api/graph/nodes/${encodeURIComponent(nodeId)}/neighbors`,
      params,
    });
  },

  createEdge(data: EdgeCreateInput, agentId = 'default'): Promise<GraphEdge> {
    return request<GraphEdge>({
      url: '/api/graph/edges',
      method: 'post',
      data: { ...data, agent_id: agentId },
    });
  },

  async getEdge(edgeId: string, agentId = 'default'): Promise<GraphEdge | null> {
    try {
      return await request<GraphEdge>({
        url: `/api/graph/edges/${encodeURIComponent(edgeId)}`,
        params: { agent_id: agentId },
      });
    } catch {
      return null;
    }
  },

  deleteEdge(edgeId: string, agentId = 'default'): Promise<{ status: string; message: string }> {
    return request<{ status: string; message: string }>({
      url: `/api/graph/edges/${encodeURIComponent(edgeId)}`,
      method: 'delete',
      params: { agent_id: agentId },
    });
  },

  getEdges(params?: {
    relation_type?: string;
    source_id?: string;
    target_id?: string;
    limit?: number;
    offset?: number;
    agent_id?: string;
  }): Promise<PageResult<GraphEdge>> {
    return request<PageResult<GraphEdge>>({ url: '/api/graph/edges/search', params });
  },

  graphSemanticSearch(data: {
    query: string;
    node_type?: string;
    limit?: number;
    agent_id?: string;
  }): Promise<{ query: string; results: SemanticSearchResultItem[] }> {
    return request({ url: '/api/graph/semantic/search', method: 'post', data });
  },

  graphHybridSearch(data: {
    query: string;
    node_type?: string;
    properties_filter?: Record<string, unknown>;
    limit?: number;
    agent_id?: string;
  }): Promise<{ query: string; results: SemanticSearchResultItem[] }> {
    return request({ url: '/api/graph/semantic/hybrid', method: 'post', data });
  },

  getGraphStatsV2(agentId = 'default'): Promise<GraphStatsV2> {
    return request<GraphStatsV2>({ url: '/api/graph/stats', params: { agent_id: agentId } });
  },

  getGraphHealthV2(agentId = 'default'): Promise<GraphHealthV2> {
    return request<GraphHealthV2>({ url: '/api/graph/health', params: { agent_id: agentId } });
  },

  getImportantNodes(params?: { limit?: number; agent_id?: string }): Promise<{
    limit: number;
    nodes: { node: GraphNode; pagerank: number }[];
  }> {
    return request({ url: '/api/graph/algorithm/important-nodes', params });
  },

  pageRank(params?: { damping?: number; max_iterations?: number; agent_id?: string }): Promise<{
    damping: number;
    scores: Record<string, number>;
  }> {
    return request({ url: '/api/graph/algorithm/pagerank', params });
  },

  // ── 旧版 Entity/Relation API（兼容 GraphDataPage） ──

  getGraphEntityTypes(library = 'thing'): Promise<{ types: string[]; entity_types?: string[] }> {
    return request({ url: `/api/graph/${encodeURIComponent(library)}/entity-types` });
  },

  getGraphRelationTypes(library = 'thing'): Promise<{ types: string[]; relation_types?: string[] }> {
    return request({ url: `/api/graph/${encodeURIComponent(library)}/relation-types` });
  },

  async deleteGraphEntity(library: string, entityId: string): Promise<void> {
    await request({
      url: `/api/graph/${encodeURIComponent(library)}/entities/${encodeURIComponent(entityId)}`,
      method: 'delete',
    });
  },

  async deleteGraphRelation(
    library: string,
    params: { source_id: string; target_id: string; relation_type: string },
  ): Promise<void> {
    await request({
      url: `/api/graph/${encodeURIComponent(library)}/relations`,
      method: 'delete',
      data: params,
    });
  },

  listGraphEntities(entityType?: string, limit?: number): Promise<{ entities: GraphEntity[] }> {
    const params = new URLSearchParams();
    if (entityType) params.append('entity_type', entityType);
    if (limit) params.append('limit', String(limit));
    const qs = params.toString();
    return request({ url: `/api/graph/entities${qs ? `?${qs}` : ''}` });
  },

  listGraphRelations(relationType?: string, limit?: number): Promise<{ relations: GraphRelation[] }> {
    const params = new URLSearchParams();
    if (relationType) params.append('relation_type', relationType);
    if (limit) params.append('limit', String(limit));
    const qs = params.toString();
    return request({ url: `/api/graph/relations${qs ? `?${qs}` : ''}` });
  },

  createGraphEntity(entityType: string, entityData: Record<string, unknown>): Promise<GraphEntity> {
    return request({
      url: '/api/graph/entities',
      method: 'post',
      data: { entity_type: entityType, ...entityData },
    });
  },

  createGraphRelation(
    relationType: string,
    sourceId: string,
    targetId: string,
    relationData?: Record<string, unknown>,
  ): Promise<GraphRelation> {
    return request({
      url: '/api/graph/relations',
      method: 'post',
      data: { relation_type: relationType, source_id: sourceId, target_id: targetId, ...relationData },
    });
  },

  findGraphPath(sourceId: string, targetId: string, maxDepth?: number): Promise<{ path: GraphEntity[] }> {
    const params = new URLSearchParams();
    params.append('start_id', sourceId);
    params.append('end_id', targetId);
    if (maxDepth) params.append('max_length', String(maxDepth));
    return request({ url: `/api/graph/paths/shortest?${params.toString()}` });
  },
};
