/**
 * 梦境日志页（DreamPage）
 *
 * CX-O-Dream 梦境引擎控制台：
 * - 顶部状态卡片：待命中/梦境生成中/清除已调度/未启用徽章 + 上次会话 + 会话统计
 * - 操作区：手动触发 / 手动清除
 * - 梦境候选列表：按会话分组，卡片展示内容 / lucidity_score / decision / 关联素材，
 *   含确认 / 否定（按 id）与按会话清除（红线 R5）
 * - 配置编辑区：含 enabled 开关与主要参数，保存调 updateConfig 后刷新
 *
 * 数据全部来自 dreamApi。降级口径（对齐 AutonomyPage）：
 * - getStatus 返回 null（后端离线）→ 全页错误态 + 重试
 * - getStatus 返回 {status:"disabled"}（未启用）→ 状态卡「未启用」徽章 + 引导提示
 * - config / list 独立容错，失败不影响主状态展示
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Ban,
  Check,
  Moon,
  Play,
  RefreshCw,
  Save,
  Trash2,
  X,
} from 'lucide-react';
import { dreamApi } from '@/api/clients/dream';
import type {
  DreamBufferEntry,
  DreamConfig,
  DreamStats,
  DreamStatus,
  DreamStatusActive,
} from '@/api/types';
import { cn } from '@/lib/utils';

const EMPTY_STATS: DreamStats = {
  sessions: 0,
  generated: 0,
  approved: 0,
  rejected: 0,
  purges: 0,
};

/** 忙碌动作标记：用于禁用对应按钮，避免重复提交 */
type DreamBusyAction =
  | 'trigger'
  | 'purge'
  | 'confirm'
  | 'reject'
  | 'clear-session'
  | 'save-config';

function isActiveStatus(s: DreamStatus | null): s is DreamStatusActive {
  return !!s && s.status !== 'disabled';
}

/** 文本输入字段 */
function TextField({
  label,
  value,
  onChange,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  testId?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <input
        data-testid={testId}
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-[var(--glass-border)] bg-transparent px-2 py-1 text-xs outline-none focus:border-primary/50"
      />
    </label>
  );
}

/** 数字输入字段 */
function NumberField({
  label,
  value,
  onChange,
  step,
  testId,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step?: number;
  testId?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <input
        data-testid={testId}
        type="number"
        value={Number.isFinite(value) ? String(value) : ''}
        onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
        step={step}
        className="rounded-lg border border-[var(--glass-border)] bg-transparent px-2 py-1 text-xs outline-none focus:border-primary/50"
      />
    </label>
  );
}

/** 布尔开关字段 */
function CheckboxField({
  label,
  checked,
  onChange,
  testId,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  testId?: string;
}) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      <input
        data-testid={testId}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-pink-500"
      />
      {label}
    </label>
  );
}

