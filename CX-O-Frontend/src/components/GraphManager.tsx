/**
 * GraphManager 组件 - 图数据库可视化管理（迁移自 CXHMS）
 *
 * 功能：
 * - Agent 选择器（per-agent 隔离）
 * - 节点列表（按 user/thing/concept/event 分类 tab + 分页）
 * - 节点详情面板（属性 + 邻居节点）
 * - 语义搜索
 * - 创建节点/关系 Modal
 * - 可视化 tab（CX-O 独有，集成 GraphVisualization 组件）
 *
 * 适配 CX-O：
 * - api 路径：使用 api/clients/graph.ts 的新版 V2 方法（路径 /api/graph/*）
 * - UI 组件：复用 CX-O 的 ui/ 组件库（Button/Card/Modal/Badge/EmptyState）
 * - 保留 CX-O 独有的 GraphVisualization 作为额外 tab
 *
 * 详见 .trae/documents/20260720_模块0_从CXHMS迁移图数据库.md
 */

import { useState, useEffect, useCallback } from 'react';
import {
  Database,
  Search,
  Plus,
  Trash2,
  X,
  Users,
  Package,
  Lightbulb,
  Calendar,
  Network,
} from 'lucide-react';
import { api } from '../api/client';
import { Card, Modal, Button, Badge, EmptyState, EmptyStateIcon } from './ui';
import type { BadgeVariant } from './ui/Badge';
import { formatRelativeTime, truncate } from '../lib/utils';
import { GraphVisualization } from './GraphVisualization';
import type { GraphNode as VisGraphNode, GraphLink as VisGraphLink } from './GraphVisualization';

// ========== 类型定义 ==========

interface GraphStats {
  node_count: number;
  edge_count: number;
  avg_degree?: number;
  graph_density?: number;
  node_types: Record<string, number>;
  edge_types?: Record<string, number>;
}

interface GraphNode {
  id: string;
  type: string;
  properties?: Record<string, unknown>;
  text_content?: string;
  created_at?: string;
  updated_at?: string;
}

interface NeighborEdge {
  id: string;
  relation_type: string;
  source_id: string;
  target_id: string;
  direction?: 'outgoing' | 'incoming';
}

interface NeighborItem {
  node: GraphNode;
  edges: NeighborEdge[];
}

interface NodeSearchResult {
  items?: GraphNode[];
  nodes?: GraphNode[];
  total: number;
  offset?: number;
  limit?: number;
  has_more?: boolean;
}

interface SemanticSearchResult {
  results?: Array<{
    node_id: string;
    node_type?: string;
    text_content?: string;
    score: number;
  }>;
}

interface GraphEdge {
  id: string;
  source_id: string;
  target_id: string;
  relation_type: string;
}

// ========== 常量映射 ==========

const GRAPH_TABS = [
  { key: 'all', label: '全部', prefix: '' },
  { key: 'user', label: '用户图', prefix: 'user_' },
  { key: 'thing', label: '物品图', prefix: 'thing_' },
  { key: 'concept', label: '概念图', prefix: 'concept_' },
  { key: 'event', label: '事件图', prefix: 'event_' },
  { key: 'visualization', label: '可视化', prefix: '__viz__' },
] as const;

type GraphTabKey = (typeof GRAPH_TABS)[number]['key'];

const ENTITY_TYPES: Record<string, string[]> = {
  user: ['person', 'user', 'contact'],
  thing: ['object', 'item', 'product'],
  concept: ['concept', 'idea', 'topic'],
  event: ['event', 'activity', 'occurrence'],
};

const RELATION_TYPES: Record<string, string[]> = {
  user: ['knows', 'friend', 'family', 'colleague', 'enemy'],
  thing: ['owns', 'part_of', 'similar_to', 'located_at', 'made_of'],
  concept: ['related_to', 'subtopic_of', 'opposite_of', 'implies'],
  event: ['caused', 'followed_by', 'concurrent_with', 'prevents'],
};

