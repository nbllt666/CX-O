/**
 * Agent 生活页（P4-T1）
 *
 * CX-O-Autonomy 自主系统控制台：
 * - 顶部状态卡片：运行/暂停/休眠/预算受限/禁用/异常徽章 + 上次行动/上次循环
 * - 四维动机可视化（curiosity/social_need/creative_drive/fatigue 进度条 0-100%）
 * - 日预算用量比例条（daily_budget_used_tokens vs config.budget.daily_token_limit）
 * - 控制区：启用/禁用开关、紧急停止（红色 + 确认）、暂停/恢复、自动启动设置
 * - 行为回放：审计列表（timestamp/action/target/result/trigger_reason，加载更多分页）
 *
 * 数据全部来自 autonomyApi。降级口径：
 * - getStatus 返回 null（后端离线）→ 全页错误态 + 重试
 * - getStatus 返回 {status:"disabled"}（未启用）→ 状态卡「未启用」徽章 + 引导提示
 * - config / audit 独立容错，失败不影响主状态展示
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Ban,
  HeartPulse,
  Pause,
  Play,
  Power,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { autonomyApi } from '@/api/clients/autonomy';
import type { AutonomyControlAction } from '@/api/clients/autonomy';
import type {
  AutonomyAuditEntry,
  AutonomyConfig,
  AutonomyMotivations,
  AutonomyStatus,
  AutonomyStatusActive,
} from '@/api/types';
import { cn } from '@/lib/utils';

const AUDIT_PAGE_SIZE = 20;

const MOTIVATION_KEYS: Array<keyof AutonomyMotivations> = [
  'curiosity',
  'social_need',
  'creative_drive',
  'fatigue',
];

/** 动机条配色（fatigue 用警示色，其余用氛围色） */
const MOTIVATION_TONES: Record<keyof AutonomyMotivations, string> = {
  curiosity: 'bg-sky-400',
  social_need: 'bg-pink-400',
  creative_drive: 'bg-violet-400',
  fatigue: 'bg-amber-400',
};

const EMPTY_MOTIVATIONS: AutonomyMotivations = {
  curiosity: 0,
  social_need: 0,
  creative_drive: 0,
  fatigue: 0,
};

function isActiveStatus(s: AutonomyStatus | null): s is AutonomyStatusActive {
  return !!s && s.status !== 'disabled';
}

