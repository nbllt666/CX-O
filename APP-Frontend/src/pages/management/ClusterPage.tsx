/**
 * 哨兵集群页（T23）
 *
 * CX-A 哨兵集群最小可视化：
 * - 集群状态卡（node_id / role / epoch / enabled / peers）
 * - 集群拓扑表（GET /api/cluster/topology：node_id/endpoint/role/state/heartbeat）
 * - 备份单元同步进度（GET /api/cluster/sync：units）
 * - 故障转移日志（复用 /admin/audit 中 action 含 failover 的项）
 *
 * 数据来自 clusterApi / adminApi。降级口径：
 * - fetchState 抛错：网络错误 → 全页错误态 + 重试；HTTP 错误（503/失败）→ 未启用徽章
 * - state.enabled === false → 未启用徽章
 * - topology / sync / failover 独立容错，失败不影响主展示
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, Ban, GitCompare, Layers, RefreshCw, ServerCog, Activity } from 'lucide-react';
import { clusterApi } from '@/api/clients/cluster';
import type {
  ClusterNodeInfo,
  ClusterState,
  ClusterSyncUnit,
} from '@/api/clients/cluster';
import { adminApi } from '@/api/clients/admin';
import type { AdminAuditEntry } from '@/api/clients/admin';
import { Badge, Button, Card, CardBody, CardHeader } from '@/components/ui-v2';

const AUDIT_PAGE_SIZE = 50;

/** 归一化错误中"无法连接服务器"即网络/后端离线错误，其余（403/404/503 等）视为未启用 */
function isNetworkError(err: unknown): boolean {
  return err instanceof Error && err.message.includes('无法连接到服务器');
}

