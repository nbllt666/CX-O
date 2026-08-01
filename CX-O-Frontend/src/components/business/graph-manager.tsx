/**
 * @file graph-manager.tsx — GraphManager 业务组件重组（模块7）
 * ============================================================================
 * 模块: 模块7 业务组件重组层 — A 组图管理类
 * 落点: C:\CX-O\CX-O-Frontend\src\components\business\graph-manager.tsx
 * 原组件: src/components/GraphManager.tsx
 *
 * 重组策略（MODULE-7 AGENTS.md §2.4）:
 *   - 保留现有业务逻辑（全部 state / effect / handler / 数据加载 / 计算逻辑不变）
 *   - UI 层换用模块6 ui-v2 基础组件:
 *     · Button → ui-v2 Button
 *     · Card → ui-v2 Card
 *     · Modal → ui-v2 Dialog（API 适配: isOpen→open, onClose→onOpenChange）
 *     · Badge → ui-v2 Badge（variant 映射: info→secondary, 其余直接映射）
 *     · <input> → ui-v2 Input / <textarea> → ui-v2 Textarea
 *     · EmptyState/EmptyStateIcon → 本地内联（基于 ui-v2 Card）
 *   - 注入 Liquid Glass + data-glass + motion variants
 *   - 通过 className 消费 token，不硬编码颜色
 *
 * 跨模块导入约束（rules-0 §四 + MODULE-7 AGENTS.md §2.3）:
 *   - 仅 import 模块6 ui-v2 公开产出
 *   - 仅 import 共享基础设施（@/api/client / @/lib/utils）
 *   - 仅 import 本模块内部实现（./graph-visualization）
 *   - 禁止 import 模块8/9 内部实现
 *   - 禁止 import 旧 @/components/ 下组件
 * ============================================================================
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
import { motion, type Variants } from 'framer-motion';
import { cn } from '@/lib/utils';
import { api } from '@/api/client';
import {
  Button,
  Card,
  Dialog,
  Badge,
  Input,
  Textarea,
  type BadgeVariant,
  buildGlassDataAttributes,
  getComponentMotionVariants,
} from '@/components/ui-v2';
import { formatRelativeTime, truncate } from '@/lib/utils';
import { GraphVisualization } from './graph-visualization';
import type { GraphNode as VisGraphNode, GraphLink as VisGraphLink } from './graph-visualization';

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

// ui-v2 BadgeVariant 映射（原 info → secondary，其余直接映射）
const TYPE_COLOR_MAP: Record<string, BadgeVariant> = {
  user: 'secondary',
  thing: 'success',
  concept: 'warning',
  event: 'error',
  default: 'default',
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

// ========== 入场 motion variants（基于模块6 工厂）==========

const managerVariants: Variants = getComponentMotionVariants({
  componentName: 'Card',
  springKey: 'glass',
});

// ========== 本地 EmptyState（基于 ui-v2 Card 重组，替换旧 ui/EmptyState）==========

const EmptyStateIcon: React.FC<{ type: 'search' | 'folder' | 'chat' | 'user' }> = ({ type }) => {
  const icons = {
    search: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    ),
    folder: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
    ),
    chat: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    ),
    user: (
      <svg className="w-16 h-16" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
      </svg>
    ),
  };
  return icons[type];
};

const EmptyState: React.FC<{
  icon?: React.ReactNode;
  title: string;
  description?: string;
}> = ({ icon, title, description }) => (
  <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
    {icon && <div className="mb-4 text-[var(--color-text-tertiary)]">{icon}</div>}
    <h3 className="text-lg font-medium text-[var(--color-text-primary)] mb-2">{title}</h3>
    {description && <p className="text-sm text-[var(--color-text-secondary)] mb-4 max-w-sm">{description}</p>}
  </div>
);

// ========== 子组件 ==========

const StatCard: React.FC<{
  title: string;
  value: number | string;
  icon: React.ReactNode;
  color: string;
}> = ({ title, value, icon, color }) => (
  <Card className="p-4" dataGlass glassTier={3}>
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
  void color;
  const colorVar = category === 'user' ? 'info' : category === 'thing' ? 'success' : category === 'concept' ? 'warning' : 'error';
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-[var(--radius-md)] bg-[var(--color-bg-tertiary)]">
      <div
        className="w-8 h-8 rounded-[var(--radius-sm)] flex items-center justify-center"
        style={{ backgroundColor: `var(--color-${colorVar}-light)` }}
      >
        <span style={{ color: `var(--color-${colorVar})` }}>{icon}</span>
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

  // 可视化数据
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

  const glassAttributes = buildGlassDataAttributes(true, 3);

  return (
    <motion.div
      className="flex flex-col h-full"
      variants={managerVariants}
      initial="initial"
      animate="animate"
      exit="exit"
      {...glassAttributes}
    >
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
            className="px-2 py-1 text-sm rounded-[var(--radius-sm)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)]"
            data-glass="true"
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
              <Card className="p-4" dataGlass glassTier={3}>
                <div className="h-12 animate-pulse bg-[var(--color-bg-tertiary)] rounded" />
              </Card>
              <Card className="p-4" dataGlass glassTier={3}>
                <div className="h-12 animate-pulse bg-[var(--color-bg-tertiary)] rounded" />
              </Card>
              <Card className="p-4" dataGlass glassTier={3}>
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

      {/* ========== 搜索栏 ========== */}
      {activeTab !== 'visualization' && (
        <div className="px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]">
          <div className="flex gap-2">
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSemanticSearch()}
              placeholder="语义搜索节点..."
              icon={<Search className="w-4 h-4" />}
              className="flex-1"
            />
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
        <div className="flex-1 flex flex-col min-w-0">
          {/* 标签页 */}
          <div className="flex border-b border-[var(--color-border)] bg-[var(--color-bg-primary)]">
            {GRAPH_TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => handleTabChange(tab.key)}
                className={cn(
                  'px-4 py-2 text-sm font-medium border-b-2 flex items-center gap-1',
                  activeTab === tab.key
                    ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                    : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)] hover:border-[var(--color-border)]',
                )}
              >
                {tab.key === 'visualization' && <Network className="w-3.5 h-3.5" />}
                {tab.label}
              </button>
            ))}
          </div>

          {/* 内容区 */}
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
                          className={cn(
                            'px-4 py-3 cursor-pointer hover:bg-[var(--color-bg-hover)]',
                            selectedNode?.id === result.node_id ? 'bg-[var(--color-accent-light)]' : '',
                          )}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 min-w-0">
                              <Badge variant={TYPE_COLOR_MAP[cat]} size="sm">
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
                                className="p-1 text-[var(--color-text-tertiary)] hover:text-[var(--color-error)]"
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
                        className={cn(
                          'px-4 py-3 cursor-pointer hover:bg-[var(--color-bg-hover)]',
                          selectedNode?.id === node.id ? 'bg-[var(--color-accent-light)]' : '',
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 min-w-0">
                            <Badge variant={TYPE_COLOR_MAP[cat]} size="sm">
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
                              className="p-1 text-[var(--color-text-tertiary)] hover:text-[var(--color-error)]"
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

        {/* 右侧：节点详情面板 */}
        {detailExpanded && selectedNode && activeTab !== 'visualization' && (
          <div className="w-80 border-l border-[var(--color-border)] bg-[var(--color-bg-secondary)] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
              <h3 className="text-sm font-semibold text-[var(--color-text-primary)]">节点详情</h3>
              <button
                onClick={() => {
                  setDetailExpanded(false);
                  setSelectedNode(null);
                  setNeighbors([]);
                }}
                className="p-1 text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant={TYPE_COLOR_MAP[getGraphCategory(selectedNode.type)]} size="sm">
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

              {selectedNode.text_content && (
                <div>
                  <h4 className="text-xs font-medium text-[var(--color-text-tertiary)] mb-1">文本内容</h4>
                  <div className="text-sm text-[var(--color-text-primary)] bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] p-3 whitespace-pre-wrap max-h-40 overflow-y-auto">
                    {selectedNode.text_content}
                  </div>
                </div>
              )}

              {selectedNode.properties && Object.keys(selectedNode.properties).length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-[var(--color-text-tertiary)] mb-1">属性</h4>
                  <pre className="text-xs text-[var(--color-text-primary)] bg-[var(--color-bg-tertiary)] rounded-[var(--radius-md)] p-3 overflow-x-auto max-h-40 overflow-y-auto">
                    {JSON.stringify(selectedNode.properties, null, 2)}
                  </pre>
                </div>
              )}

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
                            <Badge variant={TYPE_COLOR_MAP[cat]} size="sm">
                              {neighborNode.type}
                            </Badge>
                            <span className="text-xs font-medium text-[var(--color-text-primary)] truncate">
                              {(neighborNode.properties?.name as string) || neighborNode.id}
                            </span>
                          </div>
                          {edge && (
                            <div className="mt-1 flex items-center gap-1 text-[10px] text-[var(--color-text-tertiary)]">
                              <span className="px-1 py-0.5 rounded bg-[var(--color-accent-light)] text-[var(--color-accent)]">
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

              <Button variant="danger" size="sm" className="w-full" icon={<Trash2 className="w-4 h-4" />} onClick={() => handleDeleteNode(selectedNode.id)}>
                删除此节点
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* ========== 创建节点对话框（Modal → Dialog 适配）========== */}
      <Dialog
        open={createNodeOpen}
        onOpenChange={setCreateNodeOpen}
        title="创建节点"
        size="md"
        dataGlass
        glassTier={3}
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
              data-glass="true"
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
            <Textarea
              value={newNodeText}
              onChange={(e) => setNewNodeText(e.target.value)}
              placeholder="输入节点的文本内容..."
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">属性 (JSON)</label>
            <Textarea
              value={newNodeProps}
              onChange={(e) => setNewNodeProps(e.target.value)}
              placeholder='{"name": "示例", "key": "value"}'
              className="font-mono min-h-[80px]"
            />
          </div>
        </div>
      </Dialog>

      {/* ========== 创建关系对话框（Modal → Dialog 适配）========== */}
      <Dialog
        open={createEdgeOpen}
        onOpenChange={setCreateEdgeOpen}
        title="创建关系"
        size="md"
        dataGlass
        glassTier={3}
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
            <Input
              value={edgeSourceId}
              onChange={(e) => setEdgeSourceId(e.target.value)}
              placeholder="输入源节点 ID"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">目标节点 ID</label>
            <Input
              value={edgeTargetId}
              onChange={(e) => setEdgeTargetId(e.target.value)}
              placeholder="输入目标节点 ID"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">关系类型</label>
            <select
              value={edgeRelationType}
              onChange={(e) => setEdgeRelationType(e.target.value)}
              className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent"
              data-glass="true"
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
      </Dialog>
    </motion.div>
  );
}
