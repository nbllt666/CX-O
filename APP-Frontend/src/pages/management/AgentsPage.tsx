/**
 * 代理页（SubTask 7.1）
 *
 * 功能口径对齐 CX-O-Frontend AgentsPage：
 * - 统计行：Agent 总数 / 默认 Agent / 可用模型数
 * - Agent 卡片列表：名称（默认徽章）、描述、模型 / 温度 / 记忆场景、更新时间
 * - 操作：新建 / 编辑（名称、描述、系统提示词、模型下拉、温度、记忆场景）、克隆、删除
 *   （默认 Agent 不可删除/克隆操作仍允许，与参考前端一致仅隐藏删除）
 * - 加载失败展示错误态并可重试
 *
 * 数据全部来自 agentsApi（getAgents / getAvailableModels / createAgent /
 * updateAgent / cloneAgent / deleteAgent），本地 useState + useEffect，无 react-query。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Bot,
  Copy,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { agentsApi } from '@/api/clients/agents';
import type { Agent } from '@/api/types';
import { cn } from '@/lib/utils';

type MemoryScene = 'chat' | 'task' | 'first_interaction';

interface AgentForm {
  name: string;
  description: string;
  system_prompt: string;
  model: string;
  temperature: number;
  memory_scene: MemoryScene;
  voice_memory_fast: boolean;
}

const EMPTY_FORM: AgentForm = {
  name: '',
  description: '',
  system_prompt: '',
  model: '',
  temperature: 0.7,
  memory_scene: 'chat',
  voice_memory_fast: false,
};

const SCENES: MemoryScene[] = ['chat', 'task', 'first_interaction'];

/** 新建 / 编辑弹窗 */
function AgentFormModal(props: {
  agent: Agent | null;
  models: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const isEdit = props.agent !== null;
  const [form, setForm] = useState<AgentForm>(() =>
    props.agent
      ? {
          name: props.agent.name,
          description: props.agent.description ?? '',
          system_prompt: props.agent.system_prompt ?? '',
          model: props.agent.model ?? '',
          temperature: props.agent.temperature ?? 0.7,
          memory_scene: (props.agent.memory_scene as MemoryScene) ?? 'chat',
          voice_memory_fast: props.agent.voice_memory_fast ?? false,
        }
      : { ...EMPTY_FORM, model: props.models[0] ?? '' },
  );
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);

  const patch = (p: Partial<AgentForm>) => setForm((prev) => ({ ...prev, ...p }));

  const handleSave = async () => {
    if (!form.name.trim() || isSaving) return;
    setIsSaving(true);
    setSaveError(false);
    const payload: Partial<Agent> = {
      name: form.name.trim(),
      description: form.description.trim(),
      system_prompt: form.system_prompt,
      model: form.model || undefined,
      temperature: form.temperature,
      memory_scene: form.memory_scene,
      voice_memory_fast: form.voice_memory_fast,
    };
    try {
      if (isEdit && props.agent) {
        await agentsApi.updateAgent(props.agent.id, payload);
      } else {
        await agentsApi.createAgent({ ...payload, use_memory: true, use_tools: true });
      }
      props.onSaved();
      props.onClose();
    } catch (error) {
      console.error('Agent save failed:', error);
      setSaveError(true);
    } finally {
      setIsSaving(false);
    }
  };

  const inputCls =
    'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="glass-panel max-h-[85vh] w-full max-w-lg space-y-4 overflow-y-auto p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {t(isEdit ? 'management.agents.editTitle' : 'management.agents.createTitle')}
          </h2>
          <button
            type="button"
            onClick={props.onClose}
            aria-label={t('management.agents.close')}
            className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.agents.fieldName')}
          </label>
          <input
            value={form.name}
            onChange={(e) => patch({ name: e.target.value })}
            aria-label={t('management.agents.fieldName')}
            className={inputCls}
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.agents.fieldDescription')}
          </label>
          <input
            value={form.description}
            onChange={(e) => patch({ description: e.target.value })}
            aria-label={t('management.agents.fieldDescription')}
            className={inputCls}
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.agents.fieldPrompt')}
          </label>
          <textarea
            value={form.system_prompt}
            onChange={(e) => patch({ system_prompt: e.target.value })}
            rows={4}
            aria-label={t('management.agents.fieldPrompt')}
            className={cn(inputCls, 'resize-none')}
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t('management.agents.fieldModel')}
            </label>
            <select
              value={form.model}
              onChange={(e) => patch({ model: e.target.value })}
              aria-label={t('management.agents.fieldModel')}
              className={inputCls}
            >
              {props.models.length === 0 && <option value="">main</option>}
              {props.models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
              {t('management.agents.fieldScene')}
            </label>
            <select
              value={form.memory_scene}
              onChange={(e) => patch({ memory_scene: e.target.value as MemoryScene })}
              aria-label={t('management.agents.fieldScene')}
              className={inputCls}
            >
              {SCENES.map((s) => (
                <option key={s} value={s}>
                  {t(`management.agents.scene.${s}`)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.agents.fieldTemperature')}：{form.temperature.toFixed(2)}
          </label>
          <input
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={form.temperature}
            onChange={(e) => patch({ temperature: Number(e.target.value) })}
            aria-label={t('management.agents.fieldTemperature')}
            className="w-full accent-primary"
          />
        </div>

        <div className="flex items-start justify-between gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2.5">
          <div>
            <label className="block text-xs font-medium text-muted-foreground">
              {t('management.agents.fieldVoiceMemoryFast')}
            </label>
            <p className="mt-0.5 text-[11px] opacity-60">
              {t('management.agents.voiceMemoryFastHint')}
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={form.voice_memory_fast}
            aria-label={t('management.agents.fieldVoiceMemoryFast')}
            onClick={() => patch({ voice_memory_fast: !form.voice_memory_fast })}
            className={cn(
              'relative h-6 w-11 shrink-0 rounded-full transition-colors',
              form.voice_memory_fast ? 'bg-primary' : 'bg-[rgba(255,255,255,0.15)]',
            )}
          >
            <span
              className={cn(
                'absolute top-0.5 h-5 w-5 rounded-full bg-white transition-transform',
                form.voice_memory_fast ? 'translate-x-[22px]' : 'translate-x-0.5',
              )}
            />
          </button>
        </div>

        {saveError && (
          <p className="text-xs text-red-400">{t('management.agents.saveFailed')}</p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={props.onClose}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.agents.cancel')}
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!form.name.trim() || isSaving}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {isSaving ? t('management.agents.saving') : t('management.agents.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [actionError, setActionError] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const [agentList, modelResp] = await Promise.all([
        agentsApi.getAgents(),
        agentsApi.getAvailableModels().catch(() => ({ models: [] as string[] })),
      ]);
      // 过滤系统内置的 memory-agent（记忆管理助手不在智能体列表中展示）
      setAgents(agentList.filter((a) => a.id !== 'memory-agent'));
      setModels(modelResp.models || []);
    } catch (error) {
      console.error('Agents load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleClone = async (agent: Agent) => {
    setActionError(false);
    try {
      await agentsApi.cloneAgent(agent.id);
      await load();
    } catch (error) {
      console.error('Agent clone failed:', error);
      setActionError(true);
    }
  };

  const handleDelete = async (agent: Agent) => {
    if (!window.confirm(t('management.agents.deleteConfirm', { name: agent.name }))) return;
    setActionError(false);
    try {
      await agentsApi.deleteAgent(agent.id);
      await load();
    } catch (error) {
      console.error('Agent delete failed:', error);
      setActionError(true);
    }
  };

  const defaultAgent = agents.find((a) => a.is_default);

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.agents.subtitle')}</p>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => void load()}
            aria-label={t('management.agents.refresh')}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t('management.agents.refresh')}
          </button>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85"
          >
            <Plus className="h-3.5 w-3.5" />
            {t('management.agents.create')}
          </button>
        </div>
      </div>

      {/* 统计行 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.agents.statsTotal')}</p>
            <p className="text-2xl font-bold tabular-nums">{agents.length}</p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary/15 text-secondary">
            <Sparkles className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.agents.statsDefault')}</p>
            <p className="truncate text-lg font-semibold">
              {defaultAgent ? defaultAgent.name : t('management.agents.statsNone')}
            </p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent">
            <RefreshCw className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.agents.statsModels')}</p>
            <p className="text-2xl font-bold tabular-nums">{models.length}</p>
          </div>
        </div>
      </div>

      {actionError && (
        <p className="text-xs text-red-400">{t('management.agents.actionFailed')}</p>
      )}

      {/* 列表 */}
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
      ) : agents.length === 0 ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('management.agents.empty')}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {agents.map((agent) => (
            <div key={agent.id} className="glass-panel flex flex-col gap-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-sm font-semibold">{agent.name}</span>
                  {agent.is_default && (
                    <span className="shrink-0 rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                      {t('management.agents.defaultBadge')}
                    </span>
                  )}
                </div>
                <div className="flex shrink-0 gap-1">
                  <button
                    type="button"
                    onClick={() => setEditing(agent)}
                    aria-label={t('management.agents.edit')}
                    title={t('management.agents.edit')}
                    className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleClone(agent)}
                    aria-label={t('management.agents.clone')}
                    title={t('management.agents.clone')}
                    className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </button>
                  {!agent.is_default && (
                    <button
                      type="button"
                      onClick={() => void handleDelete(agent)}
                      aria-label={t('management.agents.delete')}
                      title={t('management.agents.delete')}
                      className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-400"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>

              <p className="line-clamp-2 min-h-[1.25rem] text-xs text-muted-foreground">
                {agent.description || t('management.agents.noDescription')}
              </p>

              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span>
                  {t('management.agents.cardModel')}：{agent.model || 'main'}
                </span>
                <span>
                  {t('management.agents.cardTemperature')}：{(agent.temperature ?? 0.7).toFixed(2)}
                </span>
                <span>
                  {t('management.agents.cardScene')}：
                  {t(`management.agents.scene.${agent.memory_scene ?? 'chat'}`)}
                </span>
              </div>

              {agent.updated_at && (
                <p className="border-t border-[var(--glass-border)] pt-2 text-[10px] text-muted-foreground/70">
                  {t('management.agents.updatedAt')}：{agent.updated_at}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <AgentFormModal
          agent={null}
          models={models}
          onClose={() => setShowCreate(false)}
          onSaved={() => void load()}
        />
      )}
      {editing && (
        <AgentFormModal
          agent={editing}
          models={models}
          onClose={() => setEditing(null)}
          onSaved={() => void load()}
        />
      )}
    </div>
  );
}
