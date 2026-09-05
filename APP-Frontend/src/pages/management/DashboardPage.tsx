/**
 * 仪表盘页（SubTask 6.2）
 *
 * 功能口径对齐 CX-O-Frontend DashboardPage：
 * - 关键统计卡片：记忆总数 / 会话总数 / Agent 总数 / 今日活跃会话
 * - 后端健康状态面板：/health 的 status、version 与 database/memory/vector_store 组件态
 * - 服务统计：已归档记忆、消息总数
 * - 快捷操作：发起对话 / 浏览记忆 / 记忆归档 / 系统设置
 *
 * - 性能指标：语音链路延迟（ASR / LLM 首 Token / TTS 首帧 / 端到端）P50/P95 横条，
 *   15s 轮询 + in-flight 互斥，无样本或拉取失败时区块内静默降级为空态
 *
 * 数据全部来自已有 api clients（healthApi / memoriesApi / chatApi / agentsApi / metricsApi），
 * 无 react-query 依赖，本地 useState + useEffect 拉取；失败展示错误态并可重试。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
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
  Gauge,
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
import { metricsApi } from '@/api/clients/metrics';
import type { VoiceLatencyStats } from '@/api/clients/metrics';
import type { HealthStatus, Session } from '@/api/types';
import { cn } from '@/lib/utils';

interface DashboardData {
  health: HealthStatus;
  stats: MemoryStats;
  sessions: Session[];
  agentCount: number;
}

/** 性能横条归一化上限（ms）：超过按满格截断，数值仍真实显示 */
const PERF_BAR_MAX_MS = 1500;
/** 性能指标轮询间隔（ms） */
const PERF_POLL_MS = 15000;

/** 性能指标区块的段定义（按语音链路管线顺序：识别 → 首Token → 首帧 → 端到端） */
const PERF_SEGMENTS: Array<{
  key: 'asr' | 'ttft' | 'tts_first' | 'e2e';
  labelKey: string;
}> = [
  { key: 'asr', labelKey: 'management.dashboard.performance.segments.asr' },
  { key: 'ttft', labelKey: 'management.dashboard.performance.segments.ttft' },
  { key: 'tts_first', labelKey: 'management.dashboard.performance.segments.ttsFirst' },
  { key: 'e2e', labelKey: 'management.dashboard.performance.segments.e2e' },
];

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

/** 性能横条：宽度按 ms 归一化（上限 PERF_BAR_MAX_MS 截断），数值真实显示；无值为 — */
function PerfBar(props: { label: string; value: number | null; tone: string }) {
  const { t } = useTranslation();
  const ms = props.value;
  const pct = Math.max(0, Math.min((ms ?? 0) / PERF_BAR_MAX_MS, 1)) * 100;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-8 shrink-0 text-muted-foreground">{props.label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]">
        <div
          className={cn('h-full rounded-full transition-all duration-fast', props.tone)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-20 shrink-0 text-right font-mono tabular-nums text-muted-foreground">
        {ms == null ? '—' : `${Math.round(ms)} ${t('management.dashboard.performance.unit')}`}
      </span>
    </div>
  );
}

/** 性能指标单段卡片：段名 + P50/P95 两条横条 */
function PerfSegment(props: { label: string; p50: number | null; p95: number | null }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-1.5 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2.5">
      <p className="text-xs font-medium">{props.label}</p>
      <PerfBar
        label={t('management.dashboard.performance.p50')}
        value={props.p50}
        tone="bg-primary/70"
      />
      <PerfBar
        label={t('management.dashboard.performance.p95')}
        value={props.p95}
        tone="bg-amber-400/70"
      />
    </div>
  );
}

export default function DashboardPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<DashboardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [voiceLatency, setVoiceLatency] = useState<VoiceLatencyStats | null>(null);
  const [perfError, setPerfError] = useState(false);
  // 在途互斥：15s 轮询周期内上一请求未返回时跳过本 tick，防止并发叠请求
  // （照抄 useBackendFailover 的 in-flight 互斥范式）
  const perfInFlightRef = useRef(false);

  const loadPerf = useCallback(async () => {
    if (perfInFlightRef.current) return;
    perfInFlightRef.current = true;
    try {
      const stats = await metricsApi.getVoiceLatency();
      // 陈旧响应（客户端 seq 判定）返回 null，丢弃不做状态更新
      if (stats) {
        setVoiceLatency(stats);
        setPerfError(false);
      }
    } catch (error) {
      // 静默降级：仅在性能区块内显示空态+提示，不影响页面其他区块
      console.error('Voice latency load failed:', error);
      setVoiceLatency(null);
      setPerfError(true);
    } finally {
      perfInFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    void loadPerf();
    const timer = setInterval(() => void loadPerf(), PERF_POLL_MS);
    return () => clearInterval(timer);
  }, [loadPerf]);

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

  // 空态判定：无数据或四段样本数全为 0（含请求失败的静默降级空态）
  const perfSummary = voiceLatency?.summary;
  const perfEmpty =
    !perfSummary || PERF_SEGMENTS.every((seg) => (perfSummary[seg.key]?.count ?? 0) === 0);

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

      {/* 性能指标：语音链路延迟（P50/P95 横条，15s 轮询） */}
      <div className="glass-panel p-5">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-base font-semibold">
            <Gauge className="h-4 w-4 text-accent" />
            {t('management.dashboard.performance.title')}
          </h2>
          {voiceLatency && (
            <span className="text-xs text-muted-foreground">
              {t('management.dashboard.performance.samples')}: {voiceLatency.buffer_size}
            </span>
          )}
        </div>
        {perfEmpty ? (
          <div className="space-y-1">
            <p className="text-sm text-muted-foreground">
              {t('management.dashboard.performance.empty')}
            </p>
            {perfError && (
              <p className="text-xs text-amber-400/80">
                {t('management.dashboard.performance.errorHint')}
              </p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {PERF_SEGMENTS.map((seg) => {
              const s = perfSummary?.[seg.key];
              return (
                <PerfSegment
                  key={seg.key}
                  label={t(seg.labelKey)}
                  p50={s?.p50 ?? null}
                  p95={s?.p95 ?? null}
                />
              );
            })}
          </div>
        )}
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
