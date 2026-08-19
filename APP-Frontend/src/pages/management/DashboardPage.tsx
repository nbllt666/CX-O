/**
 * 仪表盘页（SubTask 6.2）
 *
 * 功能口径对齐 CX-O-Frontend DashboardPage：
 * - 关键统计卡片：记忆总数 / 会话总数 / Agent 总数 / 今日活跃会话
 * - 后端健康状态面板：/health 的 status、version 与 database/memory/vector_store 组件态
 * - 服务统计：已归档记忆、消息总数
 * - 快捷操作：发起对话 / 浏览记忆 / 记忆归档 / 系统设置
 *
 * 数据全部来自已有 api clients（healthApi / memoriesApi / chatApi / agentsApi），
 * 无 react-query 依赖，本地 useState + useEffect 拉取；失败展示错误态并可重试。
 */
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Archive,
  ArrowRight,
  Bot,
  Brain,
  CalendarClock,
  Database,
  HeartPulse,
  MemoryStick,
  MessageSquareText,
  MessagesSquare,
  Settings,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { healthApi } from '@/api/clients/health';
import { memoriesApi } from '@/api/clients/memories';
import type { MemoryStats } from '@/api/clients/memories';
import { chatApi } from '@/api/clients/chat';
import { agentsApi } from '@/api/clients/agents';
import type { HealthStatus, Session } from '@/api/types';
import { cn } from '@/lib/utils';

interface DashboardData {
  health: HealthStatus;
  stats: MemoryStats;
  sessions: Session[];
  agentCount: number;
}

/** 统计今日活跃会话（updated_at 落在今日 0 点之后） */
function countTodaySessions(sessions: Session[]): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return sessions.filter((s) => {
    if (!s.updated_at) return false;
    const d = new Date(s.updated_at);
    return !Number.isNaN(d.getTime()) && d >= today;
  }).length;
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

function StatCardSkeleton() {
  return (
    <div className="glass-panel flex items-center gap-4 p-4">
      <div className="h-11 w-11 animate-pulse rounded-lg bg-[rgba(255,255,255,0.08)]" />
      <div className="flex-1 space-y-2">
        <div className="h-3 w-16 animate-pulse rounded bg-[rgba(255,255,255,0.08)]" />
        <div className="h-6 w-12 animate-pulse rounded bg-[rgba(255,255,255,0.08)]" />
      </div>
    </div>
  );
}

/** 组件健康徽章：ok/healthy/true → 正常（绿），其余 → 异常（红） */
function HealthBadge(props: { ok: boolean; label: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={cn(
        'flex items-center justify-between rounded-lg border border-[var(--glass-border)] px-3 py-2 text-sm',
        'bg-[rgba(255,255,255,0.04)]',
      )}
    >
      <span className="text-muted-foreground">{props.label}</span>
      <span
        className={cn(
          'flex items-center gap-1.5 text-xs font-medium',
          props.ok ? 'text-emerald-400' : 'text-red-400',
        )}
      >
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full',
            props.ok ? 'bg-emerald-400' : 'bg-red-400',
          )}
        />
        {props.ok ? t('management.dashboard.health.ok') : t('management.dashboard.health.abnormal')}
      </span>
    </span>
  );
}

