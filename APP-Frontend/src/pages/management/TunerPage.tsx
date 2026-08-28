/**
 * 微调 / 进化实验室页（TunerPage）
 *
 * 对接 server/api/routers/tuner.py（CXO-Tuner 自适应微调）：
 * - 数据集统计（GET /api/v1/tuner/stats，覆盖 total/source_breakdown/positive_ratio/negative_ratio/anchor_count）
 * - 触发训练（POST /api/v1/tuner/train/trigger）→ 轮询训练状态（GET /api/v1/tuner/train/status）
 * - 适配器列表 / 应用 / 删除（GET/POST/DELETE /api/v1/tuner/adapters[/{id}]）
 *
 * 降级口径：getStats 返回 null 即 Tuner 离线 → 概览卡展示「Tuner 未在线」提示；
 * 所有触发器（trigger/applyAdapter/deleteAdapter）错误归一化后一律展示在页面内，不抛全局。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  CheckCircle2,
  Database,
  FlaskConical,
  Layers,
  Play,
  RefreshCw,
  Trash2,
} from 'lucide-react';
import { Badge, Button, Card, CardBody, CardHeader, Input } from '@/components/ui-v2';
import { tunerApi } from '@/api/clients/tuner';
import type { TunerAdapter, TunerTrainStatus } from '@/api/clients/tuner';

/** 训练完成的终止态：命中其一即自动停止轮询 */
const DONE_STATUS: ReadonlySet<string> = new Set([
  'completed',
  'done',
  'finished',
  'failed',
  'error',
  'cancelled',
]);

