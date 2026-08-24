/**
 * 管理面页（T22）
 *
 * CX-A 管理面最小可视化：
 * - 实例概览卡（instance_id / node_name / cluster 块）
 * - 能力开关（manifest.capabilities 布尔徽章）
 * - 清单卡（agents / plugins / models）
 * - 控制卡：选 target+action，POST /api/admin/control（带随机 request_id）
 * - 管理审计列表（GET /api/admin/audit）
 *
 * 数据全部来自 adminApi。降级口径：
 * - fetchManifest 抛错：网络错误（无法连接）→ 全页错误态 + 重试；
 *   HTTP 错误（503/失败）→ admin 未启用「未启用」徽章 + 引导提示
 * - status / audit 独立容错，失败不影响主展示
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Ban, Cpu, ListChecks, RefreshCw, Send, ShieldCheck, Server } from 'lucide-react';
import { adminApi } from '@/api/clients/admin';
import type {
  AdminControlResult,
  AdminManifest,
  AdminStatus,
  AdminAuditEntry,
} from '@/api/clients/admin';
import { Button, Badge, Card, CardBody, CardHeader } from '@/components/ui-v2';

const AUDIT_PAGE_SIZE = 50;

/** 归一化错误中"无法连接服务器"即网络/后端离线错误，其余（403/404/503 等）视为未启用 */
function isNetworkError(err: unknown): boolean {
  return err instanceof Error && err.message.includes('无法连接到服务器');
}

/** 能力开关按 key 排序，保证展示稳定 */
function sortedEntries(
  cap?: Record<string, boolean>,
): Array<[string, boolean]> {
  return Object.entries(cap ?? {}).sort(([a], [b]) => a.localeCompare(b));
}