const TYPE_ICON_MAP: Record<string, React.ReactNode> = {
  user: <Users className="w-4 h-4" />,
  thing: <Package className="w-4 h-4" />,
  concept: <Lightbulb className="w-4 h-4" />,
  event: <Calendar className="w-4 h-4" />,
};

const TYPE_COLOR_MAP: Record<string, string> = {
  user: 'info',
  thing: 'success',
  concept: 'warning',
  event: 'error',
};

function getGraphCategory(nodeType: string): string {
  if (nodeType.startsWith('user_')) return 'user';
  if (nodeType.startsWith('thing_')) return 'thing';
  if (nodeType.startsWith('concept_')) return 'concept';
  if (nodeType.startsWith('event_')) return 'event';
  return 'default';
}

function getNodeTypeForTab(tabKey: GraphTabKey): string | undefined {
  if (tabKey === 'all' || tabKey === 'visualization') return undefined;
  const tab = GRAPH_TABS.find((t) => t.key === tabKey);
  return tab?.prefix || undefined;
}

// ========== 子组件 ==========

const StatCard: React.FC<{
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}> = ({ title, value, icon, color }) => (
  <Card className="p-4">
    <div className="flex items-center gap-4">
      <div
        className="w-12 h-12 rounded-[var(--radius-lg)] flex items-center justify-center"
        style={{ backgroundColor: `var(--color-${color}-light)` }}
      >
        <span style={{ color: `var(--color-${color})` }}>{icon}</span>
      </div>
      <div>
        <p className="text-sm text-[var(--color-text-secondary)]">{title}</p>
        <p className="text-2xl font-bold text-[var(--color-text-primary)]">{value}</p>
      </div>
    </div>
  </Card>
);

const TypeBreakdownCard: React.FC<{
  category: string;
  count: number;
  icon: React.ReactNode;
}> = ({ category, count, icon }) => {
  const color = TYPE_COLOR_MAP[category] || 'default';
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-[var(--radius-md)] bg-[var(--color-bg-tertiary)]">
      <div
        className="w-8 h-8 rounded-[var(--radius-sm)] flex items-center justify-center"
        style={{ backgroundColor: `var(--color-${color}-light)` }}
      >
        <span style={{ color: `var(--color-${color})` }}>{icon}</span>
      </div>
      <div>
        <p className="text-xs text-[var(--color-text-tertiary)]">
          {category === 'user' ? '用户' : category === 'thing' ? '物品' : category === 'concept' ? '概念' : '事件'}
        </p>
        <p className="text-sm font-semibold text-[var(--color-text-primary)]">{count}</p>
      </div>
    </div>
  );
};

// ========== 主组件 ==========

