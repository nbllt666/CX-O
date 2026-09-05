/**
 * CXFC 管理页（enhance-cxfc-admin-and-integrate-dream · Task 2）
 *
 * 四区块：
 * - 插件总览：插件列表 + transport 徽章（direct/relay/embedded）+ 心跳状态（status/last_seen）
 * - 工具与技能清单：按 plugin_id 分组（工具来自 plugins[].tools，技能来自 getCxfcSkills 按 source_plugin_id 归组）
 * - Relay 目标列表：GET /api/cxfc/relay/targets（前端转接插件）
 * - 记忆/生理网关测试器：选端点 + JSON 参数 -> 调用 -> 展示响应 JSON；
 *   错误态红色可见（非静默），运维旁路鉴权走 base.ts 拦截器注入的 x-api-key
 *
 * 风格对齐 DashboardPage glass-panel；数据来自 cxfcApi，useState + useEffect 拉取（无 react-query）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Cable,
  FlaskConical,
  HeartPulse,
  Puzzle,
  RefreshCw,
  Wrench,
} from 'lucide-react';
import { cxfcApi } from '@/api/clients/cxfc';
import type {
  CxfcMemorySearchPayload,
  CxfcMemoryWritePayload,
  CxfcPhysioReportPayload,
  CxfcRelayTarget,
} from '@/api/clients/cxfc';
import type { CxfcPlugin, CxfcSkill } from '@/api/types';
import { cn } from '@/lib/utils';

/** 网关测试器端点 key */
type GatewayEndpointKey =
  | 'memorySearch'
  | 'memoryWrite'
  | 'memoryStats'
  | 'memoryGet'
  | 'physioReport'
  | 'physioStatus'
  | 'physioSleep';

const GATEWAY_ENDPOINT_KEYS: readonly GatewayEndpointKey[] = [
  'memorySearch',
  'memoryWrite',
  'memoryStats',
  'memoryGet',
  'physioReport',
  'physioStatus',
  'physioSleep',
];

/** 各端点默认请求参数（切换端点时回填） */
const DEFAULT_PARAMS: Record<GatewayEndpointKey, string> = {
  memorySearch: '{\n  "query": "",\n  "limit": 5,\n  "agent_id": "default"\n}',
  memoryWrite: '{\n  "content": "",\n  "agent_id": "default"\n}',
  memoryStats: '{}',
  memoryGet: '{\n  "id": ""\n}',
  physioReport: '{\n  "heart_rate": 72,\n  "source": "manual"\n}',
  physioStatus: '{}',
  physioSleep: '{}',
};

/** 工具/技能按 plugin_id 分组后的条目（升序排列） */
interface PluginToolGroup {
  pluginId: string;
  tools: string[];
  skills: CxfcSkill[];
}

/** transport 徽章配色 */
function transportBadgeClass(transport: string): string {
  if (transport === 'relay') return 'bg-secondary/15 text-secondary';
  if (transport === 'embedded') return 'bg-accent/15 text-accent';
  return 'bg-primary/10 text-primary';
}

/** 心跳时间格式化（非法或缺失返回空串，由调用方回退 i18n 文案） */
function formatLastSeen(value: string | null | undefined): string {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString();
}

