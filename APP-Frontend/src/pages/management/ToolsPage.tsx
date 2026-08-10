/**
 * 工具页（SubTask 7.2）
 *
 * 功能口径对齐 CX-O-Frontend ToolsPage：
 * - 统计行：总工具数 / 活跃工具 / MCP 工具 / 总调用次数
 * - 类型筛选 Tab：全部 / 内置 / MCP / 自定义 / CXFC
 * - 工具卡片网格：名称、描述、类型徽章、状态徽章、调用次数、参数 schema 摘要
 * - 操作：启停切换、测试调用（JSON 参数输入 → 结果展示）、删除自定义工具
 *
 * 数据全部来自 toolsApi（getTools / getToolsStats / testTool / updateTool / deleteTool）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CheckCircle2,
  Code,
  FlaskConical,
  Power,
  RefreshCw,
  Terminal,
  Trash2,
  Wrench,
  X,
} from 'lucide-react';
import { toolsApi } from '@/api/clients/tools';
import type { Tool, ToolStats } from '@/api/types';
import { cn } from '@/lib/utils';

type FilterKey = 'all' | 'builtin' | 'mcp' | 'custom' | 'cxfc';
const FILTERS: FilterKey[] = ['all', 'builtin', 'mcp', 'custom', 'cxfc'];

/** getTools 返回 Record<string, Tool>，规整为数组并补齐缺省字段 */
function normalizeTools(toolsObj: Record<string, Tool>): Tool[] {
  return Object.entries(toolsObj).map(([key, tool]) => ({
    ...tool,
    id: tool.id ?? key,
    name: tool.name ?? key,
    description: tool.description ?? '',
    type: tool.type ?? 'custom',
    status: tool.status ?? 'inactive',
    config: tool.config ?? {},
    use_count: tool.use_count ?? 0,
  }));
}

/** 参数 schema 摘要：列出参数名与类型（parameters 为 JSON Schema 风格对象） */
function paramSummary(parameters?: Record<string, unknown>): string {
  if (!parameters) return '';
  const props = parameters.properties;
  if (!props || typeof props !== 'object') return '';
  return Object.entries(props as Record<string, Record<string, unknown>>)
    .map(([name, def]) => `${name}: ${String(def?.type ?? 'any')}`)
    .join(', ');
}