export function GraphManager() {
  // Agent 选择
  const [agents, setAgents] = useState<Array<{ id: string; name: string }>>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string>('default');

  // 统计数据
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  // 节点列表
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [nodesTotal, setNodesTotal] = useState(0);
  const [nodesLoading, setNodesLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<GraphTabKey>('all');
  const [offset, setOffset] = useState(0);
  const limit = 20;

  // 节点详情
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [neighbors, setNeighbors] = useState<NeighborItem[]>([]);
  const [neighborsLoading, setNeighborsLoading] = useState(false);
  const [detailExpanded, setDetailExpanded] = useState(false);

  // 语义搜索
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Array<{ node_id: string; node_type?: string; text_content?: string; score: number }> | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchVisible, setSearchVisible] = useState(false);

  // 创建节点对话框
  const [createNodeOpen, setCreateNodeOpen] = useState(false);
  const [newNodeType, setNewNodeType] = useState('user_person');
  const [newNodeText, setNewNodeText] = useState('');
  const [newNodeProps, setNewNodeProps] = useState('');
  const [createNodeLoading, setCreateNodeLoading] = useState(false);

  // 创建关系对话框
  const [createEdgeOpen, setCreateEdgeOpen] = useState(false);
  const [edgeSourceId, setEdgeSourceId] = useState('');
  const [edgeTargetId, setEdgeTargetId] = useState('');
  const [edgeRelationType, setEdgeRelationType] = useState('knows');
  const [createEdgeLoading, setCreateEdgeLoading] = useState(false);

  // 可视化数据（CX-O 独有：可视化 tab 显示完整图结构）
  const [vizNodes, setVizNodes] = useState<GraphNode[]>([]);
  const [vizEdges, setVizEdges] = useState<GraphEdge[]>([]);
  const [vizLoading, setVizLoading] = useState(false);

  // ========== 数据加载 ==========

  const loadStats = useCallback(async () => {
    try {
      setStatsLoading(true);
      const data = await api.getGraphStatsV2(selectedAgentId);
      setStats(data as GraphStats);
    } catch (err) {
      console.error('加载图统计失败:', err);
    } finally {
      setStatsLoading(false);
    }
  }, [selectedAgentId]);

  const loadNodes = useCallback(async () => {
    if (activeTab === 'visualization') return;
    try {
      setNodesLoading(true);
      const nodeType = getNodeTypeForTab(activeTab);
      const data = await api.getNodes({ node_type: nodeType, limit, offset, agent_id: selectedAgentId });
      const result = data as NodeSearchResult;
      // 兼容 items/nodes 两种字段名
      const items = result.items || result.nodes || [];
      setNodes(items);
      setNodesTotal(result.total || 0);
    } catch (err) {
      console.error('加载节点列表失败:', err);
    } finally {
      setNodesLoading(false);
    }
  }, [activeTab, offset, selectedAgentId]);

  const loadNeighbors = useCallback(
    async (nodeId: string) => {
      try {
        setNeighborsLoading(true);
        const data = await api.getNodeNeighbors(nodeId, { agent_id: selectedAgentId });
        setNeighbors(data?.neighbors ?? []);
      } catch (err) {
        console.error('加载邻居节点失败:', err);
      } finally {
        setNeighborsLoading(false);
      }
    },
    [selectedAgentId],
  );

  // 加载可视化数据：获取节点和边用于 GraphVisualization 渲染
  const loadVizData = useCallback(async () => {
    try {
      setVizLoading(true);
      const [nodesResp, edgesResp] = await Promise.all([
        api.getNodes({ limit: 200, agent_id: selectedAgentId }),
        api.getEdges({ limit: 200, agent_id: selectedAgentId }),
      ]);
      const nodesResult = nodesResp as NodeSearchResult;
      setVizNodes(nodesResult.items || nodesResult.nodes || []);
      const edgesResult = edgesResp as { items?: GraphEdge[]; edges?: GraphEdge[] };
      setVizEdges(edgesResult.items || edgesResult.edges || []);
    } catch (err) {
      console.error('加载可视化数据失败:', err);
    } finally {
      setVizLoading(false);
    }
  }, [selectedAgentId]);

  useEffect(() => {
    loadStats();
    loadNodes();
    if (activeTab === 'visualization') {
      loadVizData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgentId, activeTab, offset]);

  useEffect(() => {
    const loadAgents = async () => {
      try {
        const data = await api.getAgents();
        const agentList = Array.isArray(data) ? data : ((data as unknown as { agents?: Array<{ id: string; name: string }> }).agents ?? []);
        setAgents(agentList);
      } catch (e) {
        console.error('Failed to load agents:', e);
      }
    };
    loadAgents();
  }, []);

  // ========== 事件处理 ==========

  const handleSelectNode = (node: GraphNode) => {
    if (selectedNode?.id === node.id) {
      setSelectedNode(null);
      setNeighbors([]);
      setDetailExpanded(false);
    } else {
      setSelectedNode(node);
      setDetailExpanded(true);
      loadNeighbors(node.id);
    }
  };

  const handleDeleteNode = async (nodeId: string) => {
    if (!window.confirm('确定要删除此节点吗？相关的关系也会被删除。')) return;
    try {
      await api.deleteNode(nodeId, true, selectedAgentId);
      if (selectedNode?.id === nodeId) {
        setSelectedNode(null);
        setNeighbors([]);
        setDetailExpanded(false);
      }
      loadNodes();
      loadStats();
    } catch (err) {
      console.error('删除节点失败:', err);
      alert('删除节点失败: ' + (err instanceof Error ? err.message : '未知错误'));
    }
  };

  const handleSemanticSearch = async () => {
    if (!searchQuery.trim()) return;
    try {
      setSearchLoading(true);
      setSearchVisible(true);
      const nodeType = getNodeTypeForTab(activeTab);
      const data = await api.graphSemanticSearch({
        query: searchQuery,
        node_type: nodeType,
        limit: 20,
        agent_id: selectedAgentId,
      });
      const result = data as SemanticSearchResult;
      setSearchResults(result.results || []);
    } catch (err) {
      console.error('语义搜索失败:', err);
      setSearchResults([]);
    } finally {
      setSearchLoading(false);
    }
  };

  const handleCreateNode = async () => {
    if (!newNodeType.trim()) return;
    try {
      setCreateNodeLoading(true);
      const props = newNodeProps.trim() ? JSON.parse(newNodeProps) : undefined;
      await api.createNode(
        {
          type: newNodeType,
          text_content: newNodeText || undefined,
          properties: props,
        },
        selectedAgentId,
      );
      setCreateNodeOpen(false);
      setNewNodeText('');
      setNewNodeProps('');
      loadNodes();
      loadStats();
    } catch (err) {
      console.error('创建节点失败:', err);
      alert('创建节点失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setCreateNodeLoading(false);
    }
  };

  const handleCreateEdge = async () => {
    if (!edgeSourceId.trim() || !edgeTargetId.trim() || !edgeRelationType.trim()) return;
    try {
      setCreateEdgeLoading(true);
      await api.createEdge(
        {
          source_id: edgeSourceId,
          target_id: edgeTargetId,
          relation_type: edgeRelationType,
        },
        selectedAgentId,
      );
      setCreateEdgeOpen(false);
      setEdgeSourceId('');
      setEdgeTargetId('');
      if (selectedNode) {
        loadNeighbors(selectedNode.id);
      }
      loadStats();
    } catch (err) {
      console.error('创建关系失败:', err);
      alert('创建关系失败: ' + (err instanceof Error ? err.message : '未知错误'));
    } finally {
      setCreateEdgeLoading(false);
    }
  };

  const handleTabChange = (tabKey: GraphTabKey) => {
    setActiveTab(tabKey);
    setOffset(0);
    setSearchVisible(false);
    setSearchResults(null);
    setSearchQuery('');
    // 切换 tab 时关闭详情面板
    if (tabKey === 'visualization') {
      setDetailExpanded(false);
      setSelectedNode(null);
      setNeighbors([]);
    }
  };

  const handlePagePrev = () => setOffset(Math.max(0, offset - limit));
  const handlePageNext = () => {
    if (offset + limit < nodesTotal) setOffset(offset + limit);
  };

  // 计算类型分布
  const typeBreakdown = stats?.node_types
    ? Object.entries(stats.node_types).reduce(
        (acc, [type, count]) => {
          const cat = getGraphCategory(type);
          acc[cat] = (acc[cat] || 0) + count;
          return acc;
        },
        {} as Record<string, number>,
      )
    : {};

  // 当前显示的节点列表（搜索结果或普通列表）
  const displayNodes: GraphNode[] =
    searchVisible && searchResults
      ? searchResults.map((r) => ({
          id: r.node_id,
          type: r.node_type || 'unknown',
          text_content: r.text_content,
        }))
      : nodes;

  const totalPages = Math.ceil(nodesTotal / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  return (
    <div className="flex flex-col h-full">
      {/* ========== 顶部统计 ========== */}
      <div className="px-4 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Database className="w-5 h-5 text-[var(--color-accent)]" />
            <h2 className="font-semibold text-[var(--color-text-primary)]">图数据库管理</h2>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" icon={<Plus className="w-4 h-4" />} onClick={() => setCreateNodeOpen(true)}>
              创建节点
            </Button>
            <Button variant="secondary" size="sm" icon={<Plus className="w-4 h-4" />} onClick={() => setCreateEdgeOpen(true)}>
              创建关系
            </Button>
          </div>
        </div>

        {/* Agent 选择器 */}
        <div style={{ marginBottom: 16 }}>
          <label style={{ marginRight: 8, fontWeight: 500 }}>Agent:</label>
          <select
            value={selectedAgentId}
            onChange={(e) => setSelectedAgentId(e.target.value)}
            style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #d9d9d9' }}
          >
            <option value="default">默认助手</option>
            {agents
              .filter((a) => a.id !== 'default')
              .map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.name}
                </option>
              ))}
          </select>
        </div>

        <div className="grid grid-cols-3 gap-3 mb-3">
          {statsLoading ? (
            <>
              <Card className="p-4">
                <div className="h-12 animate-pulse bg-[var(--color-bg-tertiary)] rounded" />
              </Card>
              <Card className="p-4">
                <div className="h-12 animate-pulse bg-[var(--color-bg-tertiary)] rounded" />
              </Card>
              <Card className="p-4">
                <div className="h-12 animate-pulse bg-[var(--color-bg-tertiary)] rounded" />
              </Card>
            </>
          ) : (
            <>
              <StatCard title="总节点数" value={stats?.node_count ?? 0} icon={<Database className="w-5 h-5" />} color="accent" />
              <StatCard title="总边数" value={stats?.edge_count ?? 0} icon={<Database className="w-5 h-5" />} color="success" />
              <StatCard
                title="图密度"
                value={stats?.graph_density != null ? stats.graph_density.toFixed(4) : '0'}
                icon={<Database className="w-5 h-5" />}
                color="warning"
              />
            </>
          )}
        </div>

        <div className="grid grid-cols-4 gap-2">
          {(['user', 'thing', 'concept', 'event'] as const).map((cat) => (
            <TypeBreakdownCard key={cat} category={cat} count={typeBreakdown[cat] || 0} icon={TYPE_ICON_MAP[cat]} />
          ))}
        </div>
      </div>

      {/* ========== 搜索栏（仅非可视化 tab 显示） ========== */}
      {activeTab !== 'visualization' && (
        <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-text-tertiary)]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSemanticSearch()}
                placeholder="语义搜索节点..."
                className="w-full pl-10 pr-4 py-2 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-tertiary)] text-[var(--color-text-primary)] border border-[var(--color-border)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent transition-all"
              />
            </div>
            <Button variant="primary" size="sm" onClick={handleSemanticSearch} loading={searchLoading} icon={<Search className="w-4 h-4" />}>
              搜索
            </Button>
            {searchVisible && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearchVisible(false);
                  setSearchResults(null);
                  setSearchQuery('');
                }}
                icon={<X className="w-4 h-4" />}
              >
                清除
              </Button>
            )}
          </div>
        </div>
      )}

      {/* ========== 标签页 + 内容区 ========== */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：标签页 + 节点列表 / 可视化 */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* 标签页 */}
          <div className="flex border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]">
            {GRAPH_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => handleTabChange(tab.key)}
                className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 flex items-center gap-1 ${
                  activeTab === tab.key
                    ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                    : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:border-[var(--color-border)]'
                }`}
              >
                {tab.key === 'visualization' && <Network className="w-3.5 h-3.5" />}
                {tab.label}
              </button>
            ))}
          </div>

          {/* 内容区：可视化 tab 或节点列表 */}
          {activeTab === 'visualization' ? (
            <div className="flex-1 overflow-hidden p-4">
              {vizLoading ? (
                <div className="flex items-center justify-center h-full">
                  <div className="text-sm text-[var(--color-text-tertiary)]">加载图中...</div>
                </div>
              ) : vizNodes.length === 0 ? (
                <EmptyState icon={<EmptyStateIcon type="folder" />} title="暂无图数据" description="创建节点后可在此查看可视化" />
              ) : (
                <GraphVisualization
                  nodes={vizNodes.map((n): VisGraphNode => ({
                    id: n.id,
                    name: (n.properties?.name as string) || n.id,
                    type: n.type,
                    data: n.properties,
                  }))}
                  links={vizEdges.map((e): VisGraphLink => ({
                    source: e.source_id,
                    target: e.target_id,
                    type: e.relation_type,
                  }))}
                  width={800}
                  height={500}
                  onNodeClick={(node) => {
                    // 点击可视化节点时切换到全部 tab 并选中该节点
                    const graphNode: GraphNode = {
                      id: node.id,
                      type: node.type || 'unknown',
                      properties: node.data,
                    };
                    handleTabChange('all');
                    setSelectedNode(graphNode);
                    setDetailExpanded(true);
                    loadNeighbors(graphNode.id);
                  }}
                />
              )}
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {searchVisible && searchResults !== null ? (
                searchResults.length === 0 ? (
                  <EmptyState icon={<EmptyStateIcon type="search" />} title="未找到匹配节点" description="尝试使用不同的搜索词" />
                ) : (
                  <div className="divide-y divide-[var(--color-border)]">
                    {searchResults.map((result) => {
                      const cat = getGraphCategory(result.node_type || '');
                      return (
                        <div
                          key={result.node_id}
                          onClick={() =>
                            handleSelectNode({
                              id: result.node_id,
                              type: result.node_type || 'unknown',
                              text_content: result.text_content,
                            })
                          }
                          className={`px-4 py-3 cursor-pointer hover:bg-[var(--color-bg-hover)] transition-colors ${
                            selectedNode?.id === result.node_id ? 'bg-[var(--color-accent-light)]' : ''
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 min-w-0">
                              <Badge variant={TYPE_COLOR_MAP[cat] as BadgeVariant} size="sm">
                                {result.node_type}
                              </Badge>
                              <span className="text-sm font-medium text-[var(--color-text-primary)] truncate">{result.node_id}</span>
                            </div>
                            <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                              <span className="text-xs text-[var(--color-text-tertiary)]">相似度: {(result.score * 100).toFixed(1)}%</span>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteNode(result.node_id);
                                }}
                                className="p-1 text-[var(--color-text-tertiary)] hover:text-[var(--color-error)] transition-colors"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          </div>
                          {result.text_content && (
                            <p className="mt-1 text-xs text-[var(--color-text-secondary)] truncate">{truncate(result.text_content, 100)}</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )
              ) : nodesLoading ? (
                <div className="p-4 space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-16 animate-pulse bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)]" />
                  ))}
                </div>
              ) : displayNodes.length === 0 ? (
                <EmptyState icon={<EmptyStateIcon type="folder" />} title="暂无节点" description="点击「创建节点」添加第一个节点" />
              ) : (
                <div className="divide-y divide-[var(--color-border)]">
                  {displayNodes.map((node) => {
                    const cat = getGraphCategory(node.type);
                    return (
                      <div
                        key={node.id}
                        onClick={() => handleSelectNode(node)}
                        className={`px-4 py-3 cursor-pointer hover:bg-[var(--color-bg-hover)] transition-colors ${
                          selectedNode?.id === node.id ? 'bg-[var(--color-accent-light)]' : ''
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge variant={TYPE_COLOR_MAP[cat] as BadgeVariant} size="sm">
                              {node.type}
                            </Badge>
                            <span className="text-sm font-medium text-[var(--color-text-primary)] truncate">
                              {(node.properties?.name as string) || node.id}
                            </span>
                          </div>
                          <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                            {node.created_at && (
                              <span className="text-xs text-[var(--color-text-tertiary)]">{formatRelativeTime(node.created_at)}</span>
                            )}
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteNode(node.id);
                              }}
                              className="p-1 text-[var(--color-text-tertiary)] hover:text-[var(--color-error)] transition-colors"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                        {node.text_content && (
                          <p className="mt-1 text-xs text-[var(--color-text-secondary)] truncate">{truncate(node.text_content, 100)}</p>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* 分页 */}
              {!searchVisible && nodesTotal > 0 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-[var(--color-border)] bg-[var(--color-bg-secondary)]">
                  <span className="text-xs text-[var(--color-text-tertiary)]">
                    共 {nodesTotal} 个节点，第 {currentPage}/{totalPages} 页
                  </span>
                  <div className="flex gap-2">
                    <Button variant="ghost" size="sm" disabled={offset === 0} onClick={handlePagePrev}>
                      上一页
                    </Button>
                    <Button variant="ghost" size="sm" disabled={offset + limit >= nodesTotal} onClick={handlePageNext}>
                      下一页
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* 右侧：节点详情面板（仅非可视化 tab 显示） */}
        {detailExpanded && selectedNode && activeTab !== 'visualization' && (
          <div className="w-80 border-l border-[var(--color-border)] bg-[var(--color-bg-secondary)] flex flex-col overflow-hidden">
            {/* 详情头部 */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">节点详情</h3>
              <button
                onClick={() => {
                  setDetailExpanded(false);
                  setSelectedNode(null);
                  setNeighbors([]);
                }}
                className="p-1 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)] transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 详情内容 */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {/* 基本信息 */}
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant={TYPE_COLOR_MAP[getGraphCategory(selectedNode.type)] as BadgeVariant} size="sm">
                    {selectedNode.type}
                  </Badge>
                  <span className="text-sm font-medium text-[var(--color-text-primary)]">
                    {(selectedNode.properties?.name as string) || selectedNode.id}
                  </span>
                </div>
                <div className="space-y-1 text-xs text-[var(--color-text-secondary)]">
                  <p>
                    <span className="text-[var(--color-text-tertiary)]">ID:</span> {selectedNode.id}
                  </p>
                  {selectedNode.created_at && (
                    <p>
                      <span className="text-[var(--color-text-tertiary)]">创建时间:</span> {formatRelativeTime(selectedNode.created_at)}
                    </p>
                  )}
                  {selectedNode.updated_at && (
                    <p>
                      <span className="text-[var(--color-text-tertiary)]">更新时间:</span> {formatRelativeTime(selectedNode.updated_at)}
                    </p>
                  )}
                </div>
              </div>

              {/* 文本内容 */}
              {selectedNode.text_content && (
                <div>
                  <h4 className="text-xs font-medium text-[var(--color-text-tertiary)] mb-1">文本内容</h4>
                  <div className="text-sm text-[var(--color-text-primary)] bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] p-3 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {selectedNode.text_content}
                  </div>
                </div>
              )}

              {/* 属性 JSON */}
              {selectedNode.properties && Object.keys(selectedNode.properties).length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-[var(--color-text-tertiary)] mb-1">属性</h4>
                  <pre className="text-xs text-[var(--color-text-primary)] bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] p-3 overflow-x-auto max-h-40 overflow-y-auto">
                    {JSON.stringify(selectedNode.properties, null, 2)}
                  </pre>
                </div>
              )}

              {/* 邻居节点 */}
              <div>
                <h4 className="text-xs font-medium text-[var(--color-text-tertiary)] mb-2">相邻节点 ({neighbors.length})</h4>
                {neighborsLoading ? (
                  <div className="space-y-2">
                    {Array.from({ length: 3 }).map((_, i) => (
                      <div key={i} className="h-10 animate-pulse bg-[var(--color-bg-tertiary)] rounded-[var(--radius-sm)]" />
                    ))}
                  </div>
                ) : neighbors.length === 0 ? (
                  <p className="text-xs text-[var(--color-text-tertiary)]">无相邻节点</p>
                ) : (
                  <div className="space-y-2">
                    {neighbors.map((neighbor, idx) => {
                      const neighborNode = neighbor.node;
                      const edge = neighbor.edges?.[0];
                      const cat = getGraphCategory(neighborNode.type);
                      return (
                        <div key={neighborNode.id || idx} className="p-2 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-sm)]">
                          <div className="flex items-center gap-2">
                            <Badge variant={TYPE_COLOR_MAP[cat] as BadgeVariant} size="sm">
                              {neighborNode.type}
                            </Badge>
                            <span className="text-xs font-medium text-[var(--color-text-primary)] truncate">
                              {(neighborNode.properties?.name as string) || neighborNode.id}
                            </span>
                          </div>
                          {edge && (
                            <div className="mt-1 flex items-center gap-1 text-[10px] text-[var(--color-text-tertiary)]">
                              <span className={`px-1 py-0.5 rounded bg-[var(--color-accent-light)] text-[var(--color-accent)]`}>
                                {edge.relation_type}
                              </span>
                              <span>{edge.direction === 'outgoing' ? '→' : '←'}</span>
                              <span>{edge.direction === 'outgoing' ? '出边' : '入边'}</span>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* 删除按钮 */}
              <Button variant="danger" size="sm" className="w-full" icon={<Trash2 className="w-4 h-4" />} onClick={() => handleDeleteNode(selectedNode.id)}>
                删除此节点
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* ========== 创建节点对话框 ========== */}
      <Modal
        isOpen={createNodeOpen}
        onClose={() => setCreateNodeOpen(false)}
        title="创建节点"
        size="md"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateNodeOpen(false)}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={handleCreateNode} loading={createNodeLoading}>
              创建
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">节点类型</label>
            <select
              value={newNodeType}
              onChange={(e) => setNewNodeType(e.target.value)}
              className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent"
            >
              {Object.entries(ENTITY_TYPES).map(([category, types]) => (
                <optgroup
                  key={category}
                  label={
                    category === 'user' ? '用户类型' : category === 'thing' ? '物品类型' : category === 'concept' ? '概念类型' : '事件类型'
                  }
                >
                  {types.map((t) => (
                    <option key={`${category}_${t}`} value={`${category}_${t}`}>
                      {category}_{t}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">文本内容</label>
            <textarea
              value={newNodeText}
              onChange={(e) => setNewNodeText(e.target.value)}
              placeholder="输入节点的文本内容..."
              className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent resize-none min-h-[100px]"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">属性 (JSON)</label>
            <textarea
              value={newNodeProps}
              onChange={(e) => setNewNodeProps(e.target.value)}
              placeholder='{"name": "示例", "key": "value"}'
              className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent resize-none min-h-[80px] font-mono"
            />
          </div>
        </div>
      </Modal>

      {/* ========== 创建关系对话框 ========== */}
      <Modal
        isOpen={createEdgeOpen}
        onClose={() => setCreateEdgeOpen(false)}
        title="创建关系"
        size="md"
        footer={
          <>
            <Button variant="secondary" size="sm" onClick={() => setCreateEdgeOpen(false)}>
              取消
            </Button>
            <Button variant="primary" size="sm" onClick={handleCreateEdge} loading={createEdgeLoading}>
              创建
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">源节点 ID</label>
            <input
              type="text"
              value={edgeSourceId}
              onChange={(e) => setEdgeSourceId(e.target.value)}
              placeholder="输入源节点 ID"
              className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">目标节点 ID</label>
            <input
              type="text"
              value={edgeTargetId}
              onChange={(e) => setEdgeTargetId(e.target.value)}
              placeholder="输入目标节点 ID"
              className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] placeholder:text-[var(--color-text-tertiary)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">关系类型</label>
            <select
              value={edgeRelationType}
              onChange={(e) => setEdgeRelationType(e.target.value)}
              className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent"
            >
              {Object.entries(RELATION_TYPES).map(([category, types]) => (
                <optgroup
                  key={category}
                  label={category === 'user' ? '用户关系' : category === 'thing' ? '物品关系' : category === 'concept' ? '概念关系' : '事件关系'}
                >
                  {types.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        </div>
      </Modal>
    </div>
  );
}