/** 动机/预算进度条 */
function Bar({ pct, tone, testId }: { pct: number; tone: string; testId?: string }) {
  const width = Math.max(0, Math.min(100, Math.round(pct * 100)));
  return (
    <div
      data-testid={testId}
      className="h-2 w-full overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]"
    >
      <div
        className={cn('h-full rounded-full transition-all', tone)}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

export default function AutonomyPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<AutonomyStatus | null>(null);
  const [config, setConfig] = useState<AutonomyConfig | null>(null);
  const [auditItems, setAuditItems] = useState<AutonomyAuditEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditOffset, setAuditOffset] = useState(0);
  const [auditError, setAuditError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [busyAction, setBusyAction] = useState<AutonomyControlAction | 'auto_start' | null>(null);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const active = isActiveStatus(status);

  const fetchStatusAndConfig = useCallback(async () => {
    const [statusData, configData] = await Promise.all([
      autonomyApi.getStatus(),
      autonomyApi.getConfig().catch(() => null),
    ]);
    setStatus(statusData);
    setConfig(configData);
    return statusData;
  }, []);

  const loadAudit = useCallback(async (nextOffset: number, replace: boolean) => {
    const page = await autonomyApi.getAudit({ limit: AUDIT_PAGE_SIZE, offset: nextOffset });
    if (page === null) {
      setAuditError(true);
      return;
    }
    setAuditError(false);
    setAuditTotal(page.total);
    setAuditOffset(nextOffset + page.items.length);
    setAuditItems((prev) => (replace ? page.items : [...prev, ...page.items]));
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    setActionError(false);
    try {
      const statusData = await fetchStatusAndConfig();
      if (statusData === null) {
        // 后端离线：getStatus 返回 null → 全页错误态
        setLoadError(true);
      }
      await loadAudit(0, true);
    } catch (error) {
      console.error('Autonomy load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, [fetchStatusAndConfig, loadAudit]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleControl = async (action: AutonomyControlAction) => {
    if (busyAction) return;
    setBusyAction(action);
    setActionError(false);
    try {
      await autonomyApi.control(action);
      await fetchStatusAndConfig();
      await loadAudit(0, true);
    } catch (error) {
      console.error('Autonomy control failed:', error);
      setActionError(true);
    } finally {
      setBusyAction(null);
    }
  };

  const handleEmergencyStop = () => {
    if (!window.confirm(t('management.autonomy.emergencyConfirm'))) return;
    void handleControl('emergency_stop');
  };

  const handleToggleAutoStart = async () => {
    if (!config || busyAction) return;
    setBusyAction('auto_start');
    setActionError(false);
    try {
      const next = await autonomyApi.updateConfig({ auto_start: !config.auto_start });
      setConfig(next);
    } catch (error) {
      console.error('Autonomy auto-start update failed:', error);
      setActionError(true);
    } finally {
      setBusyAction(null);
    }
  };

  const handleLoadMore = async () => {
    if (isLoadingMore || auditItems.length >= auditTotal) return;
    setIsLoadingMore(true);
    await loadAudit(auditOffset, false);
    setIsLoadingMore(false);
  };

  const statusMeta = (() => {
    if (!active) {
      return { badgeKey: 'disabled', badgeCls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
    switch (status.status) {
      case 'running':
        return { badgeKey: 'running', badgeCls: 'bg-emerald-500/15 text-emerald-400' };
      case 'paused':
        return { badgeKey: 'paused', badgeCls: 'bg-amber-500/15 text-amber-400' };
      case 'sleeping':
        return { badgeKey: 'sleeping', badgeCls: 'bg-sky-500/15 text-sky-400' };
      case 'budget_limited':
        return { badgeKey: 'budgetLimited', badgeCls: 'bg-orange-500/15 text-orange-400' };
      case 'error':
        return { badgeKey: 'error', badgeCls: 'bg-red-500/15 text-red-400' };
      default:
        return { badgeKey: 'disabled', badgeCls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
  })();

  const motivations = active ? (status.motivations ?? EMPTY_MOTIVATIONS) : EMPTY_MOTIVATIONS;

  const usedTokens = active ? (status.daily_budget_used_tokens ?? 0) : 0;
  const dailyLimit = config?.budget?.daily_token_limit ?? 0;
  const budgetRatio = dailyLimit > 0 ? usedTokens / dailyLimit : 0;
  const budgetTone =
    budgetRatio >= 1 ? 'bg-red-400' : budgetRatio >= (config?.budget?.cost_alert_threshold ?? 0.8) ? 'bg-amber-400' : 'bg-emerald-400';

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.autonomy.subtitle')}</p>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t('management.autonomy.refresh')}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('management.autonomy.refresh')}
        </button>
      </div>

      {isLoading ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('common.loading')}
        </div>
      ) : loadError ? (
        <div className="glass-panel space-y-3 p-8 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-red-400" />
          <p className="text-sm text-red-400">{t('management.common.loadFailed')}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-1.5 text-xs transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.common.retry')}
          </button>
        </div>
      ) : (
        <>
          {/* ── 状态卡片 ── */}
          <div className="glass-panel space-y-4 p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <HeartPulse className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-semibold">{t('management.autonomy.statusTitle')}</h3>
                <span
                  className={cn('rounded px-2 py-0.5 text-[10px] font-medium', statusMeta.badgeCls)}
                >
                  {t(`management.autonomy.statusBadge.${statusMeta.badgeKey}`)}
                </span>
              </div>
            </div>

            {active ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                  <p className="text-[10px] text-muted-foreground">
                    {t('management.autonomy.lastAction')}
                  </p>
                  <p className="mt-0.5 truncate text-sm font-medium">
                    {status.last_action || t('management.autonomy.emptyValue')}
                  </p>
                </div>
                <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                  <p className="text-[10px] text-muted-foreground">
                    {t('management.autonomy.lastCycleAt')}
                  </p>
                  <p className="mt-0.5 truncate text-sm font-medium">
                    {status.last_cycle_at
                      ? new Date(status.last_cycle_at).toLocaleString()
                      : t('management.autonomy.emptyValue')}
                  </p>
                </div>
                <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                  <p className="text-[10px] text-muted-foreground">
                    {t('management.autonomy.budgetResetDate')}
                  </p>
                  <p className="mt-0.5 truncate text-sm font-medium">
                    {status.budget_reset_date || t('management.autonomy.emptyValue')}
                  </p>
                </div>
                <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                  <p className="text-[10px] text-muted-foreground">
                    {t('management.autonomy.budgetUsedToday')}
                  </p>
                  <p className="mt-0.5 truncate text-sm font-medium tabular-nums">
                    {usedTokens.toLocaleString()}
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-3 rounded-lg bg-[rgba(255,255,255,0.04)] p-4">
                <Ban className="h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t('management.autonomy.disabledTitle')}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('management.autonomy.disabledHint')}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* ── 四维动机 ── */}
          <div className="glass-panel space-y-3 p-4">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold">{t('management.autonomy.motivationsTitle')}</h3>
            </div>
            {active ? (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {MOTIVATION_KEYS.map((key) => (
                  <div key={key} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-muted-foreground">
                        {t(`management.autonomy.motivation.${key}`)}
                      </span>
                      <span className="tabular-nums font-medium">
                        {Math.round((motivations[key] ?? 0) * 100)}%
                      </span>
                    </div>
                    <Bar pct={motivations[key] ?? 0} tone={MOTIVATION_TONES[key]} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                {t('management.autonomy.motivationsDisabledHint')}
              </p>
            )}
          </div>

          {/* ── 预算用量 ── */}
          <div className="glass-panel space-y-2 p-4">
            <h3 className="text-sm font-semibold">{t('management.autonomy.budgetTitle')}</h3>
            {dailyLimit > 0 ? (
              <>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">
                    {t('management.autonomy.budgetUsed', {
                      used: usedTokens.toLocaleString(),
                      limit: dailyLimit.toLocaleString(),
                    })}
                  </span>
                  <span className={cn('tabular-nums font-medium', budgetRatio >= 1 && 'text-red-400', budgetRatio >= (config?.budget?.cost_alert_threshold ?? 0.8) && budgetRatio < 1 && 'text-amber-400')}>
                    {Math.round(budgetRatio * 100)}%
                  </span>
                </div>
                <Bar pct={budgetRatio} tone={budgetTone} testId="autonomy-budget-bar" />
                {budgetRatio >= 1 ? (
                  <p className="text-xs text-red-400">{t('management.autonomy.budgetExceeded')}</p>
                ) : budgetRatio >= (config?.budget?.cost_alert_threshold ?? 0.8) ? (
                  <p className="text-xs text-amber-400">{t('management.autonomy.budgetOverThreshold')}</p>
                ) : null}
              </>
            ) : (
              <p className="text-xs text-muted-foreground">{t('management.autonomy.budgetNoLimit')}</p>
            )}
          </div>

          {/* ── 控制区 ── */}
          <div className="glass-panel space-y-3 p-4">
            <h3 className="text-sm font-semibold">{t('management.autonomy.controlTitle')}</h3>
            <div className="flex flex-wrap items-center gap-2">
              {active ? (
                <>
                  <button
                    type="button"
                    onClick={() => void handleControl('disable')}
                    disabled={!!busyAction}
                    className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                  >
                    <Power className="h-3.5 w-3.5" />
                    {t('management.autonomy.disable')}
                  </button>
                  {status.status === 'running' ? (
                    <button
                      type="button"
                      onClick={() => void handleControl('pause')}
                      disabled={!!busyAction}
                      className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                    >
                      <Pause className="h-3.5 w-3.5" />
                      {t('management.autonomy.pause')}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => void handleControl('resume')}
                      disabled={!!busyAction}
                      className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                    >
                      <Play className="h-3.5 w-3.5" />
                      {t('management.autonomy.resume')}
                    </button>
                  )}
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleControl('enable')}
                  disabled={!!busyAction}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
                >
                  <Power className="h-3.5 w-3.5" />
                  {t('management.autonomy.enable')}
                </button>
              )}
              <button
                type="button"
                onClick={handleEmergencyStop}
                disabled={!!busyAction}
                className="flex items-center gap-1.5 rounded-lg bg-red-500/15 px-3 py-1.5 text-xs font-medium text-red-400 transition-colors hover:bg-red-500/25 disabled:opacity-50"
              >
                <Ban className="h-3.5 w-3.5" />
                {t('management.autonomy.emergencyStop')}
              </button>
              <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={config?.auto_start ?? false}
                  onChange={() => void handleToggleAutoStart()}
                  disabled={!config || !!busyAction}
                  className="h-4 w-4 accent-pink-500"
                />
                {t('management.autonomy.autoStart')}
              </label>
            </div>
            {actionError && (
              <p className="text-xs text-red-400">{t('management.autonomy.actionFailed')}</p>
            )}
          </div>

          {/* ── 行为回放（审计） ── */}
          <div className="glass-panel space-y-3 p-4">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t('management.autonomy.auditTitle')}</h3>
              <span className="text-[10px] text-muted-foreground">
                {t('management.autonomy.auditTotal', { count: auditTotal })}
              </span>
            </div>

            {auditError ? (
              <p className="py-6 text-center text-xs text-red-400">
                {t('management.autonomy.auditLoadFailed')}
              </p>
            ) : auditItems.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                {t('management.autonomy.auditEmpty')}
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-[var(--glass-border)] text-muted-foreground">
                      <th className="px-3 py-2 font-medium">{t('management.autonomy.colTimestamp')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.autonomy.colAction')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.autonomy.colTarget')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.autonomy.colResult')}</th>
                      <th className="px-3 py-2 font-medium">{t('management.autonomy.colTrigger')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditItems.map((item, i) => (
                      <tr
                        key={`${item.timestamp}-${item.action}-${i}`}
                        className="border-b border-[var(--glass-border)]/50 last:border-0"
                      >
                        <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                          {new Date(item.timestamp).toLocaleString()}
                        </td>
                        <td className="px-3 py-2 font-medium">{item.action}</td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {item.target || t('management.autonomy.emptyValue')}
                        </td>
                        <td className="px-3 py-2">
                          {item.result ? (
                            <span
                              className={cn(
                                'rounded px-1.5 py-0.5 text-[10px] font-medium',
                                item.result === 'success' && 'bg-emerald-500/15 text-emerald-400',
                                item.result === 'failed' && 'bg-red-500/15 text-red-400',
                                item.result === 'blocked' && 'bg-amber-500/15 text-amber-400',
                                item.result === 'skipped' &&
                                  'bg-[rgba(255,255,255,0.08)] text-muted-foreground',
                              )}
                            >
                              {t(`management.autonomy.result.${item.result}`)}
                            </span>
                          ) : (
                            t('management.autonomy.emptyValue')
                          )}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">
                          {item.trigger_reason || t('management.autonomy.emptyValue')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {!auditError && auditItems.length < auditTotal && (
              <button
                type="button"
                onClick={() => void handleLoadMore()}
                disabled={isLoadingMore}
                className="w-full rounded-lg border border-[var(--glass-border)] py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
              >
                {isLoadingMore
                  ? t('management.autonomy.loadingMore')
                  : t('management.autonomy.loadMore')}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