/** 测试调用弹窗 */
function TestToolModal(props: { tool: Tool; onClose: () => void }) {
  const { t } = useTranslation();
  const [paramsText, setParamsText] = useState('{}');
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const handleRun = async () => {
    if (isRunning) return;
    setIsRunning(true);
    setResult(null);
    setRunError(null);
    try {
      let params: Record<string, unknown> = {};
      const trimmed = paramsText.trim();
      if (trimmed) {
        try {
          params = JSON.parse(trimmed) as Record<string, unknown>;
        } catch {
          setRunError(t('management.tools.invalidJson'));
          setIsRunning(false);
          return;
        }
      }
      const resp = await toolsApi.testTool(props.tool.id, params);
      setResult(JSON.stringify(resp.result ?? resp, null, 2));
    } catch (error) {
      console.error('Tool test failed:', error);
      setRunError(t('management.tools.testFailed'));
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="glass-panel max-h-[85vh] w-full max-w-lg space-y-4 overflow-y-auto p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {t('management.tools.testTitle')}：{props.tool.name}
          </h2>
          <button
            type="button"
            onClick={props.onClose}
            aria-label={t('management.tools.close')}
            className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {paramSummary(props.tool.parameters) && (
          <p className="text-xs text-muted-foreground">
            {t('management.tools.paramSchema')}：{paramSummary(props.tool.parameters)}
          </p>
        )}

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.tools.paramsLabel')}
          </label>
          <textarea
            value={paramsText}
            onChange={(e) => setParamsText(e.target.value)}
            rows={5}
            aria-label={t('management.tools.paramsLabel')}
            className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 font-mono text-xs focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </div>

        {runError && <p className="text-xs text-red-400">{runError}</p>}

        {result !== null && (
          <div>
            <p className="mb-1.5 text-xs font-medium text-muted-foreground">
              {t('management.tools.resultLabel')}
            </p>
            <pre className="max-h-48 overflow-auto rounded-lg border border-[var(--glass-border)] bg-[rgba(0,0,0,0.25)] p-3 text-xs">
              {result}
            </pre>
          </div>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={props.onClose}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.tools.close')}
          </button>
          <button
            type="button"
            onClick={() => void handleRun()}
            disabled={isRunning}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {isRunning ? t('management.tools.running') : t('management.tools.run')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ToolsPage() {
  const { t } = useTranslation();
  const [tools, setTools] = useState<Tool[]>([]);
  const [stats, setStats] = useState<ToolStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [filter, setFilter] = useState<FilterKey>('all');
  const [testing, setTesting] = useState<Tool | null>(null);
  const [actionError, setActionError] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const [toolsResp, statsResp] = await Promise.all([
        toolsApi.getTools(),
        toolsApi.getToolsStats().catch(() => null),
      ]);
      setTools(normalizeTools(toolsResp.tools || {}));
      setStats(statsResp);
    } catch (error) {
      console.error('Tools load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filteredTools = useMemo(
    () => (filter === 'all' ? tools : tools.filter((tool) => tool.type === filter)),
    [tools, filter],
  );

  const handleToggle = async (tool: Tool) => {
    setActionError(false);
    try {
      await toolsApi.updateTool(tool.id, {
        status: tool.status === 'active' ? 'inactive' : 'active',
      });
      await load();
    } catch (error) {
      console.error('Tool toggle failed:', error);
      setActionError(true);
    }
  };

  const handleDelete = async (tool: Tool) => {
    if (!window.confirm(t('management.tools.deleteConfirm', { name: tool.name }))) return;
    setActionError(false);
    try {
      await toolsApi.deleteTool(tool.id);
      await load();
    } catch (error) {
      console.error('Tool delete failed:', error);
      setActionError(true);
    }
  };

  const activeCount = tools.filter((toolItem) => toolItem.status === 'active').length;
  const mcpCount = tools.filter((toolItem) => toolItem.type === 'mcp').length;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.tools.subtitle')}</p>
        <button
          type="button"
          onClick={() => void load()}
          aria-label={t('management.tools.refresh')}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          {t('management.tools.refresh')}
        </button>
      </div>

      {/* 统计行 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Wrench className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.tools.statsTotal')}</p>
            <p className="text-2xl font-bold tabular-nums">{stats?.total_tools ?? tools.length}</p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
            <CheckCircle2 className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.tools.statsActive')}</p>
            <p className="text-2xl font-bold tabular-nums">
              {stats?.active_tools ?? stats?.enabled_tools ?? activeCount}
            </p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary/15 text-secondary">
            <Code className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.tools.statsMcp')}</p>
            <p className="text-2xl font-bold tabular-nums">{stats?.mcp_tools ?? mcpCount}</p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent">
            <Terminal className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.tools.statsCalls')}</p>
            <p className="text-2xl font-bold tabular-nums">{stats?.total_calls ?? 0}</p>
          </div>
        </div>
      </div>

      {actionError && <p className="text-xs text-red-400">{t('management.tools.actionFailed')}</p>}

      {/* 类型筛选 */}
      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              filter === f
                ? 'bg-primary text-primary-foreground'
                : 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
            )}
          >
            {t(`management.tools.filter.${f}`)}
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
      ) : filteredTools.length === 0 ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('management.tools.empty')}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filteredTools.map((tool) => (
            <div key={tool.id} className="glass-panel flex flex-col gap-2 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{tool.name}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-1">
                    <span className="rounded bg-secondary/15 px-1.5 py-0.5 text-[10px] text-secondary">
                      {t(`management.tools.type.${tool.type}`)}
                    </span>
                    <span
                      className={cn(
                        'rounded px-1.5 py-0.5 text-[10px] font-medium',
                        tool.status === 'active'
                          ? 'bg-emerald-500/15 text-emerald-400'
                          : tool.status === 'error'
                            ? 'bg-red-500/15 text-red-400'
                            : 'bg-[rgba(255,255,255,0.08)] text-muted-foreground',
                      )}
                    >
                      {t(`management.tools.status.${tool.status}`)}
                    </span>
                  </div>
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    onClick={() => void handleToggle(tool)}
                    aria-label={t('management.tools.toggle')}
                    title={t('management.tools.toggle')}
                    className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                  >
                    <Power className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setTesting(tool)}
                    aria-label={t('management.tools.test')}
                    title={t('management.tools.test')}
                    className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                  >
                    <FlaskConical className="h-3.5 w-3.5" />
                  </button>
                  {tool.type === 'custom' && (
                    <button
                      type="button"
                      onClick={() => void handleDelete(tool)}
                      aria-label={t('management.tools.delete')}
                      title={t('management.tools.delete')}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-400"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>

              <p className="line-clamp-2 min-h-[1.25rem] text-xs text-muted-foreground">
                {tool.description || t('management.tools.noDescription')}
              </p>

              {paramSummary(tool.parameters) && (
                <p className="truncate font-mono text-[10px] text-muted-foreground/80">
                  {paramSummary(tool.parameters)}
                </p>
              )}

              <p className="border-t border-[var(--glass-border)] pt-2 text-[10px] text-muted-foreground/70">
                {t('management.tools.useCount', { count: tool.use_count })}
              </p>
            </div>
          ))}
        </div>
      )}

      {testing && <TestToolModal tool={testing} onClose={() => setTesting(null)} />}
    </div>
  );
}
