/**
 * 全局轻量 toast（D9 展示层）：cluster_event（仅切换/故障类，由 useWebSocket 过滤）与
 * autonomy_cost_alert 的右下角浮层。极简扁平风格（glass 面板 + 小图标 + 次级文案），
 * 不做管理界面风格；6s 自动消退，可手动关闭。
 *
 * 挂载点在 App.tsx 各主窗口分支（桌宠 / 弹幕 / 管理界面）；OBS /source/* 叠加页
 * 不挂载，避免污染采集画面。
 */
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Gauge, Network, X } from 'lucide-react';
import { useToastStore, type GlobalToastItem } from '@/store/toastStore';

/** 取 cluster 事件体内层 data（failover 的 from_node / role_changed 的 role 等） */
function eventInner(item: GlobalToastItem): Record<string, unknown> {
  return (item.data?.data as Record<string, unknown>) || {};
}

function ToastBody({ item }: { item: GlobalToastItem }) {
  const { t } = useTranslation();
  if (item.kind === 'cost') {
    const d = item.data || {};
    const ratio = `${Math.round(Number(d.usage_ratio || 0) * 100)}%`;
    return (
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{t('events.costAlertTitle')}</p>
        <p className="text-sm opacity-90">
          {t('events.costAlertMessage', {
            used: String(d.daily_used ?? '-'),
            limit: String(d.limit ?? '-'),
            ratio,
          })}
        </p>
      </div>
    );
  }
  const inner = eventInner(item);
  let message: string;
  switch (item.topic) {
    case 'cluster.failover_started':
      message = t('events.clusterFailoverStarted', { node: String(inner.from_node ?? '-') });
      break;
    case 'cluster.failover_completed':
      message = t('events.clusterFailoverCompleted');
      break;
    case 'cluster.node_left':
      message = t('events.clusterNodeLeft', {
        node: String(inner.node_id ?? inner.endpoint ?? '-'),
      });
      break;
    case 'cluster.role_changed':
      message = t('events.clusterRoleChanged', { role: String(inner.role ?? '-') });
      break;
    default:
      message = t('events.clusterGeneric', { topic: item.topic || '-' });
  }
  return (
    <div className="min-w-0 flex-1">
      <p className="text-sm font-medium">{t('events.clusterTitle')}</p>
      <p className="text-sm opacity-90">{message}</p>
    </div>
  );
}

export default function GlobalToasts() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  // 到期清扫（与 ChatPage alarm toast 同口径：单一清扫循环按 expireAt 批量移除）
  useEffect(() => {
    const timer = setInterval(() => {
      useToastStore.setState((state) => {
        if (state.toasts.length === 0) return state;
        const now = Date.now();
        const next = state.toasts.filter((item) => item.expireAt > now);
        return next.length === state.toasts.length ? state : { toasts: next };
      });
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 space-y-2">
      {toasts.map((item) => (
        <div
          key={item.id}
          className="pointer-events-auto flex max-w-sm items-start gap-2 rounded-lg border border-[var(--glass-border)] bg-[var(--glass-bg)] px-4 py-3 shadow-lg backdrop-blur-md"
        >
          {item.kind === 'cost' ? (
            <Gauge className="mt-0.5 h-5 w-5 shrink-0 text-amber-400" />
          ) : (
            <Network className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          )}
          <ToastBody item={item} />
          <button
            type="button"
            onClick={() => dismiss(item.id)}
            aria-label="dismiss"
            className="shrink-0 rounded p-0.5 text-muted-foreground transition-opacity hover:opacity-70"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
