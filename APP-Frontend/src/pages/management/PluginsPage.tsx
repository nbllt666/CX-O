/**
 * 插件页（SubTask 7.2）
 *
 * 功能口径对齐 CX-O-Frontend PluginsPage：
 * - 统计行：已连接插件 / 总插件数 / 提供工具 / Skills
 * - 三个 Tab：插件列表（状态徽章、能力标签、提供工具、刷新/断开）、
 *   Skills 列表（触发关键词/事件、来源插件）、局域网发现（扫描 + 一键连接）
 * - 连接插件弹窗（主机 + 端口）
 *
 * 数据全部来自 cxfcApi（getCxfcPlugins / getCxfcSkills / connectCxfcPlugin /
 * disconnectCxfcPlugin / refreshCxfcPlugin / discoverCxfcPlugins）。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Layers,
  Network,
  Plus,
  RefreshCw,
  Search,
  Wifi,
  WifiOff,
  X,
  Zap,
} from 'lucide-react';
import { cxfcApi } from '@/api/clients/cxfc';
import type { CxfcDiscoveredPlugin, CxfcPlugin, CxfcSkill } from '@/api/types';
import { cn } from '@/lib/utils';

type TabKey = 'plugins' | 'skills' | 'discover';

export default function PluginsPage() {
  const { t } = useTranslation();
  const [plugins, setPlugins] = useState<CxfcPlugin[]>([]);
  const [skills, setSkills] = useState<CxfcSkill[]>([]);
  const [discovered, setDiscovered] = useState<CxfcDiscoveredPlugin[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('plugins');
  const [hasScanned, setHasScanned] = useState(false);
  const [isScanning, setIsScanning] = useState(false);
  const [actionError, setActionError] = useState(false);

  const [showConnect, setShowConnect] = useState(false);
  const [connectHost, setConnectHost] = useState('127.0.0.1');
  const [connectPort, setConnectPort] = useState('8081');
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectError, setConnectError] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const [pluginData, skillData] = await Promise.all([
        cxfcApi.getCxfcPlugins(),
        cxfcApi.getCxfcSkills().catch(() => [] as CxfcSkill[]),
      ]);
      setPlugins(pluginData);
      setSkills(skillData);
    } catch (error) {
      console.error('Plugins load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleConnect = async () => {
    const port = Number(connectPort);
    if (!connectHost.trim() || !Number.isFinite(port) || port <= 0 || isConnecting) return;
    setIsConnecting(true);
    setConnectError(false);
    try {
      await cxfcApi.connectCxfcPlugin(connectHost.trim(), port);
      setShowConnect(false);
      await load();
    } catch (error) {
      console.error('Plugin connect failed:', error);
      setConnectError(true);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleDisconnect = async (plugin: CxfcPlugin) => {
    if (!window.confirm(t('management.plugins.disconnectConfirm', { name: plugin.name || plugin.plugin_id }))) {
      return;
    }
    setActionError(false);
    try {
      await cxfcApi.disconnectCxfcPlugin(plugin.plugin_id);
      await load();
    } catch (error) {
      console.error('Plugin disconnect failed:', error);
      setActionError(true);
    }
  };

  const handleRefresh = async (plugin: CxfcPlugin) => {
    setActionError(false);
    try {
      await cxfcApi.refreshCxfcPlugin(plugin.plugin_id);
      await load();
    } catch (error) {
      console.error('Plugin refresh failed:', error);
      setActionError(true);
    }
  };

  const handleScan = async () => {
    setIsScanning(true);
    setHasScanned(true);
    setActiveTab('discover');
    try {
      const result = await cxfcApi.discoverCxfcPlugins(true);
      setDiscovered(result.remote || []);
    } catch (error) {
      console.error('Plugin scan failed:', error);
      setDiscovered([]);
    } finally {
      setIsScanning(false);
    }
  };

  const handleConnectDiscovered = async (plugin: CxfcDiscoveredPlugin) => {
    setActionError(false);
    try {
      await cxfcApi.connectCxfcPlugin(plugin.host, plugin.port);
      await load();
      setActiveTab('plugins');
    } catch (error) {
      console.error('Connect discovered plugin failed:', error);
      setActionError(true);
    }
  };

  const connectedCount = plugins.filter((p) => p.status === 'connected').length;
  const totalTools = plugins.reduce((sum, p) => sum + (p.tools?.length ?? 0), 0);

  const inputCls =
    'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.plugins.subtitle')}</p>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => void load()}
            aria-label={t('management.plugins.refresh')}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t('management.plugins.refresh')}
          </button>
          <button
            type="button"
            onClick={() => void handleScan()}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            <Search className="h-3.5 w-3.5" />
            {t('management.plugins.scan')}
          </button>
          <button
            type="button"
            onClick={() => setShowConnect(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85"
          >
            <Plus className="h-3.5 w-3.5" />
            {t('management.plugins.connect')}
          </button>
        </div>
      </div>

      {/* 统计行 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
            <Wifi className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.plugins.statsConnected')}</p>
            <p className="text-2xl font-bold tabular-nums">{connectedCount}</p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Layers className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.plugins.statsTotal')}</p>
            <p className="text-2xl font-bold tabular-nums">{plugins.length}</p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary/15 text-secondary">
            <Zap className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.plugins.statsTools')}</p>
            <p className="text-2xl font-bold tabular-nums">{totalTools}</p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent">
            <Network className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.plugins.statsSkills')}</p>
            <p className="text-2xl font-bold tabular-nums">{skills.length}</p>
          </div>
        </div>
      </div>

      {actionError && (
        <p className="text-xs text-red-400">{t('management.plugins.actionFailed')}</p>
      )}

      {/* Tab 切换 */}
      <div className="flex gap-2">
        {(['plugins', 'skills', 'discover'] as const).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              activeTab === tab
                ? 'bg-primary text-primary-foreground'
                : 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
            )}
          >
            {t(`management.plugins.tab.${tab}`)}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('common.loading')}
        </div>
      ) : loadError ? (
        <div className="glass-panel space-y-3 p-8 text-center">
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
          {/* 插件列表 */}
          {activeTab === 'plugins' &&
            (plugins.length === 0 ? (
              <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
                {t('management.plugins.empty')}
              </div>
            ) : (
              <div className="space-y-3">
                {plugins.map((plugin) => (
                  <div key={plugin.plugin_id} className="glass-panel p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold">
                            {plugin.name || plugin.plugin_id}
                          </span>
                          <span
                            className={cn(
                              'rounded px-1.5 py-0.5 text-[10px] font-medium',
                              plugin.status === 'connected'
                                ? 'bg-emerald-500/15 text-emerald-400'
                                : 'bg-red-500/15 text-red-400',
                            )}
                          >
                            {plugin.status === 'connected'
                              ? t('management.plugins.statusConnected')
                              : t('management.plugins.statusDisconnected')}
                          </span>
                          {plugin.version && (
                            <span className="text-[10px] text-muted-foreground">
                              v{plugin.version}
                            </span>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {plugin.host && plugin.port
                            ? `${plugin.host}:${plugin.port}`
                            : (t(`management.plugins.transport.${plugin.transport || 'direct'}`) ||
                               plugin.transport ||
                               'direct')}
                          {plugin.tools.length > 0 &&
                            ` · ${t('management.plugins.toolCount', { count: plugin.tools.length })}`}
                          {plugin.skills.length > 0 &&
                            ` · ${t('management.plugins.skillCount', { count: plugin.skills.length })}`}
                        </p>
                      </div>
                      <div className="flex shrink-0 gap-1">
                        <button
                          type="button"
                          onClick={() => void handleRefresh(plugin)}
                          aria-label={t('management.plugins.refreshPlugin')}
                          title={t('management.plugins.refreshPlugin')}
                          className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                        >
                          <RefreshCw className="h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => void handleDisconnect(plugin)}
                          aria-label={t('management.plugins.disconnect')}
                          title={t('management.plugins.disconnect')}
                          className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-400"
                        >
                          <WifiOff className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    {plugin.capabilities.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {plugin.capabilities.map((cap) => (
                          <span
                            key={cap}
                            className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary"
                          >
                            {cap}
                          </span>
                        ))}
                      </div>
                    )}
                    {plugin.tools.length > 0 && (
                      <div className="mt-3 border-t border-[var(--glass-border)] pt-2">
                        <p className="mb-1.5 text-[10px] font-medium text-muted-foreground">
                          {t('management.plugins.providedTools')}
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {plugin.tools.map((tool, i) => (
                            <span
                              key={`${tool.name}-${i}`}
                              className="rounded bg-[rgba(255,255,255,0.06)] px-1.5 py-0.5 text-[10px] text-muted-foreground"
                            >
                              {tool.name || `tool_${i}`}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}

          {/* Skills 列表 */}
          {activeTab === 'skills' &&
            (skills.length === 0 ? (
              <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
                {t('management.plugins.skillsEmpty')}
              </div>
            ) : (
              <div className="space-y-3">
                {skills.map((skill) => (
                  <div key={skill.name} className="glass-panel p-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold">{skill.name}</span>
                      {skill.auto_inject && (
                        <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[10px] text-secondary">
                          {t('management.plugins.autoInject')}
                        </span>
                      )}
                    </div>
                    {skill.description && (
                      <p className="mt-1 text-xs text-muted-foreground">{skill.description}</p>
                    )}
                    {skill.trigger_keywords.length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1">
                        <span className="text-[10px] text-muted-foreground">
                          {t('management.plugins.triggerKeywords')}:
                        </span>
                        {skill.trigger_keywords.map((kw) => (
                          <span
                            key={kw}
                            className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400"
                          >
                            {kw}
                          </span>
                        ))}
                      </div>
                    )}
                    {skill.trigger_events.length > 0 && (
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <span className="text-[10px] text-muted-foreground">
                          {t('management.plugins.triggerEvents')}:
                        </span>
                        {skill.trigger_events.map((ev) => (
                          <span
                            key={ev}
                            className="rounded bg-orange-500/10 px-1.5 py-0.5 text-[10px] text-orange-400"
                          >
                            {ev}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))}

          {/* 局域网发现 */}
          {activeTab === 'discover' && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {hasScanned
                    ? t('management.plugins.discoverResult', { count: discovered.length })
                    : t('management.plugins.discoverHint')}
                </p>
                <button
                  type="button"
                  onClick={() => void handleScan()}
                  disabled={isScanning}
                  className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
                >
                  <Search className="h-3.5 w-3.5" />
                  {isScanning ? t('management.plugins.scanning') : t('management.plugins.rescan')}
                </button>
              </div>
              {hasScanned && discovered.length === 0 && !isScanning ? (
                <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
                  {t('management.plugins.discoverEmpty')}
                </div>
              ) : (
                discovered.map((plugin, i) => (
                  <div
                    key={`${plugin.host}:${plugin.port}:${i}`}
                    className="glass-panel flex items-center justify-between gap-4 p-4"
                  >
                    <div className="min-w-0">
                      <p className="text-sm font-semibold">
                        {plugin.name || t('management.plugins.unknownPlugin')}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {plugin.host}:{plugin.port}
                        {plugin.version && ` · v${plugin.version}`}
                      </p>
                      {plugin.capabilities.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {plugin.capabilities.map((cap) => (
                            <span
                              key={cap}
                              className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary"
                            >
                              {cap}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleConnectDiscovered(plugin)}
                      className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85"
                    >
                      <Wifi className="h-3.5 w-3.5" />
                      {t('management.plugins.connectShort')}
                    </button>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}

      {/* 连接弹窗 */}
      {showConnect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
          <div className="glass-panel w-full max-w-sm space-y-4 p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold">{t('management.plugins.connectTitle')}</h2>
              <button
                type="button"
                onClick={() => setShowConnect(false)}
                aria-label={t('management.plugins.close')}
                className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                {t('management.plugins.fieldHost')}
              </label>
              <input
                value={connectHost}
                onChange={(e) => setConnectHost(e.target.value)}
                aria-label={t('management.plugins.fieldHost')}
                className={inputCls}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                {t('management.plugins.fieldPort')}
              </label>
              <input
                type="number"
                value={connectPort}
                onChange={(e) => setConnectPort(e.target.value)}
                aria-label={t('management.plugins.fieldPort')}
                className={inputCls}
              />
            </div>
            {connectError && (
              <p className="text-xs text-red-400">{t('management.plugins.connectFailed')}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowConnect(false)}
                className="rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
              >
                {t('management.plugins.cancel')}
              </button>
              <button
                type="button"
                onClick={() => void handleConnect()}
                disabled={isConnecting || !connectHost.trim()}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {isConnecting
                  ? t('management.plugins.connecting')
                  : t('management.plugins.connectShort')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
