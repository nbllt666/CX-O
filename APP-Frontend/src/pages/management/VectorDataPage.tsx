/**
 * 向量数据页（SubTask 7.3）
 *
 * 功能口径对齐 CX-O-Frontend VectorDataPage：
 * - 统计行：向量总数 / 记忆总数 / 索引率 / 后端（vectorApi.getVectorStats）
 * - 未启用态：stats.vector_enabled 为 false 时展示引导卡片
 * - 操作区：语义搜索（弹窗展示相似度结果）、记忆 ID 直达详情、刷新、同步向量、重建向量（需确认）
 * - 向量列表：类型筛选、分页（20/50/100）、详情弹窗、删除（需确认）
 * - 集合信息：stats.collection_info JSON 展示
 *
 * 数据全部来自 vectorApi。参考前端的时间轴组件（TimeAxis）在 APP-Frontend 无对应依赖，
 * 本页不移植该组件，其余功能面对齐。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Database,
  Percent,
  RefreshCw,
  Search,
  Sigma,
  X,
} from 'lucide-react';
import { vectorApi } from '@/api/clients/vector';
import type { VectorStats } from '@/api/clients/vector';
import type { VectorData } from '@/api/types';
import { cn } from '@/lib/utils';

const TYPE_OPTIONS = ['', 'short_term', 'long_term', 'working', 'episodic'] as const;
const PAGE_SIZES = [20, 50, 100];

export default function VectorDataPage() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<VectorStats | null>(null);
  const [vectors, setVectors] = useState<VectorData[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [actionMsg, setActionMsg] = useState('');

  const [typeFilter, setTypeFilter] = useState('');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(50);

  const [searchInput, setSearchInput] = useState('');
  const [searchResults, setSearchResults] = useState<VectorData[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  const [idLookup, setIdLookup] = useState('');
  const [detail, setDetail] = useState<VectorData | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const statsResp = await vectorApi.getVectorStats();
      setStats(statsResp);
      if (statsResp.vector_enabled) {
        const listResp = await vectorApi.listVectors(
          pageSize,
          page * pageSize,
          typeFilter || undefined,
        );
        setVectors(listResp.vectors || []);
        setTotal(listResp.total ?? 0);
      } else {
        setVectors([]);
        setTotal(0);
      }
    } catch (error) {
      console.error('Vector load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, [page, pageSize, typeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalPages = useMemo(() => Math.max(1, Math.ceil(total / pageSize)), [total, pageSize]);

  const handleSearch = async () => {
    const query = searchInput.trim();
    if (!query || isSearching) return;
    setIsSearching(true);
    setActionError(false);
    try {
      const resp = await vectorApi.searchVectors(query, 10);
      setSearchResults(resp.results || []);
    } catch (error) {
      console.error('Vector search failed:', error);
      setActionError(true);
    } finally {
      setIsSearching(false);
    }
  };

  const openDetail = async (memoryId: number) => {
    setActionError(false);
    try {
      const data = await vectorApi.getVector(memoryId);
      setDetail(data);
    } catch (error) {
      console.error('Vector detail failed:', error);
      setActionError(true);
    }
  };

  const handleIdLookup = () => {
    const id = Number.parseInt(idLookup, 10);
    if (!Number.isFinite(id) || id <= 0) return;
    void openDetail(id);
  };

  const handleDelete = async (memoryId: number) => {
    if (!window.confirm(t('management.vector.deleteConfirm', { id: memoryId }))) return;
    setActionError(false);
    try {
      await vectorApi.deleteVector(memoryId);
      await load();
    } catch (error) {
      console.error('Vector delete failed:', error);
      setActionError(true);
    }
  };

  const handleSync = async () => {
    setActionError(false);
    setActionMsg('');
    try {
      const resp = await vectorApi.syncVectors();
      setActionMsg(t('management.vector.syncDone', { status: resp.status }));
      await load();
    } catch (error) {
      console.error('Vector sync failed:', error);
      setActionError(true);
    }
  };

  const handleRebuild = async () => {
    if (!window.confirm(t('management.vector.rebuildConfirm'))) return;
    setActionError(false);
    setActionMsg('');
    try {
      const resp = await vectorApi.rebuildVectors();
      setActionMsg(t('management.vector.rebuildDone', { status: resp.status }));
      await load();
    } catch (error) {
      console.error('Vector rebuild failed:', error);
      setActionError(true);
    }
  };

  const inputCls =
    'rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.vector.subtitle')}</p>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t('management.vector.refresh')}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('management.vector.refresh')}
        </button>
      </div>

      {isLoading ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('common.loading')}
        </div>
      ) : loadError ? (
        <div className="glass-panel space-y-3 p-8 text-center">
          <p className="text-sm text-red-400">{t('management.common.loadFailed')}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-1.5 text-xs transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.common.retry')}
          </button>
        </div>
      ) : !stats?.vector_enabled ? (
        <div className="glass-panel space-y-2 p-10 text-center">
          <Database className="mx-auto h-8 w-8 text-muted-foreground" />
          <h3 className="text-base font-semibold">{t('management.vector.disabledTitle')}</h3>
          <p className="text-sm text-muted-foreground">{t('management.vector.disabledHint')}</p>
        </div>
      ) : (
        <>
          {/* 统计行 */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="glass-panel flex items-center gap-4 p-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
                <Sigma className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">{t('management.vector.statsVectors')}</p>
                <p className="text-2xl font-bold tabular-nums">{stats.total_vectors}</p>
              </div>
            </div>
            <div className="glass-panel flex items-center gap-4 p-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary/15 text-secondary">
                <Database className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">{t('management.vector.statsMemories')}</p>
                <p className="text-2xl font-bold tabular-nums">{stats.total_memories}</p>
              </div>
            </div>
            <div className="glass-panel flex items-center gap-4 p-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
                <Percent className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">{t('management.vector.statsRatio')}</p>
                <p className="text-2xl font-bold tabular-nums">
                  {(stats.indexed_ratio * 100).toFixed(1)}%
                </p>
              </div>
            </div>
            <div className="glass-panel flex items-center gap-4 p-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent">
                <Database className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <p className="text-xs text-muted-foreground">{t('management.vector.statsBackend')}</p>
                <p className="truncate text-2xl font-bold">{stats.backend}</p>
              </div>
            </div>
          </div>

          {/* 操作区 */}
          <div className="glass-panel space-y-3 p-4">
            <h3 className="text-sm font-semibold">{t('management.vector.opsTitle')}</h3>
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void handleSearch()}
                aria-label={t('management.vector.searchPlaceholder')}
                placeholder={t('management.vector.searchPlaceholder')}
                className={cn(inputCls, 'min-w-[220px] flex-1')}
              />
              <button
                type="button"
                onClick={() => void handleSearch()}
                disabled={isSearching || !searchInput.trim()}
                className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                <Search className="h-3.5 w-3.5" />
                {isSearching ? t('management.vector.searching') : t('management.vector.search')}
              </button>
              <input
                value={idLookup}
                onChange={(e) => setIdLookup(e.target.value.replace(/\D/g, ''))}
                onKeyDown={(e) => e.key === 'Enter' && handleIdLookup()}
                aria-label={t('management.vector.idPlaceholder')}
                placeholder={t('management.vector.idPlaceholder')}
                className={cn(inputCls, 'w-28')}
              />
              <button
                type="button"
                onClick={handleIdLookup}
                className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
              >
                <ArrowRight className="h-3.5 w-3.5" />
                {t('management.vector.lookup')}
              </button>
              <button
                type="button"
                onClick={() => void handleSync()}
                className="rounded-lg border border-[var(--glass-border)] px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
              >
                {t('management.vector.sync')}
              </button>
              <button
                type="button"
                onClick={() => void handleRebuild()}
                className="rounded-lg border border-[var(--glass-border)] px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
              >
                {t('management.vector.rebuild')}
              </button>
            </div>
            {actionMsg && <p className="text-xs text-emerald-400">{actionMsg}</p>}
            {actionError && (
              <p className="text-xs text-red-400">{t('management.vector.actionFailed')}</p>
            )}
          </div>

          {/* 向量列表 */}
          <div className="glass-panel space-y-3 p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t('management.vector.listTitle')}</h3>
              <select
                value={typeFilter}
                onChange={(e) => {
                  setTypeFilter(e.target.value);
                  setPage(0);
                }}
                aria-label={t('management.vector.typeFilter')}
                className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1.5 text-xs focus:outline-none"
              >
                {TYPE_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt === '' ? t('management.vector.typeAll') : opt}
                  </option>
                ))}
              </select>
            </div>

            {vectors.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {t('management.vector.empty')}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-[var(--glass-border)] text-muted-foreground">
                      <th className="px-3 py-2 font-medium">{t('management.vector.colId')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.vector.colContent')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.vector.colType')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.vector.colImportance')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.vector.colCreatedAt')}</th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('management.vector.colActions')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {vectors.map((vec) => (
                      <tr
                        key={vec.memory_id}
                        className="border-b border-[var(--glass-border)] last:border-0"
                      >
                        <td className="px-3 py-2 font-mono">{vec.memory_id}</td>
                        <td className="max-w-[280px] truncate px-3 py-2">{vec.content}</td>
                        <td className="px-3 py-2">
                          <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[10px] text-secondary">
                            {vec.memory_type}
                          </span>
                        </td>
                        <td className="px-3 py-2 tabular-nums">{vec.importance}</td>
                        <td className="px-3 py-2 text-muted-foreground">{vec.created_at || '-'}</td>
                        <td className="px-3 py-2 text-right">
                          <button
                            type="button"
                            onClick={() => void openDetail(vec.memory_id)}
                            className="mr-3 text-primary hover:underline"
                          >
                            {t('management.vector.detail')}
                          </button>
                          <button
                            type="button"
                            onClick={() => void handleDelete(vec.memory_id)}
                            aria-label={t('management.vector.delete')}
                            className="text-red-400 hover:underline"
                          >
                            {t('management.vector.delete')}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* 分页栏 */}
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                {t('management.vector.pageInfo', { total, page: page + 1, pages: totalPages })}
              </span>
              <div className="flex items-center gap-2">
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setPage(0);
                  }}
                  aria-label={t('management.vector.pageSize')}
                  className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1.5 focus:outline-none"
                >
                  {PAGE_SIZES.map((size) => (
                    <option key={size} value={size}>
                      {t('management.vector.pageSizeOption', { count: size })}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  aria-label={t('management.vector.prev')}
                  className="flex items-center gap-1 rounded-lg border border-[var(--glass-border)] px-2 py-1.5 transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  {t('management.vector.prev')}
                </button>
                <button
                  type="button"
                  disabled={page + 1 >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  aria-label={t('management.vector.next')}
                  className="flex items-center gap-1 rounded-lg border border-[var(--glass-border)] px-2 py-1.5 transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                >
                  {t('management.vector.next')}
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>

          {/* 集合信息 */}
          {stats.collection_info && Object.keys(stats.collection_info).length > 0 && (
            <div className="glass-panel space-y-3 p-4">
              <h3 className="text-sm font-semibold">{t('management.vector.collectionInfo')}</h3>
              <pre className="max-h-60 overflow-auto rounded-lg border border-[var(--glass-border)] bg-[rgba(0,0,0,0.25)] p-3 text-xs">
                {JSON.stringify(stats.collection_info, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}

      {/* 语义搜索结果弹窗 */}
      {searchResults !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="glass-panel max-h-[85vh] w-full max-w-lg space-y-4 overflow-y-auto p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">{t('management.vector.searchTitle')}</h2>
              <button
                type="button"
                onClick={() => setSearchResults(null)}
                aria-label={t('management.vector.close')}
                className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {searchResults.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {t('management.vector.searchEmpty')}
              </p>
            ) : (
              <div className="space-y-3">
                {searchResults.map((result, idx) => {
                  const score = (result as unknown as Record<string, unknown>).score;
                  return (
                    <div
                      key={`${result.memory_id}-${idx}`}
                      className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.03)] p-3"
                    >
                      <div className="mb-1.5 flex items-center justify-between">
                        {typeof score === 'number' && (
                          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                            {t('management.vector.similarity', { score: score.toFixed(3) })}
                          </span>
                        )}
                        <span className="ml-auto text-[10px] text-muted-foreground">
                          ID: {result.memory_id}
                        </span>
                      </div>
                      <p className="text-sm">{result.content}</p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 向量详情弹窗 */}
      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="glass-panel max-h-[85vh] w-full max-w-lg space-y-4 overflow-y-auto p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">{t('management.vector.detailTitle')}</h2>
              <button
                type="button"
                onClick={() => setDetail(null)}
                aria-label={t('management.vector.close')}
                className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  {t('management.vector.colId')}
                </p>
                <p className="font-mono">{detail.memory_id}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  {t('management.vector.colType')}
                </p>
                <p>{detail.memory_type}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  {t('management.vector.colImportance')}
                </p>
                <p className="tabular-nums">{detail.importance}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  {t('management.vector.colCreatedAt')}
                </p>
                <p>{detail.created_at || '-'}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  {t('management.vector.colContent')}
                </p>
                <pre className="max-h-48 overflow-auto rounded-lg border border-[var(--glass-border)] bg-[rgba(0,0,0,0.25)] p-3 text-xs">
                  {detail.content}
                </pre>
              </div>
            </div>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => setDetail(null)}
                className="rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
              >
                {t('management.vector.close')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