function isComponentOk(
  component?: { status: string } | boolean,
  fallbackBool?: boolean,
): boolean {
  if (typeof component === 'boolean') return component;
  if (component && typeof component === 'object' && component.status) {
    const s = component.status.toLowerCase();
    return s === 'ok' || s === 'healthy' || s === 'up' || s === 'connected';
  }
  return fallbackBool ?? false;
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<DashboardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const [health, stats, sessions, agents] = await Promise.all([
        healthApi.getHealth(),
        memoriesApi.getStats(),
        chatApi.getSessions(),
        agentsApi.getAgents(),
      ]);
      setData({
        health,
        stats,
        sessions,
        agentCount: agents.filter((a) => a.id !== 'memory-agent').length,
      });
    } catch (error) {
      console.error('Dashboard load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const quickActions: Array<{ to: string; labelKey: string; icon: LucideIcon }> = [
    { to: '/chat', labelKey: 'management.dashboard.quick.chat', icon: MessageSquareText },
    { to: '/memories', labelKey: 'management.dashboard.quick.memories', icon: Brain },
    { to: '/archive', labelKey: 'management.dashboard.quick.archive', icon: Archive },
    { to: '/settings', labelKey: 'management.dashboard.quick.settings', icon: Settings },
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <p className="text-sm text-muted-foreground">{t('management.dashboard.subtitle')}</p>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {isLoading || !data ? (
          <>
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
          </>
        ) : (
          <>
            <StatCard
              label={t('management.dashboard.stats.memories')}
              value={data.stats.total_memories}
              icon={Brain}
              tone="bg-primary/15 text-primary"
            />
            <StatCard
              label={t('management.dashboard.stats.sessions')}
              value={data.sessions.length}
              icon={MessagesSquare}
              tone="bg-secondary/15 text-secondary"
            />
            <StatCard
              label={t('management.dashboard.stats.agents')}
              value={data.agentCount}
              icon={Bot}
              tone="bg-accent/15 text-accent"
            />
            <StatCard
              label={t('management.dashboard.stats.todaySessions')}
              value={countTodaySessions(data.sessions)}
              icon={CalendarClock}
              tone="bg-emerald-400/15 text-emerald-400"
            />
          </>
        )}
      </div>

      {loadError && (
        <div className="glass-panel flex items-center justify-between p-4">
          <span className="text-sm text-red-400">{t('management.common.loadFailed')}</span>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg bg-primary/85 px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            {t('management.common.retry')}
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 后端健康状态 */}
        <div className="glass-panel p-5 lg:col-span-2">
          <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
            <HeartPulse className="h-4 w-4 text-primary" />
            {t('management.dashboard.health.title')}
          </h2>
          {isLoading || !data ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-9 animate-pulse rounded-lg bg-[rgba(255,255,255,0.06)]"
                />
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2 text-sm">
                <span className="flex items-center gap-2 text-muted-foreground">
                  <Activity className="h-3.5 w-3.5" />
                  {t('management.dashboard.health.version')}
                </span>
                <span className="font-mono text-xs">{data.health.version ?? '—'}</span>
              </div>
              <HealthBadge
                ok={isComponentOk(data.health.database, data.health.components?.memory_manager)}
                label={t('management.dashboard.health.database')}
              />
              <HealthBadge
                ok={isComponentOk(data.health.memory, data.health.components?.memory_manager)}
                label={t('management.dashboard.health.memory')}
              />
              <HealthBadge
                ok={isComponentOk(data.health.vector_store, data.health.components?.memory_manager)}
                label={t('management.dashboard.health.vectorStore')}
              />
            </div>
          )}
        </div>

        {/* 快捷操作 */}
        <div className="glass-panel p-5">
          <h2 className="mb-4 text-base font-semibold">
            {t('management.dashboard.quick.title')}
          </h2>
          <div className="space-y-2">
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Link
                  key={action.to}
                  to={action.to}
                  className="group flex items-center gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2.5 text-sm transition-all duration-fast hover:bg-[rgba(255,255,255,0.08)]"
                >
                  <Icon className="h-4 w-4 text-primary" />
                  <span>{t(action.labelKey)}</span>
                  <ArrowRight className="ml-auto h-3.5 w-3.5 opacity-0 transition-opacity duration-fast group-hover:opacity-100" />
                </Link>
              );
            })}
          </div>
        </div>
      </div>

      {/* 服务统计 */}
      <div className="glass-panel p-5">
        <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
          <Database className="h-4 w-4 text-secondary" />
          {t('management.dashboard.service.title')}
        </h2>
        {isLoading || !data ? (
          <div className="grid grid-cols-2 gap-4">
            {[0, 1].map((i) => (
              <div
                key={i}
                className="h-16 animate-pulse rounded-lg bg-[rgba(255,255,255,0.06)]"
              />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4">
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Archive className="h-3.5 w-3.5" />
                {t('management.dashboard.service.archived')}
              </p>
              <p className="mt-1 text-xl font-bold tabular-nums">
                {data.stats.archived_memories}
              </p>
            </div>
            <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4">
              <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <MemoryStick className="h-3.5 w-3.5" />
                {t('management.dashboard.service.messages')}
              </p>
              <p className="mt-1 text-xl font-bold tabular-nums">{data.stats.total_messages}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
