/**
 * 记忆页（SubTask 6.4）
 *
 * 功能口径对齐 CX-O-Frontend MemoriesPage 的记忆列表面：
 * - 搜索（searchMemories，300ms 防抖；空词回退类型列表查询）
 * - 类型过滤（all / long_term / short_term / permanent）
 * - Agent 选择器（getAgentMemoryTables，查询带上 agent_id）
 * - 视图切换（card / list）
 * - 批量选择模式（多选 / 全选 / 取消全选；标签 / 归档 / 删除）
 * - 批量标签弹窗（batchUpdateTags：add / remove / set）
 * - 记忆列表（内容摘要 + 类型徽章 + 重要性 + 标签 + 归档标记）
 * - 详情弹窗（查看 / 编辑 / 删除 / 归档）
 * - 新建 / 编辑弹窗（内容、类型、1-5 重要性、逗号分隔标签）
 *
 * 数据全部来自 memoriesApi，无 react-query，本地 useState + useEffect。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Archive,
  Bot,
  Brain,
  CalendarClock,
  CheckSquare,
  Film,
  LayoutGrid,
  List,
  Pencil,
  Plus,
  Search,
  Settings2,
  Square,
  Star,
  Tags,
  Trash2,
  X,
} from 'lucide-react';
import MemoryAgentPage from './MemoryAgentPage';
import { memoriesApi } from '@/api/clients/memories';
import type { Memory } from '@/api/types';
import { Button } from '@/components/ui-v2';
import { cn } from '@/lib/utils';
import { filterBySource, getVisionMeta, isVisionMemory } from './memoryFilter';
import type { MemorySourceFilter } from './memoryFilter';

type FilterType = 'all' | 'long_term' | 'short_term' | 'permanent';
type ViewMode = 'card' | 'list';
type BatchTagOperation = 'add' | 'remove' | 'set';

interface AgentOption {
  agent_id: string;
  table_name: string;
  created_at: string;
}

const TYPE_KEYS: Record<string, string> = {
  long_term: 'management.memories.typeLongTerm',
  short_term: 'management.memories.typeShortTerm',
  permanent: 'management.memories.typePermanent',
};

const TYPE_TONES: Record<string, string> = {
  long_term: 'bg-primary/15 text-primary',
  short_term: 'bg-secondary/15 text-secondary',
  permanent: 'bg-accent/15 text-accent',
};

/** 类型徽章 */
function TypeBadge(props: { type: string }) {
  const { t } = useTranslation();
  const key = TYPE_KEYS[props.type];
  return (
    <span
      className={cn(
        'rounded px-1.5 py-0.5 text-[10px] font-medium',
        TYPE_TONES[props.type] ?? 'bg-[rgba(255,255,255,0.08)] text-muted-foreground',
      )}
    >
      {key ? t(key) : props.type}
    </span>
  );
}

/** 重要性星级（1-5，只读） */
function ImportanceStars(props: { value: number }) {
  return (
    <span className="flex items-center gap-0.5">
      {[1, 2, 3, 4, 5].map((s) => (
        <Star
          key={s}
          className={cn(
            'h-3 w-3',
            s <= props.value ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground/40',
          )}
        />
      ))}
    </span>
  );
}

/** 视觉叙事记忆徽章：来源 + 事件类型 + 情绪（元数据缺失则不展示） */
function VisionBadges(props: { m: Memory }) {
  const { t } = useTranslation();
  const meta = getVisionMeta(props.m);
  return (
    <>
      <span className="flex items-center gap-1 rounded bg-violet-500/15 px-1.5 py-0.5 font-medium text-violet-300">
        <Film className="h-2.5 w-2.5" />
        {t('management.memories.visionBadge')}
      </span>
      {meta.event_type && (
        <span className="rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5">
          {t('management.memories.eventType')}：{meta.event_type}
        </span>
      )}
      {meta.emotion && (
        <span className="rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5">
          {t('management.memories.emotion')}：{meta.emotion}
        </span>
      )}
    </>
  );
}