export default function DreamPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<DreamStatus | null>(null);
  const [items, setItems] = useState<DreamBufferEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [listError, setListError] = useState(false);
  const [actionError, setActionError] = useState(false);
  const [busyAction, setBusyAction] = useState<DreamBusyAction | null>(null);
  const [draft, setDraft] = useState<DreamConfig | null>(null);
  const [saved, setSaved] = useState(false);
  // 配置草稿同步标记：仅初始加载与保存成功后从服务端回填，用户编辑不被刷新覆盖
  const draftSyncedRef = useRef(false);

  const active = isActiveStatus(status);

  const fetchStatusAndConfig = useCallback(async () => {
    const [statusData, configData] = await Promise.all([
      dreamApi.getStatus(),
      dreamApi.getConfig().catch(() => null),
    ]);
    setStatus(statusData);
    if (configData && !draftSyncedRef.current) {
      setDraft(configData);
      draftSyncedRef.current = true;
    }
    return statusData;
  }, []);

  const loadList = useCallback(async () => {
    const page = await dreamApi.getList();
    if (page === null) {
      setListError(true);
      return;
    }
    setListError(false);
    setItems(page.items);
    setTotal(page.total);
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    setActionError(false);
    setSaved(false);
    try {
      const statusData = await fetchStatusAndConfig();
      if (statusData === null) {
        // 后端离线：getStatus 返回 null → 全页错误态
        setLoadError(true);
      }
      await loadList();
    } catch (error) {
      console.error('Dream load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, [fetchStatusAndConfig, loadList]);

  useEffect(() => {
    void load();
  }, [load]);

  /** 通用操作包装：执行 → 刷新状态/列表，失败置 actionError */
  const handleAction = async (action: DreamBusyAction, fn: () => Promise<unknown>) => {
    if (busyAction) return;
    setBusyAction(action);
    setActionError(false);
    try {
      await fn();
      await fetchStatusAndConfig();
      await loadList();
    } catch (error) {
      console.error('Dream action failed:', error);
      setActionError(true);
    } finally {
      setBusyAction(null);
    }
  };

  const handleReject = (id: number) => {
    if (!window.confirm(t('management.dream.rejectConfirm'))) return;
    void handleAction('reject', () => dreamApi.reject(id));
  };

  const handleClearSession = (sessionId: string) => {
    if (!window.confirm(t('management.dream.clearSessionConfirm'))) return;
    void handleAction('clear-session', () => dreamApi.purgeSession(sessionId));
  };

  const updateDraft = (patch: Partial<DreamConfig>) => {
    setDraft((prev) => (prev ? { ...prev, ...patch } : prev));
    setSaved(false);
  };

  const updateSchedule = (patch: Partial<DreamConfig['schedule']>) => {
    setDraft((prev) => (prev ? { ...prev, schedule: { ...prev.schedule, ...patch } } : prev));
    setSaved(false);
  };

  const handleSaveConfig = async () => {
    if (!draft || busyAction) return;
    setBusyAction('save-config');
    setActionError(false);
    setSaved(false);
    try {
      const next = await dreamApi.updateConfig(draft);
      setDraft(next);
      setSaved(true);
      await fetchStatusAndConfig();
      await loadList();
    } catch (error) {
      console.error('Dream config save failed:', error);
      setActionError(true);
    } finally {
      setBusyAction(null);
    }
  };

  const statusMeta = (() => {
    if (!active) {
      return { badgeKey: 'disabled', badgeCls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
    switch (status.status) {
      case 'idle':
        return { badgeKey: 'idle', badgeCls: 'bg-emerald-500/15 text-emerald-400' };
      case 'dreaming':
        return { badgeKey: 'dreaming', badgeCls: 'bg-sky-500/15 text-sky-400' };
      case 'purge_scheduled':
        return { badgeKey: 'purgeScheduled', badgeCls: 'bg-amber-500/15 text-amber-400' };
      default:
        return { badgeKey: 'disabled', badgeCls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
  })();

  const decisionMeta = (decision: DreamBufferEntry['decision']) => {
    switch (decision) {
      case 'pending':
        return { cls: 'bg-amber-500/15 text-amber-400' };
      case 'approved':
        return { cls: 'bg-emerald-500/15 text-emerald-400' };
      case 'rejected':
        return { cls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
      default:
        return { cls: 'bg-[rgba(255,255,255,0.08)] text-muted-foreground' };
    }
  };

  const stats = active ? (status.stats ?? EMPTY_STATS) : EMPTY_STATS;

  /** 按梦境会话分组（保留候选的 created_at 倒序语义） */
  const sessionGroups = useMemo(() => {
    const map = new Map<string, DreamBufferEntry[]>();
    for (const item of items) {
      const sid = item.dream_session_id || 'unknown';
      const list = map.get(sid);
      if (list) {
        list.push(item);
      } else {
        map.set(sid, [item]);
      }
    }
    return Array.from(map.entries());
  }, [items]);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.dream.subtitle')}</p>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t('management.dream.refresh')}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('management.dream.refresh')}
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
                <Moon className="h-4 w-4 text-primary" />
                <h3 className="text-sm font-semibold">{t('management.dream.statusTitle')}</h3>
                <span
                  className={cn('rounded px-2 py-0.5 text-[10px] font-medium', statusMeta.badgeCls)}
                >
                  {t(`management.dream.statusBadge.${statusMeta.badgeKey}`)}
                </span>
              </div>
            </div>

            {active ? (
              <>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.lastSessionAt')}
                    </p>
                    <p className="mt-0.5 truncate text-sm font-medium">
                      {status.last_session_at
                        ? new Date(status.last_session_at).toLocaleString()
                        : t('management.dream.emptyValue')}
                    </p>
                  </div>
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.statSessions')}
                    </p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums">{stats.sessions}</p>
                  </div>
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.statGenerated')}
                    </p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums">{stats.generated}</p>
                  </div>
                  <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                    <p className="text-[10px] text-muted-foreground">
                      {t('management.dream.statPurges')}
                    </p>
                    <p className="mt-0.5 text-sm font-medium tabular-nums">{stats.purges}</p>
                  </div>
                </div>
              </>
            ) : (
              <div className="flex items-center gap-3 rounded-lg bg-[rgba(255,255,255,0.04)] p-4">
                <Ban className="h-5 w-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0">
                  <p className="text-sm font-medium">{t('management.dream.disabledTitle')}</p>
                  <p className="text-xs text-muted-foreground">
                    {t('management.dream.disabledHint')}
                  </p>
                </div>
              </div>
            )}
          </div>

          {/* ── 操作区（仅启用时） ── */}
          {active && (
            <div className="glass-panel space-y-3 p-4">
              <h3 className="text-sm font-semibold">{t('management.dream.operationsTitle')}</h3>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void handleAction('trigger', () => dreamApi.trigger())}
                  disabled={!!busyAction}
                  className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                >
                  <Play className="h-3.5 w-3.5" />
                  {t('management.dream.trigger')}
                </button>
                <button
                  type="button"
                  onClick={() => void handleAction('purge', () => dreamApi.purge())}
                  disabled={!!busyAction}
                  className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t('management.dream.purge')}
                </button>
              </div>
              {actionError && (
                <p className="text-xs text-red-400">{t('management.dream.actionFailed')}</p>
              )}
            </div>
          )}

          {/* ── 梦境候选列表（仅启用时） ── */}
          {active && (
            <div className="glass-panel space-y-3 p-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">{t('management.dream.listTitle')}</h3>
                <span className="text-[10px] text-muted-foreground">
                  {t('management.dream.listTotal', { count: total })}
                </span>
              </div>

              {listError ? (
                <p className="py-6 text-center text-xs text-red-400">
                  {t('management.dream.listLoadFailed')}
                </p>
              ) : sessionGroups.length === 0 ? (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  {t('management.dream.listEmpty')}
                </p>
              ) : (
                <div className="space-y-4">
                  {sessionGroups.map(([sessionId, entries]) => (
                    <div key={sessionId} className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <p className="text-[10px] text-muted-foreground">
                          {t('management.dream.sessionTitle')} · {sessionId}
                        </p>
                        <button
                          type="button"
                          onClick={() => void handleClearSession(sessionId)}
                          disabled={!!busyAction}
                          className="flex items-center gap-1 rounded border border-[var(--glass-border)] px-2 py-1 text-[10px] text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                        >
                          <Trash2 className="h-3 w-3" />
                          {t('management.dream.clearSession')}
                        </button>
                      </div>
                      <div className="space-y-2">
                        {entries.map((item) => {
                          const meta = decisionMeta(item.decision);
                          return (
                            <div
                              key={item.id}
                              className="rounded-lg border border-[var(--glass-border)]/60 p-3"
                            >
                              <p className="text-sm leading-relaxed">{item.candidate_content}</p>
                              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                                <span
                                  className={cn(
                                    'rounded px-1.5 py-0.5 font-medium',
                                    meta.cls,
                                  )}
                                >
                                  {t(`management.dream.decision.${item.decision}`)}
                                </span>
                                <span className="tabular-nums">
                                  {t('management.dream.lucidity')}:{' '}
                                  {Math.round((item.lucidity_score ?? 0) * 100)}%
                                </span>
                                <span>
                                  {t('management.dream.associatedMemories')}:{' '}
                                  {item.associated_memories?.length ?? 0}
                                </span>
                                <span>
                                  {t('management.dream.associatedEntities')}:{' '}
                                  {item.associated_entities?.length ?? 0}
                                </span>
                              </div>
                              {item.decision === 'pending' && (
                                <div className="mt-2 flex gap-2">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      void handleAction('confirm', () =>
                                        dreamApi.confirm(item.id),
                                      )
                                    }
                                    disabled={!!busyAction}
                                    className="flex items-center gap-1 rounded-lg bg-emerald-500/15 px-2.5 py-1 text-[10px] font-medium text-emerald-400 transition-colors hover:bg-emerald-500/25 disabled:opacity-50"
                                  >
                                    <Check className="h-3 w-3" />
                                    {t('management.dream.confirm')}
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => void handleReject(item.id)}
                                    disabled={!!busyAction}
                                    className="flex items-center gap-1 rounded-lg bg-red-500/15 px-2.5 py-1 text-[10px] font-medium text-red-400 transition-colors hover:bg-red-500/25 disabled:opacity-50"
                                  >
                                    <X className="h-3 w-3" />
                                    {t('management.dream.reject')}
                                  </button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── 配置编辑区 ── */}
          <div className="glass-panel space-y-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{t('management.dream.configTitle')}</h3>
              <div className="flex items-center gap-2">
                {saved && <span className="text-[10px] text-emerald-400">{t('management.dream.saved')}</span>}
                <button
                  type="button"
                  onClick={() => void handleSaveConfig()}
                  disabled={!draft || !!busyAction}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
                >
                  <Save className="h-3.5 w-3.5" />
                  {t('management.dream.save')}
                </button>
              </div>
            </div>

            {!draft ? (
              <p className="text-xs text-muted-foreground">{t('management.dream.configLoadFailed')}</p>
            ) : (
              <div className="space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  <CheckboxField
                    label={t('management.dream.field.enabled')}
                    checked={draft.enabled}
                    onChange={(v) => updateDraft({ enabled: v })}
                    testId="dream-config-enabled"
                  />
                  <TextField
                    label={t('management.dream.field.model')}
                    value={draft.model}
                    onChange={(v) => updateDraft({ model: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.dreamTemperature')}
                    value={draft.dream_temperature}
                    step={0.1}
                    onChange={(v) => updateDraft({ dream_temperature: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.candidatesPerSession')}
                    value={draft.candidates_per_session}
                    step={1}
                    onChange={(v) => updateDraft({ candidates_per_session: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.materialWindowDays')}
                    value={draft.material_window_days}
                    step={1}
                    onChange={(v) => updateDraft({ material_window_days: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.maxMaterialItems')}
                    value={draft.max_material_items}
                    step={1}
                    onChange={(v) => updateDraft({ max_material_items: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.minLucidity')}
                    value={draft.min_lucidity}
                    step={0.1}
                    onChange={(v) => updateDraft({ min_lucidity: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.dreamTtlHours')}
                    value={draft.dream_ttl_hours}
                    step={1}
                    onChange={(v) => updateDraft({ dream_ttl_hours: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.purgeThreshold')}
                    value={draft.purge_threshold}
                    step={0.1}
                    onChange={(v) => updateDraft({ purge_threshold: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.confirmedImportance')}
                    value={draft.confirmed_importance}
                    step={0.1}
                    onChange={(v) => updateDraft({ confirmed_importance: v })}
                  />
                  <CheckboxField
                    label={t('management.dream.field.surfaceOnWake')}
                    checked={draft.surface_on_wake}
                    onChange={(v) => updateDraft({ surface_on_wake: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.surfaceProbability')}
                    value={draft.surface_probability}
                    step={0.1}
                    onChange={(v) => updateDraft({ surface_probability: v })}
                  />
                  <NumberField
                    label={t('management.dream.field.maxSurfacePerDay')}
                    value={draft.max_surface_per_day}
                    step={1}
                    onChange={(v) => updateDraft({ max_surface_per_day: v })}
                  />
                  <TextField
                    label={t('management.dream.field.wakeTime')}
                    value={draft.schedule.wake_time}
                    onChange={(v) => updateSchedule({ wake_time: v })}
                  />
                  <TextField
                    label={t('management.dream.field.sleepTime')}
                    value={draft.schedule.sleep_time}
                    onChange={(v) => updateSchedule({ sleep_time: v })}
                  />
                </div>
                {actionError && (
                  <p className="text-xs text-red-400">{t('management.dream.actionFailed')}</p>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