/** 归一化错误文本：非 Error 统一字符串化 */
function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function TunerPage() {
  const { t } = useTranslation();

  // ── 概览数据 ──
  const [stats, setStats] = useState<{ total: number; positive_ratio: number; negative_ratio: number; anchor_count: number; source_breakdown: Record<string, number> } | null>(null);
  const [statsLoaded, setStatsLoaded] = useState(false);

  // ── 训练参数与任务状态 ──
  const [epochs, setEpochs] = useState(1);
  const [sampleRatio, setSampleRatio] = useState(1.0);
  const [jobId, setJobId] = useState<string | null>(null);
  const [trainStatus, setTrainStatus] = useState<TunerTrainStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [polling, setPolling] = useState(false);
  const [trainError, setTrainError] = useState<string | null>(null);

  // ── 适配器列表与操作 ──
  const [adapters, setAdapters] = useState<TunerAdapter[]>([]);
  const [adaptersLoaded, setAdaptersLoaded] = useState(false);
  const [adaptersOffline, setAdaptersOffline] = useState(false);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [adapterMsg, setAdapterMsg] = useState<{
    id: string;
    kind: 'success' | 'error';
    text: string;
  } | null>(null);

  /** 加载适配器列表；null 表示 Tuner 离线（degraded/网络失败），驱动列表区展示离线提示 */
  const loadAdapters = useCallback(async () => {
    const list = await tunerApi.listAdapters();
    setAdaptersOffline(list === null);
    setAdapters(list ?? []);
    setAdaptersLoaded(true);
  }, []);

  /** 首次加载统计与适配器列表 */
  const loadAll = useCallback(async () => {
    const s = await tunerApi.getStats();
    setStats(s);
    setStatsLoaded(true);
    await loadAdapters();
  }, [loadAdapters]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  /** 训练状态轮询：每 5s 拉取一次，训练完成/失败自动停止 */
  useEffect(() => {
    if (!polling || !jobId) return;
    let cancelled = false;

    const tick = async () => {
      const st = await tunerApi.getTrainStatus(jobId);
      if (cancelled) return;
      if (st) {
        setTrainStatus(st);
        if (DONE_STATUS.has(st.status ?? '')) setPolling(false);
      }
    };

    void tick();
    const timer = setInterval(() => void tick(), 5000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [polling, jobId]);

  /** 触发训练：成功后尝试立即抓取一次状态并开启轮询 */
  const handleStartTrain = async () => {
    setBusy(true);
    setTrainError(null);
    setTrainStatus(null);
    setJobId(null);
    try {
      const res = await tunerApi.trigger(epochs, sampleRatio);
      const id = res?.job_id ?? null;
      setJobId(id);
      if (id) {
        setPolling(true);
        const st = await tunerApi.getTrainStatus(id);
        if (st) setTrainStatus(st);
      } else {
        setTrainStatus(res);
      }
    } catch (e) {
      console.error('tuner trigger failed:', e);
      setTrainError(messageOf(e));
    } finally {
      setBusy(false);
    }
  };

  /** 应用适配器 */
  const handleApply = async (id: string) => {
    setApplyingId(id);
    setAdapterMsg(null);
    try {
      const res = await tunerApi.applyAdapter(id);
      const detail = res?.detail;
      setAdapterMsg({
        id,
        kind: 'success',
        text: detail
          ? `${t('management.tuner.applySuccess')} · ${detail}`
          : t('management.tuner.applySuccess'),
      });
    } catch (e) {
      console.error('tuner apply failed:', e);
      setAdapterMsg({ id, kind: 'error', text: `${t('management.tuner.applyFailed')}：${messageOf(e)}` });
    } finally {
      setApplyingId(null);
    }
  };

  /** 删除适配器：成功后刷新列表 */
  const handleDelete = async (id: string) => {
    setDeletingId(id);
    setAdapterMsg(null);
    try {
      await tunerApi.deleteAdapter(id);
      setAdapterMsg({ id, kind: 'success', text: t('management.tuner.deleteSuccess') });
      await loadAdapters();
    } catch (e) {
      console.error('tuner delete failed:', e);
      setAdapterMsg({ id, kind: 'error', text: `${t('management.tuner.deleteFailed')}：${messageOf(e)}` });
    } finally {
      setDeletingId(null);
    }
  };

  const lastLoss =
    trainStatus?.loss_curve && trainStatus.loss_curve.length > 0
      ? trainStatus.loss_curve[trainStatus.loss_curve.length - 1]
      : undefined;

  const isDone = DONE_STATUS.has(trainStatus?.status ?? '');

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.tuner.subtitle')}</p>
      </div>

      {/* ── 概览卡：数据集统计 ── */}
      <Card>
        <CardHeader className="flex items-center gap-2">
          <Database className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">{t('management.tuner.statsTitle')}</h3>
        </CardHeader>
        <CardBody>
          {statsLoaded && stats === null ? (
            <div className="flex items-center gap-3">
              <AlertCircle className="h-5 w-5 shrink-0 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{t('management.tuner.offline')}</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                <p className="text-[10px] text-muted-foreground">{t('management.tuner.statsTotal')}</p>
                <p className="mt-0.5 text-sm font-medium tabular-nums">
                  {stats?.total ?? 0}
                </p>
              </div>
              <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                <p className="text-[10px] text-muted-foreground">{t('management.tuner.statsPositive')}</p>
                <p className="mt-0.5 text-sm font-medium tabular-nums">
                  {((stats?.positive_ratio ?? 0) * 100).toFixed(1)}%
                </p>
              </div>
              <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                <p className="text-[10px] text-muted-foreground">{t('management.tuner.statsNegative')}</p>
                <p className="mt-0.5 text-sm font-medium tabular-nums">
                  {((stats?.negative_ratio ?? 0) * 100).toFixed(1)}%
                </p>
              </div>
              <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
                <p className="text-[10px] text-muted-foreground">{t('management.tuner.statsAnchors')}</p>
                <p className="mt-0.5 text-sm font-medium tabular-nums">
                  {stats?.anchor_count ?? 0}
                </p>
              </div>
            </div>
          )}
          {statsLoaded && stats && Object.keys(stats.source_breakdown ?? {}).length > 0 && (
            <div className="mt-3 space-y-1.5">
              <p className="text-xs font-medium text-[var(--text-secondary)]">
                {t('management.tuner.statsSources')}
              </p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(stats.source_breakdown ?? {}).map(([k, v]) => (
                  <Badge key={k} variant="secondary" size="sm">
                    {k}: {v}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* ── 训练卡 ── */}
      <Card>
        <CardHeader className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">{t('management.tuner.trainTitle')}</h3>
        </CardHeader>
        <CardBody className="space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Input
              label={t('management.tuner.epochs')}
              type="number"
              min={1}
              value={epochs}
              onChange={(e) => setEpochs(Number(e.target.value))}
            />
            <div>
              <label className="mb-1.5 block text-sm font-medium text-[var(--text-secondary)]">
                {t('management.tuner.sampleRatio')}
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={sampleRatio}
                  onChange={(e) => setSampleRatio(Number(e.target.value))}
                  className="w-full accent-[var(--color-primary)]"
                />
                <span className="w-12 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {sampleRatio.toFixed(2)}
                </span>
              </div>
            </div>
          </div>

          {trainError && <p className="text-xs text-red-400">{trainError}</p>}

          <div className="flex items-center gap-3">
            <Button onClick={() => void handleStartTrain()} loading={busy} icon={<Play className="h-4 w-4" />}>
              {t('management.tuner.startTrain')}
            </Button>
            {polling && (
              <Button size="sm" variant="secondary" onClick={() => setPolling(false)}>
                {t('management.tuner.stopPolling')}
              </Button>
            )}
          </div>

          {trainStatus && (
            <div className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                {jobId && (
                  <Badge variant="secondary" size="sm">
                    {t('management.tuner.jobId')}: {jobId}
                  </Badge>
                )}
                {trainStatus.status ? (
                  <Badge variant={isDone ? 'success' : 'warning'} size="sm">
                    {trainStatus.status}
                  </Badge>
                ) : null}
                {lastLoss !== undefined && !Number.isNaN(lastLoss) && (
                  <span className="text-muted-foreground">
                    Loss: {lastLoss.toFixed(4)}
                  </span>
                )}
              </div>

              <div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">{t('management.tuner.progress')}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {Math.round((trainStatus.progress ?? 0) * 100)}%
                  </span>
                </div>
                <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]">
                  <div
                    className="h-full rounded-full bg-emerald-400 transition-all"
                    style={{
                      width: `${Math.max(0, Math.min(100, (trainStatus.progress ?? 0) * 100))}%`,
                    }}
                  />
                </div>
              </div>

              {trainStatus.memory_usage_mb != null && (
                <p className="text-xs text-muted-foreground">
                  {t('management.tuner.memory')}: {trainStatus.memory_usage_mb} MB
                </p>
              )}
              {trainStatus.error && <p className="text-xs text-red-400">{trainStatus.error}</p>}
              {isDone && (
                <p className="flex items-center gap-1.5 text-xs text-emerald-400">
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  {t('management.tuner.trainDone')}
                </p>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* ── 适配器列表 ── */}
      <Card>
        <CardHeader className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.tuner.adaptersTitle')}</h3>
          </div>
          <Button variant="ghost" size="sm" onClick={() => void loadAdapters()} icon={<RefreshCw className="h-3.5 w-3.5" />}>
            {t('management.tuner.refresh')}
          </Button>
        </CardHeader>
        <CardBody>
          {adaptersLoaded && adaptersOffline ? (
            <div className="flex items-center gap-3 py-4">
              <AlertCircle className="h-5 w-5 shrink-0 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">{t('management.tuner.offline')}</p>
            </div>
          ) : adaptersLoaded && adapters.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t('management.tuner.noAdapters')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[var(--glass-border)] text-muted-foreground">
                    <th className="px-3 py-2 font-medium">{t('management.tuner.colName')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.tuner.colBase')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.tuner.colScene')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.tuner.colStatus')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.tuner.colCreated')}</th>
                    <th className="px-3 py-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {adapters.map((a) => (
                    <tr
                      key={a.id}
                      className="border-b border-[var(--glass-border)]/50 last:border-0"
                    >
                      <td className="px-3 py-2 font-medium">{a.name || a.id || '—'}</td>
                      <td className="px-3 py-2 text-muted-foreground">{a.base_model || '—'}</td>
                      <td className="px-3 py-2 text-muted-foreground">{a.scene || '—'}</td>
                      <td className="px-3 py-2">
                        <Badge variant="secondary" size="sm">
                          {a.status || '—'}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {a.created_at ? new Date(a.created_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center justify-end gap-2">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() => void handleApply(a.id)}
                            loading={applyingId === a.id}
                          >
                            {t('management.tuner.apply')}
                          </Button>
                          <Button
                            size="sm"
                            variant="danger"
                            onClick={() => void handleDelete(a.id)}
                            loading={deletingId === a.id}
                            icon={<Trash2 className="h-3.5 w-3.5" />}
                          >
                            {t('management.tuner.delete')}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {adapterMsg && (
            <p
              className={
                adapterMsg.kind === 'success'
                  ? 'mt-3 flex items-center gap-1.5 text-xs text-emerald-400'
                  : 'mt-3 flex items-center gap-1.5 text-xs text-red-400'
              }
            >
              {adapterMsg.kind === 'success' ? (
                <CheckCircle2 className="h-3.5 w-3.5" />
              ) : (
                <AlertCircle className="h-3.5 w-3.5" />
              )}
              {adapterMsg.text}
            </p>
          )}
        </CardBody>
      </Card>
    </div>
  );
}