/** 新建 / 编辑弹窗 */
function MemoryFormModal(props: {
  memory: Memory | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const isEdit = props.memory !== null;
  const [content, setContent] = useState(props.memory?.content ?? '');
  const [type, setType] = useState(props.memory?.type ?? 'long_term');
  const [importance, setImportance] = useState(props.memory?.importance ?? 3);
  const [tags, setTags] = useState(props.memory?.tags.join(', ') ?? '');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);

  const handleSave = async () => {
    if (!content.trim() || isSaving) return;
    setIsSaving(true);
    setSaveError(false);
    const payload = {
      content: content.trim(),
      type,
      importance,
      tags: tags
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean),
    };
    try {
      if (isEdit && props.memory) {
        await memoriesApi.updateMemory(props.memory.id, payload);
      } else {
        await memoriesApi.createMemory(payload);
      }
      props.onSaved();
      props.onClose();
    } catch (error) {
      console.error('Memory save failed:', error);
      setSaveError(true);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-lg space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {t(isEdit ? 'management.memories.editTitle' : 'management.memories.createTitle')}
          </h2>
          <button
            type="button"
            onClick={props.onClose}
            aria-label={t('management.memories.close')}
            className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.memories.content')}
          </label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
            className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t('management.memories.type')}
            </label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            >
              <option value="long_term">{t('management.memories.typeLongTerm')}</option>
              <option value="short_term">{t('management.memories.typeShortTerm')}</option>
              <option value="permanent">{t('management.memories.typePermanent')}</option>
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t('management.memories.importance')}
            </label>
            <div className="flex items-center gap-1 pt-1.5">
              {[1, 2, 3, 4, 5].map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setImportance(s)}
                  className="p-0.5"
                  aria-label={`${s}`}
                >
                  <Star
                    className={cn(
                      'h-5 w-5 transition-colors',
                      s <= importance
                        ? 'fill-amber-400 text-amber-400'
                        : 'text-muted-foreground/40 hover:text-amber-400/60',
                    )}
                  />
                </button>
              ))}
            </div>
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.memories.tags')}
          </label>
          <input
            type="text"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            {t('management.memories.tagsHint')}
          </p>
        </div>

        {saveError && (
          <p className="text-xs text-red-400">{t('management.memories.saveFailed')}</p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={props.onClose}
            className="rounded-lg px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            {t('management.memories.close')}
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!content.trim() || isSaving}
            className="rounded-lg bg-primary/85 px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {t('management.memories.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

/** 批量标签弹窗（add / remove / set） */
function BatchTagModal(props: {
  selectedCount: number;
  operation: BatchTagOperation;
  tags: string;
  onOperationChange: (op: BatchTagOperation) => void;
  onTagsChange: (tags: string) => void;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-md space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">{t('management.memories.batchTagTitle')}</h2>
          <button
            type="button"
            onClick={props.onClose}
            aria-label={t('management.memories.close')}
            className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="text-xs text-muted-foreground">
          {t('management.memories.batchTagHint', { count: props.selectedCount })}
        </p>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.memories.batchTagOperation')}
          </label>
          <select
            value={props.operation}
            onChange={(e) => props.onOperationChange(e.target.value as BatchTagOperation)}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          >
            <option value="add">{t('management.memories.batchTagOperationAdd')}</option>
            <option value="remove">{t('management.memories.batchTagOperationRemove')}</option>
            <option value="set">{t('management.memories.batchTagOperationSet')}</option>
          </select>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.memories.batchTagInput')}
          </label>
          <input
            type="text"
            value={props.tags}
            onChange={(e) => props.onTagsChange(e.target.value)}
            placeholder={t('management.memories.batchTagInputPlaceholder')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </div>

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={props.onClose}
            className="rounded-lg px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            {t('management.memories.cancel')}
          </button>
          <button
            type="button"
            onClick={props.onConfirm}
            disabled={!props.tags.trim()}
            className="rounded-lg bg-primary/85 px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {t('management.memories.confirmTag')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function MemoriesPage() {
  const { t } = useTranslation();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<FilterType>('all');
  const [filterSource, setFilterSource] = useState<MemorySourceFilter>('all');
  const [currentAgentId, setCurrentAgentId] = useState('default');
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>('card');
  const [isBatchMode, setIsBatchMode] = useState(false);
  const [selectedMemories, setSelectedMemories] = useState<Set<number>>(new Set());
  const [showBatchTagModal, setShowBatchTagModal] = useState(false);
  const [batchTagOperation, setBatchTagOperation] = useState<BatchTagOperation>('add');
  const [batchTags, setBatchTags] = useState('');
  const [selected, setSelected] = useState<Memory | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Memory | null>(null);
  const [actionError, setActionError] = useState('');
  const [showAssistantModal, setShowAssistantModal] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const query = searchQuery.trim();
      const result = query
        ? await memoriesApi.searchMemories(query, {
            // 搜索模式同样遵循列表过滤条件：类型/Agent 空值不传（后端 MemorySearchRequest 支持）
            type: filterType === 'all' ? undefined : filterType,
            agent_id: currentAgentId || undefined,
          })
        : await memoriesApi.getMemories({
            type: filterType === 'all' ? undefined : filterType,
            limit: 1000,
            agent_id: currentAgentId,
          });
      setMemories(result.memories);
    } catch (error) {
      console.error('Memories load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery, filterType, currentAgentId]);

  // 搜索词 300ms 防抖；类型切换立即刷新
  useEffect(() => {
    const timer = setTimeout(
      () => {
        void load();
      },
      searchQuery.trim() ? 300 : 0,
    );
    return () => clearTimeout(timer);
  }, [load, searchQuery]);

  // 加载 Agent 列表
  useEffect(() => {
    let disposed = false;
    memoriesApi
      .getAgentMemoryTables()
      .then((res) => {
        if (!disposed) setAgents(res.agents ?? []);
      })
      .catch((error) => {
        console.error('Agents load failed:', error);
      });
    return () => {
      disposed = true;
    };
  }, []);

  const clearSelection = () => {
    setSelectedMemories(new Set());
  };

  const toggleMemorySelection = (id: number) => {
    setSelectedMemories((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const selectAllMemories = () => {
    setSelectedMemories((prev) => {
      if (prev.size === visibleMemories.length && visibleMemories.length > 0) {
        return new Set<number>();
      }
      return new Set(visibleMemories.map((m) => m.id));
    });
  };

  const handleDelete = async (memory: Memory) => {
    if (!window.confirm(t('management.memories.deleteConfirm'))) return;
    setActionError('');
    try {
      await memoriesApi.deleteMemory(memory.id);
      setSelected(null);
      await load();
    } catch (error) {
      console.error('Memory delete failed:', error);
      setActionError(t('management.memories.deleteFailed'));
    }
  };

  const handleArchive = async (memory: Memory) => {
    setActionError('');
    try {
      await memoriesApi.archiveMemory(memory.id);
      setSelected(null);
      await load();
    } catch (error) {
      console.error('Memory archive failed:', error);
      setActionError(t('management.memories.saveFailed'));
    }
  };

  const handleBatchDelete = async () => {
    if (selectedMemories.size === 0) return;
    if (!window.confirm(t('management.memories.batchDeleteConfirm', { count: selectedMemories.size }))) return;
    setActionError('');
    try {
      await memoriesApi.batchDeleteMemories(Array.from(selectedMemories));
      clearSelection();
      await load();
    } catch (error) {
      console.error('Batch delete failed:', error);
      setActionError(t('management.memories.batchFailed'));
    }
  };

  const handleBatchArchive = async () => {
    if (selectedMemories.size === 0) return;
    if (!window.confirm(t('management.memories.batchArchiveConfirm', { count: selectedMemories.size }))) return;
    setActionError('');
    try {
      await memoriesApi.batchArchiveMemories(Array.from(selectedMemories));
      clearSelection();
      await load();
    } catch (error) {
      console.error('Batch archive failed:', error);
      setActionError(t('management.memories.batchFailed'));
    }
  };

  const handleBatchUpdateTags = async () => {
    if (selectedMemories.size === 0) return;
    const tags = batchTags
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (tags.length === 0) return;
    setActionError('');
    try {
      await memoriesApi.batchUpdateTags(Array.from(selectedMemories), tags, batchTagOperation);
      setShowBatchTagModal(false);
      setBatchTags('');
      clearSelection();
      await load();
    } catch (error) {
      console.error('Batch tag update failed:', error);
      setActionError(t('management.memories.batchFailed'));
    }
  };

  const handleItemClick = (memory: Memory) => {
    if (isBatchMode) {
      toggleMemorySelection(memory.id);
    } else {
      setSelected(memory);
    }
  };

  // 来源过滤（'vision' 仅保留视觉叙事记忆）——前端侧过滤，按列级 source 字段判断
  const visibleMemories = useMemo(
    () => filterBySource(memories, filterSource),
    [memories, filterSource],
  );

  const allSelected = visibleMemories.length > 0 && selectedMemories.size === visibleMemories.length;

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4">
      <p className="shrink-0 text-sm text-muted-foreground">
        {t('management.memories.subtitle')}
      </p>

      {/* 工具行：搜索 + 类型过滤 + Agent + 视图切换 + 批量 + 新建 */}
      <div className="flex shrink-0 flex-wrap items-center gap-3">
        <div className="relative min-w-[180px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('management.memories.searchPlaceholder')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] py-2 pl-9 pr-3 text-sm backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </div>
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as FilterType)}
          className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        >
          <option value="all">{t('management.memories.typeAll')}</option>
          <option value="long_term">{t('management.memories.typeLongTerm')}</option>
          <option value="short_term">{t('management.memories.typeShortTerm')}</option>
          <option value="permanent">{t('management.memories.typePermanent')}</option>
        </select>
        {/* 来源过滤：全部 / 视觉记忆（前端侧过滤，依据列级 source==='vision'） */}
        <select
          value={filterSource}
          onChange={(e) => setFilterSource(e.target.value as MemorySourceFilter)}
          aria-label={t('management.memories.sourceFilter')}
          title={t('management.memories.sourceFilter')}
          className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        >
          <option value="all">{t('management.memories.sourceAll')}</option>
          <option value="vision">{t('management.memories.sourceVision')}</option>
        </select>
        {/* 视觉叙事增强能力的中性提示徽章（仅指明来源，非错误态） */}
        {filterSource === 'vision' && (
          <span className="shrink-0 rounded-full border border-violet-400/30 bg-violet-400/10 px-2.5 py-0.5 text-[10px] font-medium text-violet-300">
            <Film className="mr-1 inline h-3 w-3 align-[-1px]" />
            {t('management.memories.sourceVisionHint')}
          </span>
        )}
        <select
          value={currentAgentId}
          onChange={(e) => setCurrentAgentId(e.target.value)}
          aria-label={t('management.memories.agent')}
          className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        >
          <option value="default">{t('management.memories.agentDefault')}</option>
          {agents
            .filter((a) => a.agent_id !== 'default')
            .map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.agent_id}
              </option>
            ))}
        </select>
        <div className="flex items-center overflow-hidden rounded-lg border border-[var(--glass-border)]">
          <button
            type="button"
            onClick={() => setViewMode('card')}
            aria-label={t('management.memories.viewCard')}
            title={t('management.memories.viewCard')}
            className={cn(
              'flex items-center px-2.5 py-2 text-muted-foreground transition-colors',
              viewMode === 'card' && 'bg-[rgba(255,255,255,0.12)] text-foreground',
            )}
          >
            <LayoutGrid className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setViewMode('list')}
            aria-label={t('management.memories.viewList')}
            title={t('management.memories.viewList')}
            className={cn(
              'flex items-center px-2.5 py-2 text-muted-foreground transition-colors',
              viewMode === 'list' && 'bg-[rgba(255,255,255,0.12)] text-primary',
            )}
          >
            <List className="h-4 w-4" />
          </button>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Bot className="h-4 w-4 text-primary" />}
          onClick={() => setShowAssistantModal(true)}
        >
          {t('management.memories.openAssistant')}
        </Button>
        <Button
          variant={isBatchMode ? 'primary' : 'secondary'}
          size="sm"
          icon={<Settings2 className="h-4 w-4" />}
          onClick={() => {
            if (isBatchMode) clearSelection();
            setIsBatchMode((prev) => !prev);
          }}
        >
          {t(isBatchMode ? 'management.memories.exitBatch' : 'management.memories.batchMode')}
        </Button>
        <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => {
          setEditing(null);
          setShowForm(true);
        }}>
          {t('management.memories.newMemory')}
        </Button>
      </div>

      {actionError && (
        <div className="shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {actionError}
        </div>
      )}

      {/* 批量操作条 */}
      {isBatchMode && (
        <div className="flex shrink-0 items-center justify-between gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-4 py-2.5">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="sm" onClick={selectAllMemories}>
              <CheckSquare className="h-4 w-4" />
              {t(allSelected ? 'management.memories.cancelSelectAll' : 'management.memories.selectAll')}
            </Button>
            <span className="text-xs text-muted-foreground">
              {t('management.memories.selectedCount', { count: selectedMemories.size })}
            </span>
          </div>
          {selectedMemories.size > 0 && (
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon={<Tags className="h-4 w-4" />}
                onClick={() => setShowBatchTagModal(true)}
              >
                {t('management.memories.batchTag')}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={<Archive className="h-4 w-4" />}
                onClick={() => void handleBatchArchive()}
              >
                {t('management.memories.batchArchive')}
              </Button>
              <Button
                variant="danger"
                size="sm"
                icon={<Trash2 className="h-4 w-4" />}
                onClick={() => void handleBatchDelete()}
              >
                {t('management.memories.batchDelete')}
              </Button>
            </div>
          )}
        </div>
      )}

      {/* 列表 / 卡片 */}
      <div className="glass-panel min-h-0 flex-1 overflow-y-auto p-4">
        {isLoading ? (
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg bg-[rgba(255,255,255,0.06)]"
              />
            ))}
          </div>
        ) : loadError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3">
            <span className="text-sm text-red-400">{t('management.common.loadFailed')}</span>
            <button
              type="button"
              onClick={() => void load()}
              className="rounded-lg bg-primary/85 px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
            >
              {t('management.common.retry')}
            </button>
          </div>
        ) : visibleMemories.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
            <Brain className="h-8 w-8 opacity-40" />
            <p className="text-sm font-medium">{t('management.memories.emptyTitle')}</p>
            <p className="text-xs">{t('management.memories.emptyHint')}</p>
          </div>
        ) : (
          <>
            <p className="mb-3 text-xs text-muted-foreground">
              {t('management.memories.total', { count: visibleMemories.length })}
            </p>
            {viewMode === 'card' ? (
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {visibleMemories.map((m) => {
                  const isSelected = selectedMemories.has(m.id);
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => handleItemClick(m)}
                      className={cn(
                        'relative rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3 text-left transition-all duration-fast hover:bg-[rgba(255,255,255,0.08)]',
                        isBatchMode && isSelected && 'border-[rgba(255,183,225,0.6)] bg-[rgba(255,183,225,0.08)]',
                      )}
                    >
                      {isBatchMode && (
                        <span className="absolute right-2 top-2">
                          {isSelected ? (
                            <CheckSquare className="h-4 w-4 text-primary" />
                          ) : (
                            <Square className="h-4 w-4 text-muted-foreground/50" />
                          )}
                        </span>
                      )}
                      <p className="line-clamp-2 pr-5 text-sm">{m.content}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                        <TypeBadge type={m.type} />
                        <ImportanceStars value={m.importance} />
                        {isVisionMemory(m) && <VisionBadges m={m} />}
                        {m.is_archived && (
                          <span className="flex items-center gap-1 rounded bg-amber-400/15 px-1.5 py-0.5 font-medium text-amber-400">
                            <Archive className="h-2.5 w-2.5" />
                            {t('management.memories.archivedBadge')}
                          </span>
                        )}
                        {m.tags.slice(0, 4).map((tag) => (
                          <span key={tag} className="rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5">
                            #{tag}
                          </span>
                        ))}
                        <span className="ml-auto flex items-center gap-1">
                          <CalendarClock className="h-2.5 w-2.5" />
                          {m.created_at ? new Date(m.created_at).toLocaleDateString() : ''}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="space-y-2">
                {visibleMemories.map((m) => {
                  const isSelected = selectedMemories.has(m.id);
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => handleItemClick(m)}
                      className={cn(
                        'flex w-full items-center gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3 text-left transition-all duration-fast hover:bg-[rgba(255,255,255,0.08)]',
                        isBatchMode && isSelected && 'border-[rgba(255,183,225,0.6)] bg-[rgba(255,183,225,0.08)]',
                      )}
                    >
                      {isBatchMode &&
                        (isSelected ? (
                          <CheckSquare className="h-4 w-4 shrink-0 text-primary" />
                        ) : (
                          <Square className="h-4 w-4 shrink-0 text-muted-foreground/50" />
                        ))}
                      <div className="min-w-0 flex-1">
                        <p className="line-clamp-2 text-sm">{m.content}</p>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                          <TypeBadge type={m.type} />
                          <ImportanceStars value={m.importance} />
                          {isVisionMemory(m) && <VisionBadges m={m} />}
                          {m.is_archived && (
                            <span className="flex items-center gap-1 rounded bg-amber-400/15 px-1.5 py-0.5 font-medium text-amber-400">
                              <Archive className="h-2.5 w-2.5" />
                              {t('management.memories.archivedBadge')}
                            </span>
                          )}
                          {m.tags.slice(0, 4).map((tag) => (
                            <span key={tag} className="rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5">
                              #{tag}
                            </span>
                          ))}
                        </div>
                      </div>
                      <span className="ml-auto flex shrink-0 items-center gap-1 text-[10px] text-muted-foreground">
                        <CalendarClock className="h-2.5 w-2.5" />
                        {m.created_at ? new Date(m.created_at).toLocaleDateString() : ''}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>

      {/* 详情弹窗 */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="glass-panel w-full max-w-lg space-y-4 p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">
                {t('management.memories.detailTitle')}
              </h2>
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label={t('management.memories.close')}
                className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="whitespace-pre-wrap break-words rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3 text-sm">
              {selected.content}
            </p>

            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <TypeBadge type={selected.type} />
              <ImportanceStars value={selected.importance} />
              {selected.is_archived && (
                <span className="flex items-center gap-1 rounded bg-amber-400/15 px-1.5 py-0.5 font-medium text-amber-400">
                  <Archive className="h-2.5 w-2.5" />
                  {t('management.memories.archivedBadge')}
                </span>
              )}
              {selected.tags.map((tag) => (
                <span key={tag} className="rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5">
                  #{tag}
                </span>
              ))}
            </div>

            <p className="text-xs text-muted-foreground">
              {t('management.memories.createdAt')}：
              {selected.created_at ? new Date(selected.created_at).toLocaleString() : '—'}
            </p>

            <div className="flex justify-end gap-2">
              {!selected.is_archived && (
                <button
                  type="button"
                  onClick={() => void handleArchive(selected)}
                  className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-amber-400 transition-colors hover:bg-amber-400/10"
                >
                  <Archive className="h-4 w-4" />
                  {t('management.memories.archive')}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setEditing(selected);
                  setSelected(null);
                  setShowForm(true);
                }}
                className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-primary transition-colors hover:bg-primary/10"
              >
                <Pencil className="h-4 w-4" />
                {t('management.memories.edit')}
              </button>
              <button
                type="button"
                onClick={() => void handleDelete(selected)}
                className="flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm text-red-400 transition-colors hover:bg-red-500/10"
              >
                <Trash2 className="h-4 w-4" />
                {t('management.memories.delete')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 新建 / 编辑弹窗 */}
      {showForm && (
        <MemoryFormModal
          memory={editing}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
          }}
          onSaved={() => void load()}
        />
      )}

      {/* 批量标签弹窗 */}
      {showBatchTagModal && (
        <BatchTagModal
          selectedCount={selectedMemories.size}
          operation={batchTagOperation}
          tags={batchTags}
          onOperationChange={setBatchTagOperation}
          onTagsChange={setBatchTags}
          onConfirm={() => void handleBatchUpdateTags()}
          onClose={() => setShowBatchTagModal(false)}
        />
      )}

      {/* 记忆管理助手弹窗 / 抽屉 */}
      {showAssistantModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-md">
          <div className="glass-panel flex h-[85vh] w-full max-w-4xl flex-col p-6 shadow-2xl">
            <div className="mb-3 flex shrink-0 items-center justify-between border-b border-[var(--glass-border)] pb-3">
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/15 text-primary">
                  <Bot className="h-4 w-4" />
                </div>
                <h2 className="text-base font-semibold">
                  {t('management.memories.assistantDrawerTitle')}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShowAssistantModal(false);
                  void load(); // 对话修改记忆后自动刷新列表
                }}
                aria-label={t('management.memories.close')}
                className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <MemoryAgentPage />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}