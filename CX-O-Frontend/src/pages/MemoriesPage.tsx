import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PageHeader } from '../components/layout';
import { Badge, Button, Card, CardBody } from '../components/ui';
import { AnimatedList } from '../components/AnimatedList';
// 阶段4b: graph Tab 改用 GraphVisualization（CX-O 独有的力导向图）替换 GraphManager
// 保留 GraphManager 文件本身，仅在 MemoriesPage 中不再使用
import {
  GraphVisualization,
  type GraphNode as VizGraphNode,
  type GraphLink as VizGraphLink,
} from '../components/GraphVisualization';
// 阶段4b: 迁移 CXHMS 独有组件 DistillationModal / CharacterCardModal
import { DistillationModal } from '../components/DistillationModal';
import { CharacterCardModal } from '../components/CharacterCardModal';
import { useHotkey } from '../hooks';
import { formatDate, truncate } from '../lib/utils';
import type { Memory, ViewMode } from './memories/types';
import { MemoryCard } from './memories/MemoryCard';
import { MemoryListItem } from './memories/MemoryListItem';
import { MemoriesToolbar } from './memories/MemoriesToolbar';
import { MemoryFormModal } from './memories/MemoryFormModal';
import { MemoryDetailDrawer } from './memories/MemoryDetailDrawer';
import { BatchTagModal } from './memories/BatchTagModal';

// Tab 类型：memories 记忆列表 / diary 日记视图 / acp ACP 消息 / graph 图谱
// 迁移自 CXHMS: MemoriesPage 4-Tab 结构
type MemoriesTab = 'memories' | 'diary' | 'acp' | 'graph';

