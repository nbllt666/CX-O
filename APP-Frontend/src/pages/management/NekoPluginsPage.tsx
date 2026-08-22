/**
 * Neko 插件管理页
 * ============================================================================
 * 在 CX-O 管理界面中管理 neko 插件运行时：插件列表、插件商店、安装来源、
 * 实时日志与运行时设置五个 Tab。所有数据经渲染层兼容层（nekoApi）获取。
 * ============================================================================
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Cat,
  Download,
  ExternalLink,
  Info,
  List,
  Loader2,
  MessageCircle,
  Package,
  Play,
  Power,
  RefreshCw,
  RotateCw,
  Square,
  Store,
  Trash2,
  X,
} from 'lucide-react';
import { useNekoStore, subscribeNekoLogs } from '@/store/nekoStore';
import { nekoApi, pluginUiUrl, type NekoCatalogPlugin, type NekoPluginItem } from '@/api/clients/neko';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// 通用小组件
// ---------------------------------------------------------------------------

/** 简单延时（安装任务轮询等场景） */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 状态徽章 */
function StatusBadge({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span
      className={cn(
        'rounded px-1.5 py-0.5 text-[10px] font-medium',
        ok ? 'bg-emerald-500/15 text-emerald-400' : 'bg-[rgba(255,255,255,0.08)] text-muted-foreground',
      )}
    >
      {text}
    </span>
  );
}

