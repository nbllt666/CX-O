/**
 * 记忆页（SubTask 6.4）
 *
 * 功能口径对齐 CX-O-Frontend MemoriesPage 的记忆列表面：
 * - 搜索（searchMemories，300ms 防抖；空词回退类型列表查询）
 * - 类型过滤（all / long_term / short_term / permanent）
 * - 记忆列表（内容摘要 + 类型徽章 + 重要性 + 标签 + 归档标记）
 * - 详情弹窗（查看 / 编辑 / 删除 / 归档）
 * - 新建 / 编辑弹窗（内容、类型、1-5 重要性、逗号分隔标签）
 *
 * 数据全部来自 memoriesApi，无 react-query，本地 useState + useEffect。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Archive,
  Brain,
  CalendarClock,
  Pencil,
  Plus,
  Search,
  Star,
  Trash2,
  X,
} from 'lucide-react';
import { memoriesApi } from '@/api/clients/memories';
import type { Memory } from '@/api/types';
import { cn } from '@/lib/utils';

type FilterType = 'all' | 'long_term' | 'short_term' | 'permanent';

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

export default function MemoriesPage() {
  const { t } = useTranslation();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<FilterType>('all');
  const [selected, setSelected] = useState<Memory | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Memory | null>(null);
  const [actionError, setActionError] = useState('');

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const query = searchQuery.trim();
      const result = query
        ? await memoriesApi.searchMemories(query)
        : await memoriesApi.getMemories({
            type: filterType === 'all' ? undefined : filterType,
            limit: 1000,
          });
      setMemories(result.memories);
    } catch (error) {
      console.error('Memories load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery, filterType]);

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

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4">
      <p className="shrink-0 text-sm text-muted-foreground">
        {t('management.memories.subtitle')}
      </p>

      {/* 工具行：搜索 + 类型过滤 + 新建 */}
      <div className="flex shrink-0 items-center gap-3">
        <div className="relative flex-1">
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
        <button
          type="button"
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
          className="flex items-center gap-1.5 rounded-lg bg-primary/85 px-3 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          <Plus className="h-4 w-4" />
          {t('management.memories.newMemory')}
        </button>
      </div>

      {actionError && (
        <div className="shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {actionError}
        </div>
      )}

      {/* 列表 */}
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
        ) : memories.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
            <Brain className="h-8 w-8 opacity-40" />
            <p className="text-sm font-medium">{t('management.memories.emptyTitle')}</p>
            <p className="text-xs">{t('management.memories.emptyHint')}</p>
          </div>
        ) : (
          <>
            <p className="mb-3 text-xs text-muted-foreground">
              {t('management.memories.total', { count: memories.length })}
            </p>
            <div className="space-y-2">
              {memories.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setSelected(m)}
                  className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3 text-left transition-all duration-fast hover:bg-[rgba(255,255,255,0.08)]"
                >
                  <p className="line-clamp-2 text-sm">{m.content}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                    <TypeBadge type={m.type} />
                    <ImportanceStars value={m.importance} />
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
              ))}
            </div>
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
    </div>
  );
}