export function MemoriesPage() {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<'all' | 'long_term' | 'short_term' | 'permanent'>(
    'all'
  );
  const [currentAgentId, setCurrentAgentId] = useState('default');
  const [viewMode, setViewMode] = useState<ViewMode>('card');
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [showDetailDrawer, setShowDetailDrawer] = useState(false);
  const [selectedMemory, setSelectedMemory] = useState<Memory | null>(null);
  const [selectedMemories, setSelectedMemories] = useState<Set<number>>(new Set());
  const [isBatchMode, setIsBatchMode] = useState(false);
  const [showBatchTagModal, setShowBatchTagModal] = useState(false);
  const [batchTags, setBatchTags] = useState('');
  const [batchTagOperation, setBatchTagOperation] = useState<'add' | 'remove' | 'set'>('add');
  // 迁移自 CXHMS: Tab 切换状态
  const [activeTab, setActiveTab] = useState<MemoriesTab>('memories');

  // 阶段4b: DistillationModal / CharacterCardModal 弹窗状态
  const [showDistillationModal, setShowDistillationModal] = useState(false);
  const [showCharacterCardModal, setShowCharacterCardModal] = useState(false);

  // 阶段4b: graph Tab 使用 GraphVisualization 所需的 nodes/links 数据
  const [graphNodes, setGraphNodes] = useState<VizGraphNode[]>([]);
  const [graphLinks, setGraphLinks] = useState<VizGraphLink[]>([]);

  useHotkey('Escape', () => {
    if (showDetailDrawer) setShowDetailDrawer(false);
    if (showAddModal) setShowAddModal(false);
    if (showEditModal) setShowEditModal(false);
  });

  const { data: agentTables } = useQuery({
    queryKey: ['agentMemoryTables'],
    queryFn: () => api.getAgentMemoryTables(),
    staleTime: 60000,
  });

  const {
    data: memories,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['memories', filterType, currentAgentId],
    queryFn: async () => {
      const result = await api.getMemories({
        type: filterType === 'all' ? undefined : filterType,
        limit: 100000,
        agent_id: currentAgentId,
      });
      return result;
    },
    refetchInterval: 5000,
  });

  // 日记数据查询（仅当 activeTab === 'diary' 时启用）
  // 迁移自 CXHMS: MemoriesPage diaryData useQuery
  const { data: diaryData, isLoading: isDiaryLoading } = useQuery({
    queryKey: ['diaryEntries', currentAgentId],
    queryFn: () => api.getDiaryEntries({ limit: 200, agent_id: currentAgentId }),
    enabled: activeTab === 'diary',
  });

  // ACP 消息历史（按当前选择的 agent 查询其收到的 ACP 消息）
  // 迁移自 CXHMS: MemoriesPage acpMessagesData useQuery
  const { data: acpMessagesData, isLoading: isAcpLoading } = useQuery({
    queryKey: ['acpMessages', currentAgentId],
    queryFn: () => api.getAcpMessages(currentAgentId, 200),
    enabled: activeTab === 'acp',
    staleTime: 30000,
  });

  // ACP 消息输入与发送
  const [acpInput, setAcpInput] = useState('');
  const sendAcpMessageMutation = useMutation({
    mutationFn: ({ toAgentId, message }: { toAgentId: string; message: string }) =>
      api.sendAcpMessage(toAgentId, message),
    onSuccess: () => {
      setAcpInput('');
      // 刷新消息历史；延迟 5s 再刷一次以拉取自动回复
      queryClient.invalidateQueries({ queryKey: ['acpMessages', currentAgentId] });
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['acpMessages', currentAgentId] });
      }, 5000);
    },
  });

  const handleSendAcpMessage = () => {
    const text = acpInput.trim();
    if (!text) return;
    sendAcpMessageMutation.mutate({ toAgentId: currentAgentId, message: text });
  };

  // 阶段4b: graph Tab 使用 GraphVisualization 时按需加载节点/边数据
  // 仅当 activeTab === 'graph' 时触发查询，避免不必要的网络请求
  useEffect(() => {
    if (activeTab !== 'graph') return;
    let cancelled = false;
    const loadGraphData = async () => {
      try {
        const [nodesResp, edgesResp] = await Promise.all([
          api.getNodes({ agent_id: currentAgentId, limit: 500 }),
          api.getEdges({ agent_id: currentAgentId, limit: 1000 }),
        ]);
        if (cancelled) return;
        // 转换 API GraphNode → GraphVisualization GraphNode
        const apiNodes = nodesResp.items || nodesResp.nodes || [];
        const vizNodes: VizGraphNode[] = apiNodes.map((n) => ({
          id: n.id,
          name:
            (n.properties?.name as string | undefined) ||
            n.text_content ||
            n.id,
          type: n.type,
          val: 1,
          data: n.properties,
        }));
        // 转换 API GraphEdge → GraphVisualization GraphLink
        const apiEdges = edgesResp.items || edgesResp.edges || [];
        const vizLinks: VizGraphLink[] = apiEdges.map((e) => ({
          source: e.source_id,
          target: e.target_id,
          type: e.relation_type,
          strength: 1,
        }));
        setGraphNodes(vizNodes);
        setGraphLinks(vizLinks);
      } catch (err) {
        console.error('加载图数据失败:', err);
        if (!cancelled) {
          setGraphNodes([]);
          setGraphLinks([]);
        }
      }
    };
    void loadGraphData();
    return () => {
      cancelled = true;
    };
  }, [activeTab, currentAgentId]);

  // ===== Mutations =====
  const batchDeleteMutation = useMutation({
    mutationFn: (ids: number[]) => api.batchDeleteMemories(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] });
      clearSelection();
    },
  });

  const batchArchiveMutation = useMutation({
    mutationFn: (ids: number[]) => api.batchArchiveMemories(ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] });
      clearSelection();
    },
  });

  const batchUpdateTagsMutation = useMutation({
    mutationFn: ({
      ids,
      tags,
      operation,
    }: {
      ids: number[];
      tags: string[];
      operation: 'add' | 'remove' | 'set';
    }) => api.batchUpdateTags(ids, tags, operation),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memories'] });
      setShowBatchTagModal(false);
      setBatchTags('');
      clearSelection();
    },
  });

  // ===== Handlers =====
  const handleAddSave = async (data: { content: string; type: string; importance: number; tags: string[] }) => {
    try {
      await api.createMemory({
        content: data.content,
        type: data.type,
        importance: data.importance,
        tags: data.tags,
        agent_id: currentAgentId,
      });
      setShowAddModal(false);
      refetch();
    } catch (error) {
      console.error('创建记忆失败:', error);
    }
  };

  const handleEditSave = async (data: { content: string; type: string; importance: number; tags: string[] }) => {
    if (!selectedMemory) return;
    try {
      await api.updateMemory(selectedMemory.id, {
        content: data.content,
        tags: data.tags,
        importance: data.importance,
      });
      setShowEditModal(false);
      setSelectedMemory(null);
      refetch();
    } catch (error) {
      console.error('更新记忆失败:', error);
    }
  };

  const handleDeleteMemory = async (id: number) => {
    if (!confirm('确定要删除这条记忆吗？')) return;
    try {
      await api.deleteMemory(id);
      refetch();
    } catch (error) {
      console.error('删除记忆失败:', error);
    }
  };

  const handleArchiveMemory = async (id: number) => {
    try {
      await api.archiveMemory(id);
      refetch();
    } catch (error) {
      console.error('归档记忆失败:', error);
    }
  };

  const handleEditMemory = (memory: Memory) => {
    setShowDetailDrawer(false);
    setSelectedMemory(memory);
    setShowEditModal(true);
  };

  const handleViewMemory = (memory: Memory) => {
    setSelectedMemory(memory);
    setShowDetailDrawer(true);
  };

  const toggleMemorySelection = (id: number) => {
    const newSelected = new Set(selectedMemories);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedMemories(newSelected);
  };

  const selectAllMemories = () => {
    if (selectedMemories.size === filteredMemories.length) {
      setSelectedMemories(new Set());
    } else {
      setSelectedMemories(new Set(filteredMemories.map((m: Memory) => m.id)));
    }
  };

  const clearSelection = () => {
    setSelectedMemories(new Set());
    setIsBatchMode(false);
  };

  const handleBatchDelete = () => {
    if (selectedMemories.size === 0) return;
    if (!confirm(`确定要删除选中的 ${selectedMemories.size} 条记忆吗？`)) return;
    batchDeleteMutation.mutate(Array.from(selectedMemories));
  };

  const handleBatchArchive = () => {
    if (selectedMemories.size === 0) return;
    batchArchiveMutation.mutate(Array.from(selectedMemories));
  };

  const handleBatchUpdateTags = () => {
    if (selectedMemories.size === 0) return;
    const tags = batchTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    if (tags.length === 0) return;
    batchUpdateTagsMutation.mutate({
      ids: Array.from(selectedMemories),
      tags,
      operation: batchTagOperation,
    });
  };

  const filteredMemories =
    memories?.memories?.filter((memory: Memory) => {
      if (!searchQuery) return true;
      return (
        memory.content.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (memory.tags &&
          memory.tags.some((tag) => tag.toLowerCase().includes(searchQuery.toLowerCase())))
      );
    }) || [];

  return (
    <div className="max-w-6xl mx-auto">
      <PageHeader
        title="记忆管理"
        description="管理和浏览系统存储的记忆"
        actions={
          <div className="flex items-center gap-2">
            {/* 阶段4b: 迁移自 CXHMS 独有功能 —— RADIX-Lite 蒸馏入口 */}
            <Button variant="secondary" onClick={() => setShowDistillationModal(true)}>
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
              蒸馏
            </Button>
            {/* 阶段4b: 迁移自 CXHMS 独有功能 —— 角色卡 Agent 创建入口 */}
            <Button variant="secondary" onClick={() => setShowCharacterCardModal(true)}>
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                />
              </svg>
              角色卡
            </Button>
            {activeTab === 'memories' ? (
              <Button onClick={() => setShowAddModal(true)}>
                <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 4v16m8-8H4"
                  />
                </svg>
                新建记忆
              </Button>
            ) : null}
          </div>
        }
      />

      {/* Tab 切换：memories / diary / acp / graph
          迁移自 CXHMS: MemoriesPage 4-Tab 结构，仅启用 memories 和 diary，acp/graph 后续阶段迁移 */}
      <div className="flex items-center gap-2 mb-4 border-b border-[var(--color-border)]">
        {([
          { key: 'memories', label: '记忆' },
          { key: 'diary', label: '日记' },
          { key: 'acp', label: 'ACP' },
          { key: 'graph', label: '图谱' },
        ] as const).map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm transition-colors border-b-2 -mb-px ${
              activeTab === tab.key
                ? 'border-[var(--color-accent)] text-[var(--color-text-primary)] font-medium'
                : 'border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'memories' && (
        <MemoriesToolbar
          searchQuery={searchQuery}
          filterType={filterType}
          currentAgentId={currentAgentId}
          viewMode={viewMode}
          isBatchMode={isBatchMode}
          agents={agentTables?.agents || []}
          onSearchChange={setSearchQuery}
          onFilterTypeChange={setFilterType}
          onAgentChange={(value) => {
            setCurrentAgentId(value);
            clearSelection();
          }}
          onViewModeChange={setViewMode}
          onBatchModeToggle={() => {
            setIsBatchMode(!isBatchMode);
            if (isBatchMode) clearSelection();
          }}
        />
      )}

      {activeTab === 'diary' && (
        <div className="flex items-center justify-end mb-4">
          <label className="text-sm text-[var(--color-text-secondary)] mr-2">Agent:</label>
          <select
            value={currentAgentId}
            onChange={(e) => setCurrentAgentId(e.target.value)}
            className="px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm"
          >
            <option value="default">默认 Agent</option>
            {agentTables?.agents
              ?.filter((a) => a.agent_id !== 'default')
              .map((agent) => (
                <option key={agent.agent_id} value={agent.agent_id}>
                  {agent.agent_id}
                </option>
              ))}
          </select>
        </div>
      )}

      {activeTab === 'memories' && isBatchMode && (
        <Card className="mb-4 p-3 bg-[var(--color-accent-light)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button variant="ghost" size="sm" onClick={selectAllMemories}>
                {selectedMemories.size === filteredMemories.length ? '取消全选' : '全选'}
                <span className="ml-2 text-[var(--color-text-secondary)]">
                  ({selectedMemories.size}/{filteredMemories.length})
                </span>
              </Button>
            </div>
            <div className="flex items-center gap-2">
              {selectedMemories.size > 0 && (
                <>
                  <Button variant="secondary" size="sm" onClick={() => setShowBatchTagModal(true)}>
                    标签
                  </Button>
                  <Button variant="secondary" size="sm" onClick={handleBatchArchive}>
                    归档
                  </Button>
                  <Button variant="danger" size="sm" onClick={handleBatchDelete}>
                    删除
                  </Button>
                </>
              )}
            </div>
          </div>
        </Card>
      )}

      {activeTab === 'memories' &&
        (isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="animate-spin w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full" />
          </div>
        ) : filteredMemories.length === 0 ? (
          <Card className="py-12 text-center">
            <div className="text-[var(--color-text-tertiary)]">
              <svg
                className="w-16 h-16 mx-auto mb-4 opacity-50"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
                />
              </svg>
              <h3 className="text-lg font-medium mb-2">暂无记忆</h3>
              <p className="text-sm">点击"新建记忆"按钮添加您的第一条记忆</p>
            </div>
          </Card>
        ) : viewMode === 'card' ? (
          <AnimatedList className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredMemories.map((memory: Memory) => (
              <MemoryCard
                key={memory.id}
                memory={memory}
                isBatchMode={isBatchMode}
                isSelected={selectedMemories.has(memory.id)}
                onView={handleViewMemory}
                onEdit={handleEditMemory}
                onDelete={handleDeleteMemory}
                onArchive={handleArchiveMemory}
                onToggleSelect={toggleMemorySelection}
              />
            ))}
          </AnimatedList>
        ) : (
          <Card>
            <CardBody className="p-0">
              <table className="w-full">
                <thead className="bg-[var(--color-bg-tertiary)]">
                  <tr>
                    {isBatchMode && (
                      <th className="w-10 px-4 py-3 text-left">
                        <input
                          type="checkbox"
                          checked={selectedMemories.size === filteredMemories.length}
                          onChange={selectAllMemories}
                          className="rounded"
                        />
                      </th>
                    )}
                    <th className="px-4 py-3 text-left text-sm font-medium text-[var(--color-text-secondary)]">
                      内容
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-[var(--color-text-secondary)] w-24">
                      类型
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-[var(--color-text-secondary)] w-24">
                      重要性
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-[var(--color-text-secondary)] w-32">
                      标签
                    </th>
                    <th className="px-4 py-3 text-left text-sm font-medium text-[var(--color-text-secondary)] w-32">
                      创建时间
                    </th>
                    <th className="px-4 py-3 text-right text-sm font-medium text-[var(--color-text-secondary)] w-32">
                      操作
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {filteredMemories.map((memory: Memory) => (
                    <MemoryListItem
                      key={memory.id}
                      memory={memory}
                      isBatchMode={isBatchMode}
                      isSelected={selectedMemories.has(memory.id)}
                      onView={handleViewMemory}
                      onEdit={handleEditMemory}
                      onDelete={handleDeleteMemory}
                      onToggleSelect={toggleMemorySelection}
                    />
                  ))}
                </tbody>
              </table>
            </CardBody>
          </Card>
        ))}

      {/* 日记视图 Tab
          迁移自 CXHMS: MemoriesPage DiaryView 组件，时间线展开/折叠 */}
      {activeTab === 'diary' && (
        <DiaryView diaryData={diaryData} isLoading={isDiaryLoading} />
      )}

      {/* ACP 消息视图 Tab
          迁移自 CXHMS: MemoriesPage ACP 实现（agent selector + 消息列表 + 发送区） */}
      {activeTab === 'acp' && (
        <>
          <div className="flex items-center justify-end mb-4">
            <label className="text-sm text-[var(--color-text-secondary)] mr-2">Agent:</label>
            <select
              value={currentAgentId}
              onChange={(e) => setCurrentAgentId(e.target.value)}
              className="px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm"
            >
              <option value="default">默认 Agent</option>
              {agentTables?.agents
                ?.filter((a) => a.agent_id !== 'default')
                .map((agent) => (
                  <option key={agent.agent_id} value={agent.agent_id}>
                    {agent.agent_id}
                  </option>
                ))}
            </select>
          </div>

          {isAcpLoading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full" />
            </div>
          ) : acpMessagesData?.messages && acpMessagesData.messages.length > 0 ? (
            <div className="space-y-3">
              {acpMessagesData.messages
                .slice()
                .reverse()
                .map((msg) => {
                  const isFromCurrent = msg.from_agent_id === currentAgentId;
                  const contentText =
                    typeof msg.content === 'string'
                      ? msg.content
                      : (msg.content?.text as string) ||
                        (msg.content?.message as string) ||
                        JSON.stringify(msg.content);
                  return (
                    <div
                      key={msg.id}
                      className={`flex ${isFromCurrent ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-[75%] rounded-[var(--radius-md)] px-4 py-3 ${
                          isFromCurrent
                            ? 'bg-[var(--color-accent)] text-white'
                            : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-primary)]'
                        }`}
                      >
                        <div className="text-xs opacity-70 mb-1">
                          {isFromCurrent
                            ? `发送至 ${msg.to_agent_id || ''}`
                            : `来自 ${msg.from_agent_name || msg.from_agent_id}`}
                          <span className="ml-2">{formatDate(msg.timestamp)}</span>
                          {msg.is_sent && (
                            <span className="ml-2 px-1.5 py-0.5 text-[10px] bg-black/10 rounded">
                              已发送
                            </span>
                          )}
                        </div>
                        <div className="whitespace-pre-wrap break-words">{contentText}</div>
                      </div>
                    </div>
                  );
                })}
            </div>
          ) : (
            <Card className="py-12 text-center">
              <div className="text-[var(--color-text-tertiary)]">
                <h3 className="text-lg font-medium mb-2">暂无 ACP 消息</h3>
                <p className="text-sm">通过下方输入框向该 Agent 发送消息以开始对话</p>
              </div>
            </Card>
          )}

          {/* ACP 消息发送区：无论有无消息历史都显示，便于主动发起对话 */}
          <div className="mt-6 pt-4 border-t border-[var(--color-border)]">
            <div className="flex items-center gap-2">
              <input
                value={acpInput}
                onChange={(e) => setAcpInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendAcpMessage();
                  }
                }}
                placeholder={
                  currentAgentId === 'default'
                    ? '请先选择目标 Agent'
                    : `向 ${currentAgentId} 发送 ACP 消息...`
                }
                disabled={sendAcpMessageMutation.isPending || currentAgentId === 'default'}
                className="flex-1 px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm focus:outline-none focus:border-[var(--color-accent)] disabled:opacity-50"
              />
              <Button
                onClick={handleSendAcpMessage}
                disabled={
                  sendAcpMessageMutation.isPending ||
                  !acpInput.trim() ||
                  currentAgentId === 'default'
                }
              >
                {sendAcpMessageMutation.isPending ? '发送中...' : '发送'}
              </Button>
            </div>
            {sendAcpMessageMutation.isError && (
              <div className="mt-2 text-xs text-[var(--color-error)]">发送失败，请重试</div>
            )}
            {currentAgentId === 'default' && (
              <div className="mt-2 text-xs text-[var(--color-text-secondary)]">
                请先在上方选择目标 Agent（不能为 default）
              </div>
            )}
          </div>
        </>
      )}

      {/* 图谱视图 Tab：阶段4b 改用 CX-O 独有的 GraphVisualization（纯力导向图）
          替换原 GraphManager（含节点列表/语义搜索等复杂功能）。
          数据来源：api.getNodes() + api.getEdges()，在 useEffect 中按 currentAgentId 加载 */}
      {activeTab === 'graph' && (
        <div className="flex flex-col h-[600px] border border-[var(--color-border)] rounded-lg bg-[var(--color-bg-secondary)] overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] bg-[var(--color-bg-tertiary)]">
            <div className="text-sm font-medium">知识图谱可视化</div>
            <div className="text-xs text-[var(--color-text-secondary)]">
              {graphNodes.length} 节点 · {graphLinks.length} 关系
              {currentAgentId !== 'default' && ` · agent: ${currentAgentId}`}
            </div>
          </div>
          <div className="flex-1 overflow-hidden">
            {graphNodes.length === 0 ? (
              <div className="flex items-center justify-center h-full text-sm text-[var(--color-text-secondary)]">
                暂无图数据
              </div>
            ) : (
              <GraphVisualization nodes={graphNodes} links={graphLinks} height={560} />
            )}
          </div>
        </div>
      )}

      {showAddModal && (
        <MemoryFormModal
          memory={null}
          onClose={() => setShowAddModal(false)}
          onSave={handleAddSave}
        />
      )}

      {showEditModal && selectedMemory && (
        <MemoryFormModal
          key={selectedMemory.id}
          memory={selectedMemory}
          onClose={() => {
            setShowEditModal(false);
            setSelectedMemory(null);
          }}
          onSave={handleEditSave}
        />
      )}

      {showDetailDrawer && selectedMemory && (
        <MemoryDetailDrawer
          memory={selectedMemory}
          onClose={() => {
            setShowDetailDrawer(false);
            setSelectedMemory(null);
          }}
          onEdit={handleEditMemory}
          onArchive={handleArchiveMemory}
          onDelete={handleDeleteMemory}
        />
      )}

      {showBatchTagModal && (
        <BatchTagModal
          selectedCount={selectedMemories.size}
          operation={batchTagOperation}
          tags={batchTags}
          onOperationChange={setBatchTagOperation}
          onTagsChange={setBatchTags}
          onConfirm={handleBatchUpdateTags}
          onClose={() => setShowBatchTagModal(false)}
        />
      )}

      {/* 阶段4b: 迁移自 CXHMS 独有组件 —— RADIX-Lite 蒸馏弹窗 */}
      <DistillationModal
        isOpen={showDistillationModal}
        onClose={() => setShowDistillationModal(false)}
      />

      {/* 阶段4b: 迁移自 CXHMS 独有组件 —— 角色卡 Agent 创建弹窗 */}
      <CharacterCardModal
        isOpen={showCharacterCardModal}
        onClose={() => setShowCharacterCardModal(false)}
      />
    </div>
  );
}