/** 运行时头部：状态 + 启停 */
function RuntimeHeader() {
  const { t } = useTranslation();
  const { running, port, bridge, checking, startRuntime, stopRuntime, refreshStatus } = useNekoStore();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const handleToggle = useCallback(async () => {
    setBusy(true);
    setErr(null);
    const res = running ? await stopRuntime() : await startRuntime();
    if (!res.ok) setErr(res.error ?? '操作失败');
    setBusy(false);
  }, [running, startRuntime, stopRuntime]);

  return (
    <div className="glass-panel flex flex-wrap items-center gap-4 p-4">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
        <Cat className="h-5 w-5" />
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold">{t('management.neko.runtime.title')}</p>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <StatusBadge ok={running} text={running ? t('management.neko.runtime.running') : t('management.neko.runtime.stopped')} />
          {running && port && <span className="font-mono">127.0.0.1:{port}</span>}
          {running && bridge?.bridgeRunning && (
            <StatusBadge ok text={t('management.neko.runtime.bridge', { count: bridge.tools ?? 0 })} />
          )}
          {running && bridge && !bridge.bridgeRunning && (
            <StatusBadge ok={false} text={t('management.neko.runtime.bridgeOff')} />
          )}
        </div>
      </div>
      <div className="ml-auto flex items-center gap-2">
        {err && <span className="text-xs text-red-400">{err}</span>}
        <button
          type="button"
          onClick={() => void handleToggle()}
          disabled={busy || checking}
          className={cn(
            'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-opacity disabled:opacity-50',
            running ? 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]' : 'bg-primary text-primary-foreground hover:opacity-85',
          )}
        >
          <Power className="h-3.5 w-3.5" />
          {running ? t('management.neko.runtime.stop') : t('management.neko.runtime.start')}
        </button>
        <button
          type="button"
          onClick={() => void refreshStatus()}
          aria-label={t('management.neko.runtime.refresh')}
          className="rounded-lg border border-[var(--glass-border)] p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 插件列表 Tab
// ---------------------------------------------------------------------------
function PluginsTab() {
  const { t } = useTranslation();
  const { plugins, loadingPlugins, installed, refreshPlugins, pluginAction } = useNekoStore();
  const { port } = useNekoStore();
  const [uiPlugin, setUiPlugin] = useState<NekoPluginItem | null>(null);
  const [detail, setDetail] = useState<NekoPluginItem | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const installedIds = new Set(installed.map((p) => p.plugin_id));

  const run = async (action: 'start' | 'stop' | 'refresh' | 'reload', id: string) => {
    setBusy(`${id}:${action}`);
    try {
      await pluginAction(id, action);
    } catch (e) {
      console.error('plugin action failed', e);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void refreshPlugins()}
          aria-label={t('management.neko.plugins.refresh')}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('management.neko.plugins.refresh')}
        </button>
      </div>

      {loadingPlugins ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />
          {t('common.loading')}
        </div>
      ) : plugins.length === 0 ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('management.neko.plugins.empty')}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {plugins.map((plugin) => {
            const running = plugin.status === 'running' || plugin.status === 'active' || !!plugin.enabled;
            const isInstalled = installedIds.has(plugin.id);
            return (
              <div key={plugin.id} className="glass-panel flex flex-col gap-2 p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{plugin.name || plugin.id}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      <StatusBadge ok={running} text={running ? t('management.neko.plugins.running') : t('management.neko.plugins.stopped')} />
                      {isInstalled && <StatusBadge ok text={t('management.neko.plugins.market')} />}
                      {plugin.version && (
                        <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[10px] text-secondary">
                          {plugin.version}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      title={running ? t('management.neko.plugins.stop') : t('management.neko.plugins.start')}
                      onClick={() => void run(running ? 'stop' : 'start', plugin.id)}
                      disabled={busy === `${plugin.id}:${running ? 'stop' : 'start'}`}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground disabled:opacity-40"
                    >
                      {running ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                    </button>
                    <button
                      type="button"
                      title={t('management.neko.plugins.reload')}
                      onClick={() => void run('reload', plugin.id)}
                      disabled={busy === `${plugin.id}:reload`}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground disabled:opacity-40"
                    >
                      <RotateCw className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      title={t('management.neko.plugins.openUi')}
                      onClick={() => setUiPlugin(plugin)}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      title={t('management.neko.plugins.detail')}
                      onClick={() => setDetail(plugin)}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                    >
                      <Info className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>

                <p className="line-clamp-2 min-h-[1.25rem] text-xs text-muted-foreground">
                  {plugin.description || t('management.neko.plugins.noDescription')}
                </p>

                <p className="truncate border-t border-[var(--glass-border)] pt-2 font-mono text-[10px] text-muted-foreground/70">
                  {plugin.id}
                </p>
              </div>
            );
          })}
        </div>
      )}

      {uiPlugin && (
        <PluginUiModal
          title={String(uiPlugin.name || uiPlugin.id)}
          url={pluginUiUrl(port, `/plugin/${uiPlugin.id}/ui/`)}
          onClose={() => setUiPlugin(null)}
        />
      )}
      {detail && <PluginDetailDrawer plugin={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

/** 插件 UI iframe 弹窗 */
function PluginUiModal({ title, url, onClose }: { title: string; url: string; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6 backdrop-blur-sm">
      <div className="flex h-[85vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-[var(--glass-border)] bg-[#12121a]">
        <div className="flex items-center justify-between border-b border-[var(--glass-border)] px-4 py-2.5">
          <p className="text-sm font-semibold">{title}</p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.open(url, '_blank')}
              aria-label={t('management.neko.plugins.openExternal')}
              className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
            >
              <ExternalLink className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label={t('management.neko.plugins.close')}
              className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <iframe src={url} title={title} className="h-full w-full flex-1 bg-white" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 插件详情抽屉（生命周期配置 / 声明入口(快捷动作·事件) / 事件消息）
// ---------------------------------------------------------------------------
interface EntryPreview {
  id?: string;
  name?: string;
  description?: string;
  event_type?: string;
  kind?: string;
  auto_start?: boolean;
  timeout?: number | null;
  [key: string]: unknown;
}

function normalizeMessages(data: unknown): unknown[] {
  if (Array.isArray(data)) return data as unknown[];
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    const raw = obj.messages ?? obj.items ?? obj.records ?? obj.data;
    if (Array.isArray(raw)) return raw as unknown[];
  }
  return [];
}

function PluginDetailDrawer({ plugin, onClose }: { plugin: NekoPluginItem; onClose: () => void }) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<Record<string, unknown> | null | undefined>(undefined);
  const [messages, setMessages] = useState<unknown[]>([]);
  const [loadingMsgs, setLoadingMsgs] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        setConfig(await nekoApi.getPluginConfig(plugin.id));
      } catch {
        setConfig(null);
      }
    })();
    void (async () => {
      setLoadingMsgs(true);
      try {
        setMessages(normalizeMessages(await nekoApi.getPluginMessages(plugin.id, 50)));
      } catch {
        setMessages([]);
      } finally {
        setLoadingMsgs(false);
      }
    })();
  }, [plugin.id]);

  const entries = (Array.isArray(plugin.entries_preview) ? plugin.entries_preview : []) as EntryPreview[];
  const lifecycle = config ?? {};
  const enabled = lifecycle.enabled;
  const autoStart = lifecycle.auto_start ?? plugin.auto_start;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div
        className="h-full w-full max-w-lg space-y-4 overflow-y-auto bg-[#15151d] p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold">{plugin.name || plugin.id}</h2>
            <p className="truncate font-mono text-[11px] text-muted-foreground">{plugin.id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('management.neko.plugins.close')}
            className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 生命周期配置 */}
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('management.neko.detail.lifecycle')}
          </h3>
          <div className="glass-panel space-y-2 p-4 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">{t('management.neko.detail.enabled')}</span>
              <StatusBadge ok={enabled !== false} text={enabled !== false ? t('management.neko.detail.on') : t('management.neko.detail.off')} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">{t('management.neko.detail.autoStart')}</span>
              <StatusBadge ok={!!autoStart} text={autoStart ? t('management.neko.detail.on') : t('management.neko.detail.off')} />
            </div>
            {Object.entries(lifecycle)
              .filter(([k]) => !['enabled', 'auto_start'].includes(k))
              .slice(0, 8)
              .map(([k, v]) => (
                <div key={k} className="flex items-start justify-between gap-2">
                  <span className="shrink-0 text-muted-foreground/70">{k}</span>
                  <span className="max-w-[60%] break-words text-right text-foreground/85">
                    {typeof v === 'object' ? JSON.stringify(v) : String(v ?? '-')}
                  </span>
                </div>
              ))}
          </div>
        </section>

        {/* 声明入口（快捷动作 / 事件） */}
        <section>
          <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            <MessageCircle className="h-3.5 w-3.5" />
            {t('management.neko.detail.entries')}
          </h3>
          {entries.length === 0 ? (
            <p className="glass-panel p-4 text-xs text-muted-foreground">{t('management.neko.detail.noEntries')}</p>
          ) : (
            <div className="space-y-2">
              {entries.map((entry) => (
                <div key={entry.id} className="glass-panel p-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{entry.name || entry.id}</span>
                    <div className="flex shrink-0 items-center gap-1">
                      <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[10px] text-secondary">
                        {entry.kind || entry.event_type || 'entry'}
                      </span>
                      {entry.auto_start && (
                        <StatusBadge ok text={t('management.neko.detail.autoStart')} />
                      )}
                    </div>
                  </div>
                  {entry.description && (
                    <p className="mt-1 text-muted-foreground">{entry.description}</p>
                  )}
                  {entry.timeout != null && (
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground/70">
                      {t('management.neko.detail.timeout', { s: entry.timeout })}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 事件 / 消息 */}
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {t('management.neko.detail.messages')}
          </h3>
          {loadingMsgs ? (
            <div className="glass-panel p-4 text-center text-xs text-muted-foreground">
              <Loader2 className="mx-auto mb-1 h-4 w-4 animate-spin" />
              {t('common.loading')}
            </div>
          ) : messages.length === 0 ? (
            <p className="glass-panel p-4 text-xs text-muted-foreground">{t('management.neko.detail.noMessages')}</p>
          ) : (
            <div className="glass-panel max-h-64 space-y-1 overflow-y-auto p-3 text-[11px]">
              {messages.map((m, i) => (
                <pre key={i} className="whitespace-pre-wrap break-all border-l-2 border-secondary/40 pl-2 text-muted-foreground">
                  {typeof m === 'string' ? m : JSON.stringify(m)}
                </pre>
              ))}
            </div>
          )}
        </section>

        <div className="flex justify-end pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.neko.plugins.close')}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 商店 Tab
// ---------------------------------------------------------------------------
function StoreTab() {
  const { t } = useTranslation();
  const { catalog, loadingCatalog, marketStatus, refreshCatalog, installPlugin, pollTask, installTasks, marketUnreachable } = useNekoStore();
  const [installing, setInstalling] = useState<string | null>(null);
  const [embedMarket, setEmbedMarket] = useState(false);

  const marketWebUrl = marketStatus?.market_web_url || '';

  const waitTerminal = async (taskId: string): Promise<void> => {
    for (let i = 0; i < 120; i++) {
      await pollTask(taskId);
      const task = useNekoStore.getState().installTasks[taskId];
      if (task && ['completed', 'failed', 'cancelled'].includes(task.status)) return;
      await sleep(1500);
    }
  };

  const handleInstall = async (plugin: NekoCatalogPlugin) => {
    const latest = plugin.latest_version;
    const packageUrl = latest?.package_url;
    const sha256 = latest?.package_sha256;
    if (!packageUrl || !sha256) return;
    const id = String(plugin.id ?? plugin.slug ?? plugin.name ?? '');
    setInstalling(id);
    const taskId = await installPlugin({
      package_url: packageUrl,
      package_sha256: sha256,
      plugin_id: String(plugin.id ?? plugin.slug ?? ''),
      version: latest?.version,
      expected_plugin_toml_id: String(plugin.slug ?? plugin.id ?? ''),
    });
    if (taskId) await waitTerminal(taskId);
    setInstalling(null);
  };

  // 安装任务展示
  const activeTasks = Object.values(installTasks).filter((tk) => !['completed', 'failed', 'cancelled'].includes(tk.status));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {marketUnreachable ? (
            <span className="text-red-400">{t('management.neko.store.unreachable')}</span>
          ) : (
            <>
              <Store className="h-3.5 w-3.5" />
              {marketStatus?.online !== false
                ? t('management.neko.store.online')
                : t('management.neko.store.offline')}
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setEmbedMarket((v) => !v)}
            disabled={!marketWebUrl}
            className={cn(
              'flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs transition-colors',
              embedMarket
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40',
            )}
          >
            <ExternalLink className="h-3.5 w-3.5" />
            {t('management.neko.store.embed')}
          </button>
          <button
            type="button"
            onClick={() => void refreshCatalog()}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t('management.neko.store.refresh')}
          </button>
        </div>
      </div>

      {embedMarket ? (
        marketWebUrl ? (
          <div className="overflow-hidden rounded-xl border border-[var(--glass-border)]">
            <div className="h-[70vh] w-full">
              <iframe
                src={marketWebUrl}
                title="Neko Market"
                className="h-full w-full bg-white"
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
              />
            </div>
          </div>
        ) : (
          <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
            {t('management.neko.store.embedUnavailable')}
          </div>
        )
      ) : (
        <>
          {activeTasks.length > 0 && (
        <div className="space-y-2">
          {activeTasks.map((task) => (
            <div key={task.task_id} className="glass-panel flex items-center gap-3 p-3 text-xs">
              <Loader2 className="h-4 w-4 animate-spin text-primary" />
              <span className="min-w-0 flex-1 truncate">{task.message || task.stage}</span>
              <span className="tabular-nums text-muted-foreground">{Math.round(task.progress * 100)}%</span>
            </div>
          ))}
        </div>
      )}

      {loadingCatalog ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" />
          {t('common.loading')}
        </div>
      ) : catalog.length === 0 ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('management.neko.store.empty')}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {catalog.map((plugin) => {
            const id = String(plugin.id ?? plugin.slug ?? plugin.name ?? '');
            const latest = plugin.latest_version;
            const installable = !!latest?.package_url && !!latest?.package_sha256;
            return (
              <div key={id} className="glass-panel flex flex-col gap-2 p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold">{plugin.name || id}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {latest?.version && (
                        <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[10px] text-secondary">
                          {latest.version}
                        </span>
                      )}
                      {latest?.channel && (
                        <span className="rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          {latest.channel}
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleInstall(plugin)}
                    disabled={!installable || installing === id}
                    className="flex shrink-0 items-center gap-1 rounded-lg bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-40"
                  >
                    {installing === id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
                    {t('management.neko.store.install')}
                  </button>
                </div>
                <p className="line-clamp-2 min-h-[1.25rem] text-xs text-muted-foreground">
                  {plugin.description || t('management.neko.plugins.noDescription')}
                </p>
              </div>
            );
          })}
        </div>
      )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 安装来源 Tab
// ---------------------------------------------------------------------------
function InstallTab() {
  const { t } = useTranslation();
  const { installPlugin, pollTask } = useNekoStore();
  const [url, setUrl] = useState('');
  const [sha256, setSha256] = useState('');
  const [kind, setKind] = useState<'url' | 'local'>('url');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const handleInstall = async () => {
    if (busy) return;
    const trimmedUrl = url.trim();
    if (!trimmedUrl) return;
    setBusy(true);
    setMsg(null);
    const taskId = await installPlugin({
      package_url: trimmedUrl,
      package_sha256: sha256.trim() || '0'.repeat(64),
      on_conflict: 'fail',
    });
    if (taskId) {
      setMsg(t('management.neko.install.started'));
      for (let i = 0; i < 120; i++) {
        await pollTask(taskId);
        const task = useNekoStore.getState().installTasks[taskId];
        if (task && ['completed', 'failed', 'cancelled'].includes(task.status)) {
          setMsg(task.error || task.message || task.status);
          setBusy(false);
          return;
        }
        await sleep(1500);
      }
      setBusy(false);
    } else {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="flex flex-wrap gap-2">
        {(['url', 'local'] as const).map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setKind(k)}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              kind === k
                ? 'bg-primary text-primary-foreground'
                : 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
            )}
          >
            {t(`management.neko.install.kind.${k}`)}
          </button>
        ))}
      </div>

      {kind === 'url' ? (
        <div className="glass-panel space-y-3 p-5">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t('management.neko.install.packageUrl')}
            </label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/plugin.zip"
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t('management.neko.install.sha256')}
            </label>
            <input
              value={sha256}
              onChange={(e) => setSha256(e.target.value.trim())}
              placeholder={t('management.neko.install.sha256Placeholder')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 font-mono text-xs focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </div>
          <button
            type="button"
            onClick={() => void handleInstall()}
            disabled={!url.trim() || busy}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-40"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {t('management.neko.install.install')}
          </button>
          {msg && <p className="text-xs text-muted-foreground">{msg}</p>}
        </div>
      ) : (
        <div className="glass-panel space-y-3 p-5">
          <p className="text-xs text-muted-foreground">{t('management.neko.install.localNote')}</p>
          <p className="text-xs text-muted-foreground/70">{t('management.neko.install.localHint')}</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 日志 Tab
// ---------------------------------------------------------------------------
function LogsTab() {
  const { t } = useTranslation();
  const { logs, clearLogs } = useNekoStore();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = boxRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [logs]);

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={clearLogs}
          className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <Trash2 className="h-3.5 w-3.5" />
          {t('management.neko.logs.clear')}
        </button>
      </div>
      <div
        ref={boxRef}
        className="glass-panel h-[50vh] overflow-auto rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-relaxed"
      >
        {logs.length === 0 ? (
          <p className="text-muted-foreground">{t('management.neko.logs.empty')}</p>
        ) : (
          logs.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all text-foreground/80">
              <span className="mr-2 select-none text-muted-foreground/50">{i + 1}</span>
              {line}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 设置 Tab
// ---------------------------------------------------------------------------
function SettingsTab() {
  const { t } = useTranslation();
  const { config, setConfig } = useNekoStore();
  const [draft, setDraft] = useState(config);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setDraft(config);
    setSaved(false);
  }, [config]);

  const save = async () => {
    await setConfig({ ...draft });
    setSaved(true);
  };

  const field = (label: string, key: keyof typeof draft, placeholder?: string) => (
    <div>
      <label className="mb-1.5 block text-xs font-medium text-muted-foreground">{label}</label>
      <input
        value={String(draft[key])}
        placeholder={placeholder}
        onChange={(e) => setDraft((d) => ({ ...d, [key]: key === 'port' || key === 'autoStart' ? (key === 'port' ? Number(e.target.value) : e.target.value === 'true') : e.target.value }))}
        className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
      />
    </div>
  );

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <div className="glass-panel space-y-3 p-5">
        {field(t('management.neko.settings.python'), 'python')}
        {field(t('management.neko.settings.sourceDir'), 'sourceDir', 'C:\\N.E.K.O-main')}
        {field(t('management.neko.settings.port'), 'port')}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={draft.autoStart}
            onChange={(e) => setDraft((d) => ({ ...d, autoStart: e.target.checked }))}
            className="h-4 w-4 shrink-0"
          />
          {t('management.neko.settings.autoStart')}
        </label>
        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => void save()}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85"
          >
            {t('management.neko.settings.save')}
          </button>
          {saved && <span className="text-xs text-emerald-400">{t('management.neko.settings.saved')}</span>}
        </div>
      </div>

      {/* 边界与运行前提说明 */}
      <div className="glass-panel space-y-2 p-5 text-xs leading-relaxed text-muted-foreground">
        <p className="font-semibold text-foreground">{t('management.neko.settings.preconditionTitle')}</p>
        <p>{t('management.neko.settings.preconditionBody')}</p>
        <p className="pt-1 font-semibold text-foreground">{t('management.neko.settings.boundaryTitle')}</p>
        <p>{t('management.neko.settings.boundaryBody')}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 页面
// ---------------------------------------------------------------------------
type TabKey = 'plugins' | 'store' | 'install' | 'logs' | 'settings';

export default function NekoPluginsPage() {
  const { t } = useTranslation();
  const { refreshStatus } = useNekoStore();
  const [tab, setTab] = useState<TabKey>('plugins');

  // 挂载时刷新运行时状态，并订阅日志
  useEffect(() => {
    void refreshStatus();
    const off = subscribeNekoLogs(useNekoStore);
    return () => off?.();
  }, [refreshStatus]);

  const tabs: { key: TabKey; label: string; icon: typeof List }[] = [
    { key: 'plugins', label: t('management.neko.tab.plugins'), icon: List },
    { key: 'store', label: t('management.neko.tab.store'), icon: Store },
    { key: 'install', label: t('management.neko.tab.install'), icon: Package },
    { key: 'logs', label: t('management.neko.tab.logs'), icon: Loader2 },
    { key: 'settings', label: t('management.neko.tab.settings'), icon: Cat },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">{t('management.neko.subtitle')}</p>
      </div>

      <RuntimeHeader />

      {/* Tab 导航 */}
      <div className="flex flex-wrap gap-2">
        {tabs.map((tb) => (
          <button
            key={tb.key}
            type="button"
            onClick={() => setTab(tb.key)}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              tab === tb.key
                ? 'bg-primary text-primary-foreground'
                : 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
            )}
          >
            <tb.icon className="h-3.5 w-3.5" />
            {tb.label}
          </button>
        ))}
      </div>

      <div>
        {tab === 'plugins' && <PluginsTab />}
        {tab === 'store' && <StoreTab />}
        {tab === 'install' && <InstallTab />}
        {tab === 'logs' && <LogsTab />}
        {tab === 'settings' && <SettingsTab />}
      </div>
    </div>
  );
}