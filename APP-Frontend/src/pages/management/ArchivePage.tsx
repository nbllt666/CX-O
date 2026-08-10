/**
 * 归档页（SubTask 6.4）
 *
 * 功能口径对齐 CX-O-Frontend ArchivePage：
 * - 概览 Tab：归档统计卡（总归档数 / 合并记录 / 重复检测 / 归档层级数）、
 *   归档层级分布条、快速操作（自动归档 / 检测重复）
 * - 去重管理 Tab：重复记忆组列表（代表记忆 id、成员数、平均相似度）、组内合并
 *
 * 数据来自 memoriesApi（getArchiveStats / detectDuplicates / autoArchiveProcess /
 * mergeMemories），无 react-query，本地 useState + useEffect。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Archive,
  BarChart3,
  CheckCircle2,
  Copy,
  Layers,
  Loader2,
  Merge,
  ScanSearch,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { memoriesApi } from '@/api/clients/memories';
import type { ArchiveStats, DuplicateGroup } from '@/api/types';
import { cn } from '@/lib/utils';

type ArchiveTab = 'overview' | 'duplicates';

/** 组内平均相似度（similarity_matrix 值域 0~1，键为 id 对） */
function groupSimilarity(group: DuplicateGroup): number {
  const values = Object.values(group.similarity_matrix ?? {});
  if (values.length === 0) return 0;
  return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function StatCard(props: { label: string; value: number; icon: LucideIcon; tone: string }) {
  const Icon = props.icon;
  return (
    <div className="glass-panel flex items-center gap-4 p-4">
      <div
        className={cn(
          'flex h-11 w-11 shrink-0 items-center justify-center rounded-lg',
          props.tone,
        )}
      >
        <Icon className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{props.label}</p>
        <p className="text-2xl font-bold tabular-nums">{props.value}</p>
      </div>
    </div>
  );
}

export default function ArchivePage() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<ArchiveTab>('overview');
  const [stats, setStats] = useState<ArchiveStats | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateGroup[] | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isDetecting, setIsDetecting] = useState(false);
  const [processResult, setProcessResult] = useState<{ ok: boolean; text: string } | null>(null);

  const loadStats = useCallback(async () => {
    try {
      setStats(await memoriesApi.getArchiveStats());
    } catch (error) {
      console.error('Archive stats load failed:', error);
    }
  }, []);

  const loadDuplicates = useCallback(async () => {
    setIsDetecting(true);
    try {
      const res = await memoriesApi.detectDuplicates();
      setDuplicates(res.duplicate_groups);
    } catch (error) {
      console.error('Duplicate detect failed:', error);
      setDuplicates([]);
    } finally {
      setIsDetecting(false);
    }
  }, []);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  // 切到去重 Tab 且尚未加载过时自动检测一次
  useEffect(() => {
    if (activeTab === 'duplicates' && duplicates === null && !isDetecting) {
      void loadDuplicates();
    }
  }, [activeTab, duplicates, isDetecting, loadDuplicates]);

  const handleAutoArchive = async () => {
    setIsProcessing(true);
    setProcessResult(null);
    try {
      const result = await memoriesApi.autoArchiveProcess();
      const archived = result.archived_count ?? result.results?.archived?.length ?? 0;
      const merged = result.merged_count ?? result.results?.merged?.length ?? 0;
      setProcessResult({
        ok: true,
        text: t('management.archive.archiveResult', { archived, merged }),
      });
      void loadStats();
    } catch (error) {
      console.error('Auto archive failed:', error);
      setProcessResult({ ok: false, text: t('management.archive.archiveFailed') });
    } finally {
      setIsProcessing(false);
    }
  };

  const handleMergeGroup = async (group: DuplicateGroup) => {
    if (
      !window.confirm(
        t('management.archive.mergeConfirm', { count: group.memory_ids.length }),
      )
    ) {
      return;
    }
    setIsProcessing(true);
    try {
      await memoriesApi.mergeMemories(group.memory_ids);
      await loadDuplicates();
      void loadStats();
    } catch (error) {
      console.error('Merge failed:', error);
    } finally {
      setIsProcessing(false);
    }
  };

  const levelCounts = Object.entries(stats?.archive_level_counts ?? {}).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  const levelTotal = levelCounts.reduce((sum, [, n]) => sum + n, 0);

  const tabs: Array<{ id: ArchiveTab; labelKey: string; icon: LucideIcon }> = [
    { id: 'overview', labelKey: 'management.archive.tabOverview', icon: BarChart3 },
    { id: 'duplicates', labelKey: 'management.archive.tabDuplicates', icon: ScanSearch },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <p className="text-sm text-muted-foreground">{t('management.archive.subtitle')}</p>

      {/* Tab 切换 */}
      <div className="flex items-center gap-1 border-b border-[var(--glass-border)]">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                'flex items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors',
                activeTab === tab.id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-4 w-4" />
              {t(tab.labelKey)}
            </button>
          );
        })}
      </div>

      {activeTab === 'overview' ? (
        <>
          {/* 统计卡 */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label={t('management.archive.stats.totalArchived')}
              value={stats?.total_archived ?? stats?.archived_memories ?? 0}
              icon={Archive}
              tone="bg-primary/15 text-primary"
            />
            <StatCard
              label={t('management.archive.stats.merged')}
              value={stats?.merge_count ?? 0}
              icon={Merge}
              tone="bg-secondary/15 text-secondary"
            />
            <StatCard
              label={t('management.archive.stats.duplicates')}
              value={stats?.duplicate_count ?? 0}
              icon={Copy}
              tone="bg-amber-400/15 text-amber-400"
            />
            <StatCard
              label={t('management.archive.stats.levels')}
              value={levelCounts.length}
              icon={Layers}
              tone="bg-accent/15 text-accent"
            />
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* 层级分布 */}
            <div className="glass-panel p-5">
              <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
                <Layers className="h-4 w-4 text-secondary" />
                {t('management.archive.levelDist')}
              </h2>
              {levelCounts.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  {t('management.archive.noData')}
                </p>
              ) : (
                <div className="space-y-3">
                  {levelCounts.map(([level, count]) => (
                    <div key={level}>
                      <div className="mb-1 flex items-center justify-between text-xs">
                        <span className="text-muted-foreground">
                          {t('management.archive.level', { level })}
                        </span>
                        <span className="tabular-nums">{count}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]">
                        <div
                          className="h-full rounded-full bg-primary/70 transition-all duration-slow"
                          style={{
                            width: `${levelTotal > 0 ? Math.round((count / levelTotal) * 100) : 0}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 快速操作 */}
            <div className="glass-panel p-5">
              <h2 className="mb-4 text-base font-semibold">
                {t('management.archive.actions')}
              </h2>
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => void handleAutoArchive()}
                  disabled={isProcessing}
                  className="flex w-full items-center gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-4 py-3 text-sm transition-all duration-fast hover:bg-[rgba(255,255,255,0.08)] disabled:opacity-50"
                >
                  {isProcessing ? (
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  ) : (
                    <Archive className="h-4 w-4 text-primary" />
                  )}
                  {isProcessing
                    ? t('management.archive.processing')
                    : t('management.archive.autoArchive')}
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('duplicates')}
                  className="flex w-full items-center gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-4 py-3 text-sm transition-all duration-fast hover:bg-[rgba(255,255,255,0.08)]"
                >
                  <ScanSearch className="h-4 w-4 text-secondary" />
                  {t('management.archive.detectDuplicates')}
                </button>
              </div>

              {processResult && (
                <p
                  className={cn(
                    'mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs',
                    processResult.ok
                      ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
                      : 'border-red-500/30 bg-red-500/10 text-red-400',
                  )}
                >
                  {processResult.ok && <CheckCircle2 className="h-3.5 w-3.5" />}
                  {processResult.text}
                </p>
              )}
            </div>
          </div>
        </>
      ) : (
        /* 去重管理 */
        <div className="glass-panel p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-base font-semibold">
              {t('management.archive.dupTitle', { count: duplicates?.length ?? 0 })}
            </h2>
            <button
              type="button"
              onClick={() => void loadDuplicates()}
              disabled={isDetecting}
              className="flex items-center gap-1.5 rounded-lg bg-primary/85 px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {isDetecting ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  {t('management.archive.detecting')}
                </>
              ) : (
                t('management.archive.reDetect')
              )}
            </button>
          </div>

          {isDetecting && duplicates === null ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-20 animate-pulse rounded-lg bg-[rgba(255,255,255,0.06)]"
                />
              ))}
            </div>
          ) : !duplicates || duplicates.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-muted-foreground">
              <CheckCircle2 className="h-8 w-8 text-emerald-400/60" />
              <p className="text-sm font-medium">{t('management.archive.noDupTitle')}</p>
              <p className="text-xs">{t('management.archive.noDupHint')}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {duplicates.map((group) => (
                <div
                  key={group.group_id}
                  className="flex items-center gap-4 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4"
                >
                  <div className="min-w-0 flex-1 space-y-1 text-xs text-muted-foreground">
                    <p className="text-sm font-medium text-foreground">
                      {t('management.archive.memberCount', {
                        count: group.memory_ids.length,
                      })}
                    </p>
                    <p>
                      {t('management.archive.canonical')}：
                      <span className="font-mono">#{group.canonical_id}</span>
                      <span className="mx-2">·</span>
                      {t('management.archive.similarity')}：
                      <span className="tabular-nums">
                        {(groupSimilarity(group) * 100).toFixed(1)}%
                      </span>
                    </p>
                    <p className="font-mono text-[10px]">
                      ids: {group.memory_ids.join(', ')}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleMergeGroup(group)}
                    disabled={isProcessing}
                    className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary/85 px-3 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    <Merge className="h-3.5 w-3.5" />
                    {t('management.archive.merge')}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
