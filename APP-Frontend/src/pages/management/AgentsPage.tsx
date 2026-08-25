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
  Laptop,
  Mic,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import { agentsApi } from '@/api/clients/agents';
import { audioApi } from '@/api/clients/audio';
import type { RefAudioAsset } from '@/api/clients/audio';
import type { Agent } from '@/api/types';
import { cn } from '@/lib/utils';
import { isElectron } from '@/lib/isElectron';
import { usePetPanelStore } from '@/store/petPanelStore';

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

/** 参考音频资产列表里取人类可读标签（提示词 > 文件名 > 注释 > id） */
function assetLabel(asset: RefAudioAsset): string {
  if (asset.source === 'prompt' && asset.prompt) return asset.prompt;
  return asset.file_name || asset.note || asset.id;
}

/** 单 agent 的参考音频/音色绑定控件（下拉选资产 → 设为音色 / 清除） */
function AgentRefAudioControl(props: {
  agent: Agent;
  assets: RefAudioAsset[];
  assetsError: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [pending, setPending] = useState('');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);
  const bound = props.agent.ref_audio_asset_id ?? null;

  const describeError = (error: unknown): string => {
    const msg = error instanceof Error ? error.message : String(error);
    const clean = msg.replace(/^请求失败:\s*/, '').trim();
    // 后端 404：参考音频资产不存在或已删除 / Agent 不存在，统一按"资产不可用"提示
    if (/不存在|已删除/i.test(clean)) return t('management.agents.refAudioAssetMissing');
    return t('management.agents.refAudioSaveFailed');
  };

  const handleSet = async () => {
    if (!pending || busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      await audioApi.setAgentRefAudio(props.agent.id, { asset_id: pending });
      setFeedback({ kind: 'ok', text: t('management.agents.refAudioSetSuccess') });
      setPending('');
      props.onChanged();
    } catch (error) {
      console.error('Set agent ref audio failed:', error);
      setFeedback({ kind: 'err', text: describeError(error) });
    } finally {
      setBusy(false);
    }
  };

  const handleClear = async () => {
    if (!bound || busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      await audioApi.clearAgentRefAudio(props.agent.id);
      setFeedback({ kind: 'ok', text: t('management.agents.refAudioClearSuccess') });
      props.onChanged();
    } catch (error) {
      console.error('Clear agent ref audio failed:', error);
      setFeedback({ kind: 'err', text: describeError(error) });
    } finally {
      setBusy(false);
    }
  };

  const showAssetsState = () => {
    if (props.assetsError) return <p className="text-xs text-red-400">{t('management.agents.refAudioLoadFailed')}</p>;
    if (props.assets.length === 0) return <p className="text-xs text-muted-foreground">{t('management.agents.refAudioNone')}</p>;
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        <select
          value={pending}
          onChange={(e) => setPending(e.target.value)}
          aria-label={t('management.agents.refAudioTitle')}
          className="min-w-0 flex-1 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-2 py-1.5 text-xs focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        >
          <option value="">{bound ? assetLabel(props.assets.find((a) => a.id === bound)!) : t('management.agents.refAudioNotBound')}</option>
          {props.assets.map((a) => (
            <option key={a.id} value={a.id}>
              {assetLabel(a)}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void handleSet()}
          disabled={!pending || busy}
          className="rounded-lg bg-primary px-2.5 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {t('management.agents.refAudioSet')}
        </button>
        <button
          type="button"
          onClick={() => void handleClear()}
          disabled={!bound || busy}
          className="rounded-lg border border-[var(--glass-border)] px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
        >
          {t('management.agents.refAudioClear')}
        </button>
      </div>
    );
  };

  return (
    <div className="border-t border-[var(--glass-border)] pt-2">
      <div className="mb-1.5 flex items-center gap-1.5">
        <Mic className="h-3.5 w-3.5 text-primary" />
        <span className="text-xs font-medium text-muted-foreground">{t('management.agents.refAudioTitle')}</span>
        {bound && props.assets.some((a) => a.id === bound) && (
          <span className="truncate text-xs text-primary">{assetLabel(props.assets.find((a) => a.id === bound)!)}</span>
        )}
      </div>
      {showAssetsState()}
      {feedback && (
        <p className={cn('mt-1 text-xs', feedback.kind === 'ok' ? 'text-emerald-400' : 'text-red-400')}>
          {feedback.text}
        </p>
      )}
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
  const [refAssets, setRefAssets] = useState<RefAudioAsset[]>([]);
  const [refAssetsError, setRefAssetsError] = useState(false);

  // 桌宠多开：开启状态持久化记忆；开/关经 IPC 调主进程建/关对应桌宠窗
  const petOpenIds = usePetPanelStore((s) => s.openAgentIds);
  const petSetOpen = usePetPanelStore((s) => s.setOpen);

  const handlePetToggle = (agent: Agent) => {
    if (!isElectron()) return;
    const currentlyOpen = petOpenIds.includes(agent.id);
    if (currentlyOpen) {
      void window.electronAPI?.closePet(agent.id);
      petSetOpen(agent.id, false);
    } else {
      void window.electronAPI?.openPet(agent.id);
      petSetOpen(agent.id, true);
    }
  };

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    setRefAssetsError(false);
    try {
      const [agentList, modelResp, assetResp] = await Promise.all([
        agentsApi.getAgents(),
        agentsApi.getAvailableModels().catch(() => ({ models: [] as string[] })),
        audioApi.listRefAudioAssets().catch((error) => {
          console.error('Ref audio assets load failed:', error);
          setRefAssetsError(true);
          return { assets: [] as RefAudioAsset[], current_asset_id: null };
        }),
      ]);
      // 过滤系统内置的 memory-agent（记忆管理助手不在智能体列表中展示）
      setAgents(agentList.filter((a) => a.id !== 'memory-agent'));
      setModels(modelResp.models || []);
      setRefAssets(assetResp.assets || []);
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

      {/* 桌宠多开面板：列出全部 agent，显示各桌宠是否已开启，提供开/关（仅 Electron 生效） */}
      <div className="glass-panel p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <Laptop className="h-4 w-4 text-primary" />
            {t('management.petPanel.title')}
          </p>
          <span className="text-xs text-muted-foreground">{t('management.petPanel.hint')}</span>
        </div>
        {!isElectron() ? (
          <p className="text-xs text-muted-foreground">{t('management.petPanel.browserOnly')}</p>
        ) : agents.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t('management.petPanel.none')}</p>
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {agents.map((agent) => {
              const open = petOpenIds.includes(agent.id);
              return (
                <div
                  key={agent.id}
                  className={cn(
                    'flex items-center justify-between gap-2 rounded-lg border px-3 py-2',
                    open
                      ? 'border-[var(--color-primary)] bg-primary/10'
                      : 'border-[var(--glass-border)]',
                  )}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm">{agent.name}</span>
                    {open ? (
                      <span className="shrink-0 rounded bg-primary/15 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        {t('management.petPanel.running')}
                      </span>
                    ) : (
                      <span className="shrink-0 rounded bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {t('management.petPanel.stopped')}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    aria-label={`${open ? t('management.petPanel.close') : t('management.petPanel.open')} ${agent.name}`}
                    title={open ? t('management.petPanel.close') : t('management.petPanel.open')}
                    onClick={() => handlePetToggle(agent)}
                    className={cn(
                      'flex shrink-0 items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs transition-colors',
                      open
                        ? 'bg-primary/85 text-primary-foreground hover:opacity-85'
                        : 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
                    )}
                  >
                    <Power className="h-3.5 w-3.5" />
                    {open ? t('management.petPanel.close') : t('management.petPanel.open')}
                  </button>
                </div>
              );
            })}
          </div>
        )}
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

              <AgentRefAudioControl
                agent={agent}
                assets={refAssets}
                assetsError={refAssetsError}
                onChanged={() => void load()}
              />

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
