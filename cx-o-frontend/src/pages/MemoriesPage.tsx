import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { formatDate, truncate, getImportanceColor, getImportanceLabel } from '../lib/utils';
import { PageHeader } from '../components/layout';
import { Button, Card, CardBody, Input, Badge, Modal, Textarea, Drawer } from '../components/ui';
import { useHotkey } from '../hooks';

interface Memory {
  id: number;
  content: string;
  type: string;
  importance: number;
  tags: string[];
  created_at: string;
  is_archived: boolean;
  emotion_score?: number;
}

type ViewMode = 'card' | 'list';

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
  const [editingMemory, setEditingMemory] = useState<Memory | null>(null);
  const [newMemory, setNewMemory] = useState({
    content: '',
    type: 'long_term',
    importance: 3,
    tags: '',
  });

  const [selectedMemories, setSelectedMemories] = useState<Set<number>>(new Set());
  const [isBatchMode, setIsBatchMode] = useState(false);
  const [showBatchTagModal, setShowBatchTagModal] = useState(false);
  const [batchTags, setBatchTags] = useState('');
  const [batchTagOperation, setBatchTagOperation] = useState<'add' | 'remove' | 'set'>('add');

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
        limit: 1000,
        agent_id: currentAgentId,
      });
      return result;
    },
    refetchInterval: 5000,
  });

  const handleCreateMemory = async () => {
    try {
      await api.createMemory({
        content: newMemory.content,
        type: newMemory.type,
        importance: newMemory.importance,
        tags: newMemory.tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        agent_id: currentAgentId,
      });
      setShowAddModal(false);
      setNewMemory({ content: '', type: 'long_term', importance: 3, tags: '' });
      refetch();
    } catch (error) {
      console.error('创建记忆失败:', error);
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
    setEditingMemory(memory);
    setShowEditModal(true);
  };

  const handleViewMemory = (memory: Memory) => {
    setSelectedMemory(memory);
    setShowDetailDrawer(true);
  };

  const handleUpdateMemory = async () => {
    if (!editingMemory) return;
    try {
      await api.updateMemory(editingMemory.id, {
        content: editingMemory.content,
        tags: editingMemory.tags,
        importance: editingMemory.importance,
      });
      setShowEditModal(false);
      setEditingMemory(null);
      refetch();
    } catch (error) {
      console.error('更新记忆失败:', error);
    }
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

  const typeLabels: Record<string, string> = {
    permanent: '永久',
    long_term: '长期',
    short_term: '短期',
  };

  return (
    <div className="max-w-6xl mx-auto">
      <PageHeader
        title="记忆管理"
        description="管理和浏览系统存储的记忆"
        actions={
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
        }
      />

      <div className="flex items-center gap-4 mb-6">
        <div className="flex-1">
          <Input
            placeholder="搜索记忆内容或标签..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full"
          />
        </div>

        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as typeof filterType)}
          className="px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm"
        >
          <option value="all">全部类型</option>
          <option value="permanent">永久记忆</option>
          <option value="long_term">长期记忆</option>
          <option value="short_term">短期记忆</option>
        </select>

        <select
          value={currentAgentId}
          onChange={(e) => {
            setCurrentAgentId(e.target.value);
            clearSelection();
          }}
          className="px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)] text-sm"
        >
          <option value="default">默认Agent</option>
          {agentTables?.agents
            ?.filter((a: { agent_id: string }) => a.agent_id !== 'default')
            .map((agent: { agent_id: string }) => (
              <option key={agent.agent_id} value={agent.agent_id}>
                {agent.agent_id}
              </option>
            ))}
        </select>

        <div className="flex items-center border border-[var(--color-border)] rounded-[var(--radius-md)] overflow-hidden">
          <button
            onClick={() => setViewMode('card')}
            className={`px-3 py-2 text-sm ${viewMode === 'card' ? 'bg-[var(--color-accent)] text-white' : 'bg-[var(--color-bg-primary)]'}`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
              />
            </svg>
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`px-3 py-2 text-sm ${viewMode === 'list' ? 'bg-[var(--color-accent)] text-white' : 'bg-[var(--color-bg-primary)]'}`}
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 10h16M4 14h16M4 18h16"
              />
            </svg>
          </button>
        </div>

        <Button
          variant={isBatchMode ? 'primary' : 'secondary'}
          onClick={() => {
            setIsBatchMode(!isBatchMode);
            if (isBatchMode) clearSelection();
          }}
        >
          {isBatchMode ? '退出批量' : '批量操作'}
        </Button>
      </div>

      {isBatchMode && (
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

      {isLoading ? (
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
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredMemories.map((memory: Memory) => (
            <Card
              key={memory.id}
              className={`cursor-pointer transition-all hover:shadow-lg ${
                memory.is_archived ? 'opacity-60' : ''
              } ${isBatchMode && selectedMemories.has(memory.id) ? 'ring-2 ring-[var(--color-accent)]' : ''}`}
              onClick={() => {
                if (isBatchMode) {
                  toggleMemorySelection(memory.id);
                } else {
                  handleViewMemory(memory);
                }
              }}
            >
              <CardBody>
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{
                        backgroundColor: `var(--color-${getImportanceColor(memory.importance).replace('bg-', '')})`,
                      }}
                    />
                    <span className="text-xs text-[var(--color-text-secondary)]">
                      {getImportanceLabel(memory.importance)}
                    </span>
                    <Badge variant="secondary" size="sm">
                      {typeLabels[memory.type] || memory.type}
                    </Badge>
                  </div>
                  {!isBatchMode && (
                    <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => handleArchiveMemory(memory.id)}
                        className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-colors"
                        title="归档"
                      >
                        <svg
                          className="w-4 h-4 text-[var(--color-text-secondary)]"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"
                          />
                        </svg>
                      </button>
                      <button
                        onClick={() => handleEditMemory(memory)}
                        className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)] transition-colors"
                        title="编辑"
                      >
                        <svg
                          className="w-4 h-4 text-[var(--color-text-secondary)]"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                          />
                        </svg>
                      </button>
                      <button
                        onClick={() => handleDeleteMemory(memory.id)}
                        className="p-1.5 hover:bg-[var(--color-error-light)] rounded-[var(--radius-sm)] transition-colors"
                        title="删除"
                      >
                        <svg
                          className="w-4 h-4 text-[var(--color-error)]"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    </div>
                  )}
                </div>
                <p className="text-sm text-[var(--color-text-primary)] mb-3 line-clamp-4">
                  {truncate(memory.content, 200)}
                </p>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1 flex-wrap">
                    {memory.tags?.slice(0, 3).map((tag) => (
                      <Badge key={tag} variant="primary" size="sm">
                        {tag}
                      </Badge>
                    ))}
                    {memory.tags && memory.tags.length > 3 && (
                      <span className="text-xs text-[var(--color-text-tertiary)]">
                        +{memory.tags.length - 3}
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-[var(--color-text-tertiary)]">
                    {formatDate(memory.created_at)}
                  </span>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
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
                  <tr
                    key={memory.id}
                    className={`hover:bg-[var(--color-bg-hover)] cursor-pointer ${
                      isBatchMode && selectedMemories.has(memory.id)
                        ? 'bg-[var(--color-accent-light)]'
                        : ''
                    }`}
                    onClick={() => {
                      if (isBatchMode) {
                        toggleMemorySelection(memory.id);
                      } else {
                        handleViewMemory(memory);
                      }
                    }}
                  >
                    {isBatchMode && (
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedMemories.has(memory.id)}
                          onChange={() => toggleMemorySelection(memory.id)}
                          className="rounded"
                        />
                      </td>
                    )}
                    <td className="px-4 py-3 text-sm truncate max-w-xs">
                      {truncate(memory.content, 100)}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="secondary" size="sm">
                        {typeLabels[memory.type] || memory.type}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-sm">{getImportanceLabel(memory.importance)}</td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1 flex-wrap">
                        {memory.tags?.slice(0, 2).map((tag) => (
                          <Badge key={tag} variant="primary" size="sm">
                            {tag}
                          </Badge>
                        ))}
                        {memory.tags && memory.tags.length > 2 && (
                          <span className="text-xs text-[var(--color-text-tertiary)]">
                            +{memory.tags.length - 2}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--color-text-secondary)]">
                      {formatDate(memory.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div
                        className="flex items-center justify-end gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          onClick={() => handleEditMemory(memory)}
                          className="p-1.5 hover:bg-[var(--color-bg-hover)] rounded-[var(--radius-sm)]"
                        >
                          <svg
                            className="w-4 h-4 text-[var(--color-text-secondary)]"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
                            />
                          </svg>
                        </button>
                        <button
                          onClick={() => handleDeleteMemory(memory.id)}
                          className="p-1.5 hover:bg-[var(--color-error-light)] rounded-[var(--radius-sm)]"
                        >
                          <svg
                            className="w-4 h-4 text-[var(--color-error)]"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                            />
                          </svg>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardBody>
        </Card>
      )}

      <Modal isOpen={showAddModal} onClose={() => setShowAddModal(false)} title="新建记忆">
        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-1.5 block">内容</label>
            <Textarea
              value={newMemory.content}
              onChange={(e) => setNewMemory({ ...newMemory, content: e.target.value })}
              placeholder="输入记忆内容..."
              className="min-h-[100px]"
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-sm font-medium mb-1.5 block">类型</label>
              <select
                value={newMemory.type}
                onChange={(e) => setNewMemory({ ...newMemory, type: e.target.value })}
                className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
              >
                <option value="long_term">长期记忆</option>
                <option value="short_term">短期记忆</option>
                <option value="permanent">永久记忆</option>
              </select>
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">重要性</label>
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    onClick={() => setNewMemory({ ...newMemory, importance: star })}
                    className="p-1"
                  >
                    <svg
                      className={`w-5 h-5 ${star <= newMemory.importance ? 'fill-yellow-400 text-yellow-400' : 'text-[var(--color-text-tertiary)]'}`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"
                      />
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          </div>
          <div>
            <label className="text-sm font-medium mb-1.5 block">标签（用逗号分隔）</label>
            <Input
              value={newMemory.tags}
              onChange={(e) => setNewMemory({ ...newMemory, tags: e.target.value })}
              placeholder="标签1, 标签2, 标签3"
            />
          </div>
          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary" onClick={() => setShowAddModal(false)}>
              取消
            </Button>
            <Button onClick={handleCreateMemory} disabled={!newMemory.content.trim()}>
              创建
            </Button>
          </div>
        </div>
      </Modal>

      <Modal isOpen={showEditModal} onClose={() => setShowEditModal(false)} title="编辑记忆">
        {editingMemory && (
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-1.5 block">内容</label>
              <Textarea
                value={editingMemory.content}
                onChange={(e) => setEditingMemory({ ...editingMemory, content: e.target.value })}
                className="min-h-[100px]"
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">重要性</label>
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((star) => (
                  <button
                    key={star}
                    onClick={() => setEditingMemory({ ...editingMemory, importance: star })}
                    className="p-1"
                  >
                    <svg
                      className={`w-5 h-5 ${star <= editingMemory.importance ? 'fill-yellow-400 text-yellow-400' : 'text-[var(--color-text-tertiary)]'}`}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"
                      />
                    </svg>
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-sm font-medium mb-1.5 block">标签（用逗号分隔）</label>
              <Input
                value={editingMemory.tags.join(', ')}
                onChange={(e) =>
                  setEditingMemory({
                    ...editingMemory,
                    tags: e.target.value
                      .split(',')
                      .map((t) => t.trim())
                      .filter(Boolean),
                  })
                }
              />
            </div>
            <div className="flex justify-end gap-3 pt-4">
              <Button variant="secondary" onClick={() => setShowEditModal(false)}>
                取消
              </Button>
              <Button onClick={handleUpdateMemory}>保存</Button>
            </div>
          </div>
        )}
      </Modal>

      <Drawer isOpen={showDetailDrawer} onClose={() => setShowDetailDrawer(false)} title="记忆详情">
        {selectedMemory && (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">内容</h3>
              <p className="text-[var(--color-text-primary)] whitespace-pre-wrap">
                {selectedMemory.content}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">
                  类型
                </h3>
                <Badge variant="secondary">
                  {typeLabels[selectedMemory.type] || selectedMemory.type}
                </Badge>
              </div>
              <div>
                <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">
                  重要性
                </h3>
                <span>{getImportanceLabel(selectedMemory.importance)}</span>
              </div>
            </div>
            <div>
              <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">标签</h3>
              <div className="flex gap-2 flex-wrap">
                {selectedMemory.tags?.map((tag) => (
                  <Badge key={tag} variant="primary">
                    {tag}
                  </Badge>
                ))}
                {(!selectedMemory.tags || selectedMemory.tags.length === 0) && (
                  <span className="text-[var(--color-text-tertiary)]">无标签</span>
                )}
              </div>
            </div>
            <div>
              <h3 className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">
                创建时间
              </h3>
              <span className="text-[var(--color-text-primary)]">
                {formatDate(selectedMemory.created_at)}
              </span>
            </div>
            <div className="flex gap-2 pt-4 border-t border-[var(--color-border)]">
              <Button
                variant="secondary"
                onClick={() => {
                  setShowDetailDrawer(false);
                  handleEditMemory(selectedMemory);
                }}
              >
                编辑
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  handleArchiveMemory(selectedMemory.id);
                  setShowDetailDrawer(false);
                }}
              >
                归档
              </Button>
              <Button
                variant="danger"
                onClick={() => {
                  handleDeleteMemory(selectedMemory.id);
                  setShowDetailDrawer(false);
                }}
              >
                删除
              </Button>
            </div>
          </div>
        )}
      </Drawer>

      <Modal
        isOpen={showBatchTagModal}
        onClose={() => setShowBatchTagModal(false)}
        title="批量更新标签"
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--color-text-secondary)]">
            将对选中的 {selectedMemories.size} 条记忆进行标签操作
          </p>
          <div>
            <label className="text-sm font-medium mb-1.5 block">操作类型</label>
            <select
              value={batchTagOperation}
              onChange={(e) => setBatchTagOperation(e.target.value as typeof batchTagOperation)}
              className="w-full px-3 py-2 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-md)]"
            >
              <option value="add">添加标签</option>
              <option value="remove">移除标签</option>
              <option value="set">设置标签（覆盖现有）</option>
            </select>
          </div>
          <div>
            <label className="text-sm font-medium mb-1.5 block">标签（用逗号分隔）</label>
            <Input
              value={batchTags}
              onChange={(e) => setBatchTags(e.target.value)}
              placeholder="标签1, 标签2, 标签3"
            />
          </div>
          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary" onClick={() => setShowBatchTagModal(false)}>
              取消
            </Button>
            <Button onClick={handleBatchUpdateTags} disabled={!batchTags.trim()}>
              确认
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