export default function AdminPage() {
  const { t } = useTranslation();
  const [manifest, setManifest] = useState<AdminManifest | null>(null);
  const [statusData, setStatusData] = useState<AdminStatus | null>(null);
  const [auditItems, setAuditItems] = useState<AdminAuditEntry[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditError, setAuditError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [disabled, setDisabled] = useState(false);

  // 控制表单
  const [target, setTarget] = useState('instance');
  const [action, setAction] = useState('reload');
  const [busy, setBusy] = useState(false);
  const [controlResult, setControlResult] = useState<AdminControlResult | null>(null);
  const [controlError, setControlError] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    setDisabled(false);
    setControlError(false);
    try {
      const man = await adminApi.fetchManifest();
      setManifest(man);
      const [statusData, auditPage] = await Promise.all([
        adminApi.fetchStatus(),
        adminApi.fetchAudit({ limit: AUDIT_PAGE_SIZE, offset: 0 }),
      ]);
      setStatusData(statusData ?? null);
      if (auditPage) {
        setAuditItems(auditPage.items ?? []);
        setAuditTotal(auditPage.total ?? 0);
        setAuditError(false);
      } else {
        setAuditError(true);
      }
    } catch (err) {
      console.error('Admin load failed:', err);
      if (isNetworkError(err)) {
        setLoadError(true);
      } else {
        setDisabled(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 目标下拉候选：instance + agents + plugins（兼容字符串或含 name 的对象）
  const targetOptions = useCallback((): string[] => {
    const list: string[] = ['instance'];
    const push = (items: unknown[] | undefined) => {
      if (!items) return;
      for (const item of items) {
        if (typeof item === 'string') {
          if (!list.includes(item)) list.push(item);
        } else if (item && typeof item === 'object') {
          const name = (item as { name?: unknown }).name;
          if (typeof name === 'string' && !list.includes(name)) list.push(name);
        }
      }
    };
    push(manifest?.agents);
    push(manifest?.plugins);
    return list;
  }, [manifest]);

  const actionOptions = manifest?.control_actions?.length
    ? manifest.control_actions
    : ['reload', 'restart', 'pause', 'resume', 'healthcheck'];

  const handleSubmitControl = async () => {
    if (busy) return;
    setBusy(true);
    setControlError(false);
    setControlResult(null);
    try {
      const res = await adminApi.postControl({
        action,
        target,
        request_id: Math.random().toString(36).slice(2),
      });
      setControlResult(res);
      const auditPage = await adminApi.fetchAudit({ limit: AUDIT_PAGE_SIZE, offset: 0 });
      if (auditPage) {
        setAuditItems(auditPage.items ?? []);
        setAuditTotal(auditPage.total ?? 0);
      }
    } catch (err) {
      console.error('Admin control failed:', err);
      setControlError(true);
    } finally {
      setBusy(false);
    }
  };

  const capabilities = statusData?.capabilities ?? manifest?.capabilities;
  const cluster = manifest?.cluster;

  if (isLoading) {
    return (
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('common.loading')}
        </div>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="glass-panel space-y-3 p-8 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-red-400" />
          <p className="text-sm text-red-400">{t('management.common.loadFailed')}</p>
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            {t('management.common.retry')}
          </Button>
        </div>
      </div>
    );
  }

  if (disabled || !manifest) {
    return (
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">{t('management.admin.subtitle')}</p>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => void load()}
          >
            {t('management.admin.refresh')}
          </Button>
        </div>
        <Card>
          <CardBody className="flex items-center gap-3">
            <Ban className="h-5 w-5 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <p className="text-sm font-medium">{t('management.admin.disabledTitle')}</p>
              <p className="text-xs text-muted-foreground">
                {t('management.admin.disabledHint')}
              </p>
            </div>
          </CardBody>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.admin.subtitle')}</p>
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void load()}
        >
          {t('management.admin.refresh')}
        </Button>
      </div>

      {/* ── 实例概览 ── */}
      <Card>
        <CardHeader className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Server className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.admin.overviewTitle')}</h3>
          </div>
          {cluster ? (
            <Badge variant={cluster.enabled ? 'success' : 'secondary'} size="sm">
              {cluster.enabled
                ? t('management.admin.clusterEnabledOn')
                : t('management.admin.clusterEnabledOff')}
            </Badge>
          ) : null}
        </CardHeader>
        <CardBody className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.admin.instanceId')}</p>
            <p className="mt-0.5 truncate text-sm font-medium">
              {manifest.instance_id || t('management.admin.emptyValue')}
            </p>
          </div>
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.admin.nodeName')}</p>
            <p className="mt-0.5 truncate text-sm font-medium">
              {manifest.node_name || t('management.admin.emptyValue')}
            </p>
          </div>
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.admin.role')}</p>
            <p className="mt-0.5 truncate text-sm font-medium">
              {cluster?.role || t('management.admin.emptyValue')}
            </p>
          </div>
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.admin.epoch')}</p>
            <p className="mt-0.5 truncate text-sm font-medium tabular-nums">
              {cluster?.epoch != null ? String(cluster.epoch) : t('management.admin.emptyValue')}
            </p>
          </div>
        </CardBody>
      </Card>

      {/* ── 能力开关 ── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.admin.capabilitiesTitle')}</h3>
          </div>
        </CardHeader>
        <CardBody>
          {capabilities && sortedEntries(capabilities).length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {sortedEntries(capabilities).map(([key, on]) => (
                <Badge key={key} variant={on ? 'success' : 'secondary'} size="sm">
                  {key}
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">{t('management.admin.emptyList')}</p>
          )}
        </CardBody>
      </Card>

      {/* ── 清单：agents / plugins / models ── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.admin.inventoryTitle')}</h3>
          </div>
        </CardHeader>
        <CardBody className="space-y-4">
          {[
            { label: t('management.admin.agentsLabel'), items: manifest.agents },
            { label: t('management.admin.pluginsLabel'), items: manifest.plugins },
            { label: t('management.admin.modelsLabel'), items: manifest.models },
          ].map(({ label, items }) => (
            <div key={label}>
              <p className="mb-2 text-[10px] text-muted-foreground">{label}</p>
              {items && items.length > 0 ? (
                <div className="flex flex-wrap gap-1.5">
                  {(items as unknown[]).map((item, i) => (
                    <span
                      key={i}
                      className="rounded bg-[rgba(255,255,255,0.06)] px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      {typeof item === 'string'
                        ? item
                        : String((item as { name?: unknown })?.name ?? item ?? '')}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">{t('management.admin.emptyList')}</p>
              )}
            </div>
          ))}
        </CardBody>
      </Card>

      {/* ── 控制入口 ── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Cpu className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.admin.controlTitle')}</h3>
          </div>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="space-y-1 text-xs text-muted-foreground">
              <span className="block">{t('management.admin.targetLabel')}</span>
              <select
                value={target}
                onChange={(e) => setTarget(e.target.value)}
                className="rounded-lg border border-[var(--glass-border)] bg-transparent px-3 py-1.5 text-sm"
              >
                {targetOptions().map((opt) => (
                  <option key={opt} value={opt} className="bg-[#1a1d26]">
                    {opt}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              <span className="block">{t('management.admin.actionLabel')}</span>
              <select
                value={action}
                onChange={(e) => setAction(e.target.value)}
                className="rounded-lg border border-[var(--glass-border)] bg-transparent px-3 py-1.5 text-sm"
              >
                {actionOptions.map((a) => (
                  <option key={a} value={a} className="bg-[#1a1d26]">
                    {a}
                  </option>
                ))}
              </select>
            </label>
            <Button
              size="sm"
              loading={busy}
              icon={<Send className="h-3.5 w-3.5" />}
              onClick={() => void handleSubmitControl()}
            >
              {t('management.admin.triggerButton')}
            </Button>
          </div>
          {controlResult && (
            <p className="text-xs text-emerald-400">
              {t('management.admin.controlSuccess', { status: controlResult.status })}
            </p>
          )}
          {controlError && (
            <p className="text-xs text-red-400">{t('management.admin.controlFailed')}</p>
          )}
        </CardBody>
      </Card>

      {/* ── 管理审计 ── */}
      <Card>
        <CardHeader className="flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">{t('management.admin.auditTitle')}</h3>
          <span className="text-[10px] text-muted-foreground">
            {t('management.admin.auditTotal', { count: auditTotal })}
          </span>
        </CardHeader>
        <CardBody>
          {auditError ? (
            <p className="py-4 text-center text-xs text-red-400">
              {t('management.admin.auditLoadFailed')}
            </p>
          ) : auditItems.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t('management.admin.auditEmpty')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[var(--glass-border)] text-muted-foreground">
                    <th className="px-3 py-2 font-medium">{t('management.admin.colTimestamp')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.admin.colActor')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.admin.colAction')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.admin.colTarget')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.admin.colSummary')}</th>
                  </tr>
                </thead>
                <tbody>
                  {auditItems.map((item, i) => (
                    <tr
                      key={item.id || `${item.timestamp}-${item.action}-${i}`}
                      className="border-b border-[var(--glass-border)]/50 last:border-0"
                    >
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                        {new Date(item.timestamp).toLocaleString()}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {item.actor || t('management.admin.emptyValue')}
                      </td>
                      <td className="px-3 py-2 font-medium">{item.action}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {item.target || t('management.admin.emptyValue')}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {item.summary || t('management.admin.emptyValue')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}