export default function CxfcPage() {
  const { t } = useTranslation();

  // ── 总览数据：插件 / 技能 / relay 目标 ──
  const [plugins, setPlugins] = useState<CxfcPlugin[]>([]);
  const [skills, setSkills] = useState<CxfcSkill[]>([]);
  const [relayTargets, setRelayTargets] = useState<CxfcRelayTarget[]>([]);
  const [relayError, setRelayError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    // relay 目标为增强信息：拉取失败不阻断主视图，仅区块内降级提示（可见非静默）
    const relayResult = await cxfcApi
      .relayTargets()
      .then((resp) => ({ ok: true as const, targets: resp.targets || [] }))
      .catch(() => ({ ok: false as const, targets: [] as CxfcRelayTarget[] }));
    try {
      const [pluginData, skillData] = await Promise.all([
        cxfcApi.getCxfcPlugins(),
        cxfcApi.getCxfcSkills().catch(() => [] as CxfcSkill[]),
      ]);
      setPlugins(pluginData);
      setSkills(skillData);
      setRelayTargets(relayResult.targets);
      setRelayError(!relayResult.ok);
    } catch (error) {
      console.error('CxfcPage load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // ── 工具/技能按 plugin_id 分组（插件升序，未归组技能排最后） ──
  const toolGroups = useMemo<PluginToolGroup[]>(() => {
    const map = new Map<string, PluginToolGroup>();
    for (const p of plugins) {
      map.set(p.plugin_id, {
        pluginId: p.plugin_id,
        tools: (p.tools ?? []).map((tool) => tool.name).filter(Boolean),
        skills: [],
      });
    }
    for (const s of skills) {
      const gid = s.source_plugin_id || '__ungrouped__';
      const group = map.get(gid);
      if (group) {
        group.skills.push(s);
      } else {
        map.set(gid, { pluginId: gid, tools: [], skills: [s] });
      }
    }
    return Array.from(map.values()).sort((a, b) => {
      if (a.pluginId === '__ungrouped__') return 1;
      if (b.pluginId === '__ungrouped__') return -1;
      return a.pluginId.localeCompare(b.pluginId);
    });
  }, [plugins, skills]);

  // ── 网关测试器状态 ──
  const [endpointKey, setEndpointKey] = useState<GatewayEndpointKey>('memoryStats');
  const [paramsText, setParamsText] = useState<string>(DEFAULT_PARAMS.memoryStats);
  const [isCalling, setIsCalling] = useState(false);
  const [callError, setCallError] = useState<string | null>(null);
  const [response, setResponse] = useState<unknown>(null);

  const handleEndpointChange = (key: GatewayEndpointKey) => {
    setEndpointKey(key);
    setParamsText(DEFAULT_PARAMS[key]);
    setCallError(null);
    setResponse(null);
  };

  const handleCall = async () => {
    // JSON 参数解析失败即刻报错（红色可见，不静默吞掉）
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(paramsText || '{}') as Record<string, unknown>;
    } catch {
      setCallError(t('management.cxfc.invalidJson'));
      setResponse(null);
      return;
    }
    setIsCalling(true);
    setCallError(null);
    setResponse(null);
    try {
      let result: unknown;
      switch (endpointKey) {
        case 'memorySearch':
          result = await cxfcApi.memorySearch(parsed as CxfcMemorySearchPayload);
          break;
        case 'memoryWrite':
          result = await cxfcApi.memoryWrite(parsed as CxfcMemoryWritePayload);
          break;
        case 'memoryStats':
          result = await cxfcApi.memoryStats();
          break;
        case 'memoryGet':
          result = await cxfcApi.memoryGet(String(parsed.id ?? ''));
          break;
        case 'physioReport':
          result = await cxfcApi.physioReport(parsed as CxfcPhysioReportPayload);
          break;
        case 'physioStatus':
          result = await cxfcApi.physioStatus();
          break;
        case 'physioSleep':
          result = await cxfcApi.physioSleep();
          break;
      }
      setResponse(result);
    } catch (error) {
      setCallError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsCalling(false);
    }
  };

  const inputCls =
    'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.cxfc.subtitle')}</p>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t('management.cxfc.refresh')}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('management.cxfc.refresh')}
        </button>
      </div>

      {isLoading ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('common.loading')}
        </div>
      ) : loadError ? (
        <div className="glass-panel space-y-3 p-8 text-center">
          <p className="text-sm text-red-400">{t('management.cxfc.loadFailed')}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-1.5 text-xs transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.cxfc.retry')}
          </button>
        </div>
      ) : (
        <>
          {/* 区块一：插件总览（transport 徽章 + 心跳状态） */}
          <section className="glass-panel p-5">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
              <Puzzle className="h-4 w-4 text-primary" />
              {t('management.cxfc.pluginsTitle')}
            </h2>
            {plugins.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {t('management.cxfc.pluginsEmpty')}
              </p>
            ) : (
              <div className="space-y-3">
                {plugins.map((plugin) => {
                  const transport = plugin.transport || 'direct';
                  const lastSeen = formatLastSeen(plugin.last_seen);
                  const heartbeatOk = plugin.status === 'connected';
                  return (
                    <div
                      key={plugin.plugin_id}
                      className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold">
                          {plugin.name || plugin.plugin_id}
                        </span>
                        <span
                          className={cn(
                            'rounded px-1.5 py-0.5 text-[10px] font-medium',
                            transportBadgeClass(transport),
                          )}
                        >
                          {t(`management.cxfc.transport.${transport}`)}
                        </span>
                        <span
                          className={cn(
                            'flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[10px] font-medium',
                            heartbeatOk
                              ? 'bg-emerald-500/15 text-emerald-400'
                              : 'bg-red-500/15 text-red-400',
                          )}
                          title={t('management.cxfc.heartbeat')}
                        >
                          <HeartPulse className="h-3 w-3" />
                          {t('management.cxfc.heartbeat')}:
                          {heartbeatOk
                            ? t('management.cxfc.heartbeatOk')
                            : t('management.cxfc.heartbeatStale')}
                        </span>
                        {plugin.version && (
                          <span className="text-[10px] text-muted-foreground">
                            v{plugin.version}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {plugin.host && plugin.port ? `${plugin.host}:${plugin.port} · ` : ''}
                        {t('management.cxfc.lastSeen')}:{' '}
                        {lastSeen || t('management.cxfc.lastSeenNever')}
                      </p>
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
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* 区块二：工具与技能清单（按 plugin_id 分组） */}
          <section className="glass-panel p-5">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
              <Wrench className="h-4 w-4 text-secondary" />
              {t('management.cxfc.toolsSkillsTitle')}
            </h2>
            {toolGroups.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {t('management.cxfc.toolsSkillsEmpty')}
              </p>
            ) : (
              <div className="space-y-3">
                {toolGroups.map((group) => (
                  <div
                    key={group.pluginId}
                    className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4"
                  >
                    <p className="text-sm font-semibold">
                      {group.pluginId === '__ungrouped__'
                        ? t('management.cxfc.ungrouped')
                        : group.pluginId}
                    </p>
                    {group.tools.length > 0 && (
                      <div className="mt-2">
                        <p className="mb-1 text-[10px] font-medium text-muted-foreground">
                          {t('management.cxfc.toolsLabel')}（{group.tools.length}）
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {group.tools.map((tool) => (
                            <span
                              key={tool}
                              className="rounded bg-[rgba(255,255,255,0.06)] px-1.5 py-0.5 text-[10px] text-muted-foreground"
                            >
                              {tool}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                    {group.skills.length > 0 && (
                      <div className="mt-2">
                        <p className="mb-1 text-[10px] font-medium text-muted-foreground">
                          {t('management.cxfc.skillsLabel')}（{group.skills.length}）
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {group.skills.map((skill) => (
                            <span
                              key={skill.name}
                              title={skill.description || skill.name}
                              className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400"
                            >
                              {skill.name}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 区块三：Relay 目标列表 */}
          <section className="glass-panel p-5">
            <h2 className="mb-4 flex items-center gap-2 text-base font-semibold">
              <Cable className="h-4 w-4 text-accent" />
              {t('management.cxfc.relayTitle')}
            </h2>
            {relayError && (
              <p className="mb-3 text-xs text-red-400">{t('management.cxfc.relayLoadFailed')}</p>
            )}
            {relayTargets.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                {t('management.cxfc.relayEmpty')}
              </p>
            ) : (
              <div className="space-y-2">
                {relayTargets.map((target) => (
                  <div
                    key={target.plugin_id}
                    className="flex items-center justify-between gap-4 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2.5 text-sm"
                  >
                    <div className="min-w-0">
                      <span className="font-medium">{target.name || target.plugin_id}</span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        {target.plugin_id} · {target.transport}
                      </span>
                    </div>
                    <span
                      className={cn(
                        'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium',
                        target.active
                          ? 'bg-emerald-500/15 text-emerald-400'
                          : 'bg-[rgba(255,255,255,0.08)] text-muted-foreground',
                      )}
                    >
                      {target.active
                        ? t('management.cxfc.relayActive')
                        : t('management.cxfc.relayInactive')}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 区块四：记忆/生理网关测试器 */}
          <section className="glass-panel p-5">
            <h2 className="mb-1 flex items-center gap-2 text-base font-semibold">
              <FlaskConical className="h-4 w-4 text-primary" />
              {t('management.cxfc.testerTitle')}
            </h2>
            <p className="mb-4 text-xs text-muted-foreground">{t('management.cxfc.testerHint')}</p>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="space-y-3">
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                    {t('management.cxfc.endpointLabel')}
                  </label>
                  <select
                    value={endpointKey}
                    onChange={(e) => handleEndpointChange(e.target.value as GatewayEndpointKey)}
                    aria-label={t('management.cxfc.endpointLabel')}
                    className={inputCls}
                  >
                    {GATEWAY_ENDPOINT_KEYS.map((key) => (
                      <option key={key} value={key}>
                        {t(`management.cxfc.endpoints.${key}`)}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                    {t('management.cxfc.paramsLabel')}
                  </label>
                  <textarea
                    value={paramsText}
                    onChange={(e) => setParamsText(e.target.value)}
                    aria-label={t('management.cxfc.paramsLabel')}
                    rows={6}
                    className={cn(inputCls, 'font-mono text-xs')}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => void handleCall()}
                  disabled={isCalling}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
                >
                  {isCalling ? t('management.cxfc.running') : t('management.cxfc.run')}
                </button>
                {callError && (
                  <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                    {t('management.cxfc.errorLabel')}: {callError}
                  </p>
                )}
              </div>

              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">
                  {t('management.cxfc.responseLabel')}
                </p>
                {response === null ? (
                  <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4 text-xs text-muted-foreground">
                    {t('management.cxfc.emptyResponse')}
                  </div>
                ) : (
                  <pre className="max-h-96 overflow-auto rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3 font-mono text-xs leading-relaxed">
                    {JSON.stringify(response, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