export default function ClusterPage() {
  const { t } = useTranslation();
  const [state, setState] = useState<ClusterState | null>(null);
  const [topology, setTopology] = useState<ClusterNodeInfo[]>([]);
  const [topologyError, setTopologyError] = useState(false);
  const [syncUnits, setSyncUnits] = useState<ClusterSyncUnit[]>([]);
  const [syncError, setSyncError] = useState(false);
  const [failoverItems, setFailoverItems] = useState<AdminAuditEntry[]>([]);
  const [failoverError, setFailoverError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [disabled, setDisabled] = useState(false);

  /** 独立加载故障转移日志（复用 /admin/audit，过滤 action 含 failover） */
  const loadFailover = useCallback(async () => {
    const page = await adminApi.fetchAudit({ limit: AUDIT_PAGE_SIZE, offset: 0 });
    if (page === null) {
      setFailoverError(true);
      return;
    }
    setFailoverError(false);
    const filtered = (page.items ?? []).filter((item) =>
      item.action?.toLowerCase().includes('failover'),
    );
    setFailoverItems(filtered);
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    setDisabled(false);
    try {
      const st = await clusterApi.fetchState();
      setState(st);

      const [topoPage, syncInfo] = await Promise.all([
        clusterApi.fetchTopology(),
        clusterApi.fetchSync(),
      ]);
      if (topoPage) {
        setTopology(topoPage.topology ?? []);
        setTopologyError(false);
      } else {
        setTopology([]);
        setTopologyError(true);
      }
      if (syncInfo) {
        setSyncUnits(syncInfo.sync?.units ?? []);
        setSyncError(false);
      } else {
        setSyncError(true);
      }
      await loadFailover();
    } catch (err) {
      console.error('Cluster load failed:', err);
      if (isNetworkError(err)) {
        setLoadError(true);
      } else {
        setDisabled(true);
      }
    } finally {
      setIsLoading(false);
    }
  }, [loadFailover]);

  useEffect(() => {
    void load();
  }, [load]);

  const clusterState = state?.state;

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

  if (disabled || !clusterState || clusterState.enabled === false) {
    return (
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-muted-foreground">{t('management.cluster.subtitle')}</p>
          <Button
            variant="secondary"
            size="sm"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            onClick={() => void load()}
          >
            {t('management.cluster.refresh')}
          </Button>
        </div>
        <Card>
          <CardBody className="flex items-center gap-3">
            <Ban className="h-5 w-5 shrink-0 text-muted-foreground" />
            <div className="min-w-0">
              <p className="text-sm font-medium">{t('management.cluster.disabledTitle')}</p>
              <p className="text-xs text-muted-foreground">
                {t('management.cluster.disabledHint')}
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
        <p className="text-sm text-muted-foreground">{t('management.cluster.subtitle')}</p>
        <Button
          variant="secondary"
          size="sm"
          icon={<RefreshCw className="h-3.5 w-3.5" />}
          onClick={() => void load()}
        >
          {t('management.cluster.refresh')}
        </Button>
      </div>

      {/* ── 集群状态 ── */}
      <Card>
        <CardHeader className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ServerCog className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.cluster.overviewTitle')}</h3>
          </div>
          <Badge variant={clusterState.enabled ? 'success' : 'secondary'} size="sm">
            {clusterState.enabled
              ? t('management.cluster.enabledOn')
              : t('management.cluster.enabledOff')}
          </Badge>
        </CardHeader>
        <CardBody className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.cluster.nodeId')}</p>
            <p className="mt-0.5 truncate text-sm font-medium">
              {clusterState.node_id || t('management.cluster.emptyValue')}
            </p>
          </div>
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.cluster.role')}</p>
            <p className="mt-0.5 truncate text-sm font-medium">
              {clusterState.role || t('management.cluster.emptyValue')}
            </p>
          </div>
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.cluster.epoch')}</p>
            <p className="mt-0.5 truncate text-sm font-medium tabular-nums">
              {clusterState.epoch != null
                ? String(clusterState.epoch)
                : t('management.cluster.emptyValue')}
            </p>
          </div>
          <div className="rounded-lg bg-[rgba(255,255,255,0.04)] p-3">
            <p className="text-[10px] text-muted-foreground">{t('management.cluster.peers')}</p>
            <p className="mt-0.5 truncate text-sm font-medium">
              {(clusterState.peers ?? []).length
                ? clusterState.peers!.join(', ')
                : t('management.cluster.emptyValue')}
            </p>
          </div>
        </CardBody>
      </Card>

      {/* ── 集群拓扑 ── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Layers className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.cluster.topologyTitle')}</h3>
          </div>
        </CardHeader>
        <CardBody>
          {topologyError ? (
            <p className="py-4 text-center text-xs text-red-400">
              {t('management.cluster.topologyLoadFailed')}
            </p>
          ) : topology.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t('management.cluster.topologyEmpty')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[var(--glass-border)] text-muted-foreground">
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colNode')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colEndpoint')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colRole')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colState')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colHeartbeat')}</th>
                  </tr>
                </thead>
                <tbody>
                  {topology.map((node, i) => (
                    <tr
                      key={node.node_id || `${node.endpoint}-${i}`}
                      className="border-b border-[var(--glass-border)]/50 last:border-0"
                    >
                      <td className="px-3 py-2 font-medium">
                        {node.node_id || t('management.cluster.emptyValue')}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">{node.endpoint}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {node.role || t('management.cluster.emptyValue')}
                      </td>
                      <td className="px-3 py-2">
                        <Badge
                          variant={node.state === 'online' ? 'success' : 'secondary'}
                          size="sm"
                        >
                          {node.state || t('management.cluster.emptyValue')}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {node.last_heartbeat
                          ? new Date(node.last_heartbeat).toLocaleString()
                          : t('management.cluster.emptyValue')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>

      {/* ── 备份单元同步 ── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.cluster.syncTitle')}</h3>
          </div>
        </CardHeader>
        <CardBody>
          {syncError ? (
            <p className="py-4 text-center text-xs text-red-400">
              {t('management.cluster.syncLoadFailed')}
            </p>
          ) : syncUnits.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t('management.cluster.syncEmpty')}
            </p>
          ) : (
            <div className="space-y-3">
              {syncUnits.map((unit, i) => {
                const total = unit.total ?? 0;
                const synced = unit.synced ?? 0;
                const pct = total > 0 ? Math.round((synced / total) * 100) : unit.progress ?? 0;
                return (
                  <div key={unit.name || i} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium">
                        {unit.name || t('management.cluster.emptyValue')}
                      </span>
                      {unit.status ? (
                        <Badge variant="secondary" size="sm">
                          {unit.status}
                        </Badge>
                      ) : (
                        <span className="tabular-nums text-muted-foreground">
                          {synced} / {total} · {pct}%
                        </span>
                      )}
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]">
                      <div
                        className="h-full rounded-full bg-emerald-400 transition-all"
                        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>

      {/* ── 故障转移日志 ── */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <GitCompare className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-semibold">{t('management.cluster.failoverTitle')}</h3>
          </div>
        </CardHeader>
        <CardBody>
          {failoverError ? (
            <p className="py-4 text-center text-xs text-red-400">
              {t('management.cluster.failoverLoadFailed')}
            </p>
          ) : failoverItems.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              {t('management.cluster.failoverEmpty')}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[var(--glass-border)] text-muted-foreground">
                    <th className="px-3 py-2 font-medium">
                      {t('management.cluster.colTimestamp')}
                    </th>
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colAction')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colTarget')}</th>
                    <th className="px-3 py-2 font-medium">{t('management.cluster.colSummary')}</th>
                  </tr>
                </thead>
                <tbody>
                  {failoverItems.map((item, i) => (
                    <tr
                      key={item.id || `${item.timestamp}-${item.action}-${i}`}
                      className="border-b border-[var(--glass-border)]/50 last:border-0"
                    >
                      <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                        {new Date(item.timestamp).toLocaleString()}
                      </td>
                      <td className="px-3 py-2 font-medium">{item.action}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {item.target || t('management.cluster.emptyValue')}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {item.summary || t('management.cluster.emptyValue')}
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