// ========== 日记视图组件 ==========
// 迁移自 CXHMS: MemoriesPage DiaryView（时间线展开/折叠）
// 保持 CX-O 风格：不使用 i18n，直接中文

interface DiaryEntry {
  id: number;
  content: string;
  metadata?: {
    date?: string;
    title?: string;
    mood?: string;
    body?: string;
    summarized_message_range?: string;
    source?: string;
  };
  created_at: string;
}

interface DiaryGroup {
  date: string;
  entries: DiaryEntry[];
}

interface DiaryViewProps {
  diaryData?: { diary_groups?: DiaryGroup[]; count?: number };
  isLoading: boolean;
}

interface TimelineEntry extends DiaryEntry {
  groupDate: string;
}

function DiaryView({ diaryData, isLoading }: DiaryViewProps) {
  const [expandedEntryIds, setExpandedEntryIds] = useState<Set<number>>(new Set());

  const groups = diaryData?.diary_groups || [];

  // 将日期分组的条目展平为单一列表，按 created_at 降序排序
  // API 已按日期降序返回分组，此处防御性重排
  const allEntries: TimelineEntry[] = groups
    .flatMap((group) => group.entries.map((entry) => ({ ...entry, groupDate: group.date })))
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  const toggleEntry = (id: number) => {
    setExpandedEntryIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="animate-spin w-8 h-8 border-2 border-[var(--color-accent)] border-t-transparent rounded-full" />
      </div>
    );
  }

  if (allEntries.length === 0) {
    return (
      <Card className="py-12 text-center">
        <div className="text-[var(--color-text-tertiary)]">
          <svg
            className="w-16 h-16 mx-auto mb-4 opacity-50"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"
            />
          </svg>
          <h3 className="text-lg font-medium mb-2">暂无日记</h3>
          <p className="text-sm">通过 summary-agent 或 save_diary_entry 工具生成日记</p>
        </div>
      </Card>
    );
  }

  return (
    <div className="relative pl-8">
      {/* 时间线垂直连接线 */}
      <div className="absolute left-[7px] top-3 bottom-3 w-px bg-[var(--color-border)]" />

      <div className="space-y-4">
        {allEntries.map((entry) => {
          const meta = entry.metadata || {};
          const isExpanded = expandedEntryIds.has(entry.id);
          const hasExpandableDetail = Boolean(meta.body || meta.summarized_message_range);
          const previewBody = meta.body ?? entry.content;

          return (
            <div key={entry.id} className="relative">
              {/* 时间线节点圆点 */}
              <div
                className={`absolute -left-[1.95rem] top-4 w-3.5 h-3.5 rounded-full ring-4 ring-[var(--color-bg-primary)] transition-colors ${
                  isExpanded
                    ? 'bg-[var(--color-accent)]'
                    : 'bg-[var(--color-text-tertiary)]'
                }`}
              />

              <Card
                className={`transition-all hover:shadow-lg ${
                  hasExpandableDetail ? 'cursor-pointer' : ''
                } ${isExpanded ? 'ring-1 ring-[var(--color-accent)]' : ''}`}
                onClick={() => hasExpandableDetail && toggleEntry(entry.id)}
              >
                <CardBody>
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className="text-xs font-medium text-[var(--color-text-secondary)]">
                      {entry.groupDate}
                    </span>
                    {meta.mood && (
                      <Badge variant="primary" size="sm">
                        {meta.mood}
                      </Badge>
                    )}
                    {meta.source && (
                      <span className="text-xs text-[var(--color-text-tertiary)]">
                        · {meta.source}
                      </span>
                    )}
                    {hasExpandableDetail && (
                      <svg
                        className={`w-4 h-4 ml-auto text-[var(--color-text-secondary)] transition-transform ${
                          isExpanded ? 'rotate-180' : ''
                        }`}
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M19 9l-7 7-7-7"
                        />
                      </svg>
                    )}
                  </div>

                  {meta.title && (
                    <h4 className="text-base font-semibold text-[var(--color-text-primary)] mb-1.5">
                      {meta.title}
                    </h4>
                  )}

                  <p className="text-sm text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap">
                    {isExpanded ? previewBody : truncate(previewBody, 120)}
                  </p>

                  {isExpanded && (
                    <div className="mt-3 pt-3 border-t border-[var(--color-border)] space-y-2">
                      {meta.summarized_message_range && (
                        <div className="flex items-center gap-2 text-xs text-[var(--color-text-tertiary)]">
                          <span className="font-medium">消息范围</span>
                          <span>{meta.summarized_message_range}</span>
                        </div>
                      )}
                      <div className="flex items-center gap-2 text-xs text-[var(--color-text-tertiary)]">
                        <svg
                          className="w-3.5 h-3.5"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                          />
                        </svg>
                        <span className="font-medium">完整时间</span>
                        <span>{formatDate(entry.created_at)}</span>
                      </div>
                    </div>
                  )}
                </CardBody>
              </Card>
            </div>
          );
        })}
      </div>
    </div>
  );
}
