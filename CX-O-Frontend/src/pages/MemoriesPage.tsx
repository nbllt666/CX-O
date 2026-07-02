import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { PageHeader } from '../components/layout';
import { Button, Card, CardBody } from '../components/ui';
import { AnimatedList } from '../components/AnimatedList';
import { useHotkey } from '../hooks';
import type { Memory, ViewMode } from './memories/types';
import { MemoryCard } from './memories/MemoryCard';
import { MemoryListItem } from './memories/MemoryListItem';
import { MemoriesToolbar } from './memories/MemoriesToolbar';
import { MemoryFormModal } from './memories/MemoryFormModal';
import { MemoryDetailDrawer } from './memories/MemoryDetailDrawer';
import { BatchTagModal } from './memories/BatchTagModal';

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
    </div>
  );
}
