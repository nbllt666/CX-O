/**
 * ACP 页（SubTask 7.1）
 *
 * 功能口径对齐 CX-O-Frontend AcpPage + MemoriesPage ACP 消息视图：
 * - 统计行：代理总数 / 活跃代理 / 消息总数
 * - 代理列表：名称、描述、能力标签、状态徽章（活跃/停用）
 * - 操作：新建 / 编辑（名称、描述、能力标签）、切换启停状态、删除
 * - 消息互通：选择代理后查看 ACP 消息历史，可发送 ACP 消息（触发对方自动回复）
 *
 * 数据全部来自 agentsApi（getAcpStats / getAcpAgents / createAcpAgent /
 * updateAcpAgent / deleteAcpAgent / getAcpMessages / sendAcpMessage）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Bot,
  MessageSquare,
  Pencil,
  Plus,
  Power,
  RefreshCw,
  Send,
  Trash2,
  X,
} from 'lucide-react';
import { agentsApi } from '@/api/clients/agents';
import type { AcpAgentRow, AcpMessage, AcpStats } from '@/api/types';
import { cn } from '@/lib/utils';

interface AcpForm {
  name: string;
  description: string;
  capabilities: string;
}

const EMPTY_FORM: AcpForm = { name: '', description: '', capabilities: '' };

/** loadMessages 单调请求序号（模块级，M5）：快速切换 agent 时旧响应不得覆盖最新选择的消息流 */
let loadMessagesSeq = 0;

/** 从 ACP 消息 content 中提取可读文本 */
function extractMessageText(content: AcpMessage['content']): string {
  if (typeof content === 'string') return content;
  const text = content?.text;
  if (typeof text === 'string') return text;
  return JSON.stringify(content);
}

/** 新建 / 编辑弹窗 */
function AcpFormModal(props: {
  agent: AcpAgentRow | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const isEdit = props.agent !== null;
  const [form, setForm] = useState<AcpForm>(() =>
    props.agent
      ? {
          name: props.agent.name,
          description: props.agent.description ?? '',
          capabilities: (props.agent.capabilities ?? []).join(', '),
        }
      : { ...EMPTY_FORM },
  );
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);

  const patch = (p: Partial<AcpForm>) => setForm((prev) => ({ ...prev, ...p }));

  const handleSave = async () => {
    if (!form.name.trim() || isSaving) return;
    setIsSaving(true);
    setSaveError(false);
    const capabilities = form.capabilities
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      if (isEdit && props.agent) {
        await agentsApi.updateAcpAgent(props.agent.id, {
          name: form.name.trim(),
          description: form.description.trim(),
          capabilities,
        });
      } else {
        await agentsApi.createAcpAgent({
          name: form.name.trim(),
          description: form.description.trim(),
          capabilities,
        });
      }
      props.onSaved();
      props.onClose();
    } catch (error) {
      console.error('ACP agent save failed:', error);
      setSaveError(true);
    } finally {
      setIsSaving(false);
    }
  };

  const inputCls =
    'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm">
      <div className="glass-panel w-full max-w-md space-y-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">
            {t(isEdit ? 'management.acp.editTitle' : 'management.acp.createTitle')}
          </h2>
          <button
            type="button"
            onClick={props.onClose}
            aria-label={t('management.acp.close')}
            className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.acp.fieldName')}
          </label>
          <input
            value={form.name}
            onChange={(e) => patch({ name: e.target.value })}
            aria-label={t('management.acp.fieldName')}
            className={inputCls}
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.acp.fieldDescription')}
          </label>
          <input
            value={form.description}
            onChange={(e) => patch({ description: e.target.value })}
            aria-label={t('management.acp.fieldDescription')}
            className={inputCls}
          />
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
            {t('management.acp.fieldCapabilities')}
          </label>
          <input
            value={form.capabilities}
            onChange={(e) => patch({ capabilities: e.target.value })}
            placeholder={t('management.acp.capabilitiesHint')}
            aria-label={t('management.acp.fieldCapabilities')}
            className={inputCls}
          />
        </div>

        {saveError && <p className="text-xs text-red-400">{t('management.acp.saveFailed')}</p>}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={props.onClose}
            className="rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            {t('management.acp.cancel')}
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!form.name.trim() || isSaving}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {isSaving ? t('management.acp.saving') : t('management.acp.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AcpPage() {
  const { t } = useTranslation();
  const [stats, setStats] = useState<AcpStats | null>(null);
  const [agents, setAgents] = useState<AcpAgentRow[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<AcpAgentRow | null>(null);
  const [actionError, setActionError] = useState(false);

  const [selected, setSelected] = useState<AcpAgentRow | null>(null);
  const [messages, setMessages] = useState<AcpMessage[]>([]);
  const [msgInput, setMsgInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState(false);
  // M5：toggle/delete 行操作进行中的 agent id 集，进行中禁用对应按钮防连点重复请求
  const [pendingIds, setPendingIds] = useState<ReadonlySet<string>>(new Set());

  // M5：卸载标记——loadMessages 的迟到响应在卸载后不得写入 state
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /** 标记/清除某个 agent 的行操作进行中状态 */
  const setAgentPending = useCallback((id: string, pending: boolean) => {
    setPendingIds((prev) => {
      if (pending === prev.has(id)) return prev;
      const next = new Set(prev);
      if (pending) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError(false);
    try {
      const [statsResp, agentList] = await Promise.all([
        agentsApi.getAcpStats().catch(() => null),
        agentsApi.getAcpAgents(),
      ]);
      setStats(statsResp);
      setAgents(agentList);
    } catch (error) {
      console.error('ACP load failed:', error);
      setLoadError(true);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const loadMessages = useCallback(async (agentId: string) => {
    // M5：发起即占用新代际；await 返回时比对序号与挂载标记，过期/卸载响应丢弃
    const seq = ++loadMessagesSeq;
    try {
      const resp = await agentsApi.getAcpMessages(agentId, 50);
      if (seq !== loadMessagesSeq || !mountedRef.current) return;
      setMessages(resp.messages || []);
    } catch (error) {
      console.error('ACP messages load failed:', error);
      if (seq !== loadMessagesSeq || !mountedRef.current) return;
      setMessages([]);
    }
  }, []);

  const handleSelect = (agent: AcpAgentRow) => {
    setSelected(agent);
    void loadMessages(agent.id);
  };

  const handleToggle = async (agent: AcpAgentRow) => {
    // M5：进行中守卫 + pendingIds 标记，完成/失败后移除
    if (pendingIds.has(agent.id)) return;
    setAgentPending(agent.id, true);
    setActionError(false);
    try {
      await agentsApi.updateAcpAgent(agent.id, {
        status: agent.status === 'active' ? 'inactive' : 'active',
      });
      await load();
    } catch (error) {
      console.error('ACP toggle failed:', error);
      setActionError(true);
    } finally {
      setAgentPending(agent.id, false);
    }
  };

  const handleDelete = async (agent: AcpAgentRow) => {
    if (!window.confirm(t('management.acp.deleteConfirm', { name: agent.name }))) return;
    if (pendingIds.has(agent.id)) return;
    setAgentPending(agent.id, true);
    setActionError(false);
    try {
      await agentsApi.deleteAcpAgent(agent.id);
      if (selected?.id === agent.id) {
        setSelected(null);
        setMessages([]);
      }
      await load();
    } catch (error) {
      console.error('ACP delete failed:', error);
      setActionError(true);
    } finally {
      setAgentPending(agent.id, false);
    }
  };

  const handleSend = async () => {
    const text = msgInput.trim();
    if (!text || !selected || isSending) return;
    setIsSending(true);
    setSendError(false);
    try {
      await agentsApi.sendAcpMessage(selected.id, text);
      setMsgInput('');
      await loadMessages(selected.id);
    } catch (error) {
      console.error('ACP send failed:', error);
      setSendError(true);
    } finally {
      setIsSending(false);
    }
  };

  const activeCount = agents.filter((a) => a.status === 'active').length;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.acp.subtitle')}</p>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => void load()}
            aria-label={t('management.acp.refresh')}
            className="flex items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            {t('management.acp.refresh')}
          </button>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85"
          >
            <Plus className="h-3.5 w-3.5" />
            {t('management.acp.create')}
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
            <p className="text-xs text-muted-foreground">{t('management.acp.statsTotal')}</p>
            <p className="text-2xl font-bold tabular-nums">
              {stats?.total_agents ?? agents.length}
            </p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-secondary/15 text-secondary">
            <Activity className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.acp.statsActive')}</p>
            <p className="text-2xl font-bold tabular-nums">{stats?.active_agents ?? activeCount}</p>
          </div>
        </div>
        <div className="glass-panel flex items-center gap-4 p-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-accent/15 text-accent">
            <MessageSquare className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">{t('management.acp.statsMessages')}</p>
            <p className="text-2xl font-bold tabular-nums">{stats?.total_messages ?? 0}</p>
          </div>
        </div>
      </div>

      {actionError && <p className="text-xs text-red-400">{t('management.acp.actionFailed')}</p>}

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
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* 代理列表 */}
          <div className="glass-panel space-y-1 p-3">
            <h2 className="px-2 pb-2 text-sm font-semibold">{t('management.acp.listTitle')}</h2>
            {agents.length === 0 ? (
              <p className="p-6 text-center text-sm text-muted-foreground">
                {t('management.acp.empty')}
              </p>
            ) : (
              agents.map((agent) => (
                <div
                  key={agent.id}
                  onClick={() => handleSelect(agent)}
                  className={cn(
                    'cursor-pointer rounded-lg p-3 transition-colors hover:bg-[rgba(255,255,255,0.05)]',
                    selected?.id === agent.id && 'bg-[rgba(255,183,225,0.08)]',
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">{agent.name}</span>
                        <span
                          className={cn(
                            'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium',
                            agent.status === 'active'
                              ? 'bg-emerald-500/15 text-emerald-400'
                              : 'bg-[rgba(255,255,255,0.08)] text-muted-foreground',
                          )}
                        >
                          {agent.status === 'active'
                            ? t('management.acp.statusActive')
                            : t('management.acp.statusInactive')}
                        </span>
                      </div>
                      {agent.description && (
                        <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                          {agent.description}
                        </p>
                      )}
                      {agent.capabilities && agent.capabilities.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {agent.capabilities.map((cap) => (
                            <span
                              key={cap}
                              className="rounded bg-secondary/15 px-1.5 py-0.5 text-[10px] text-secondary"
                            >
                              {cap}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleToggle(agent);
                        }}
                        aria-label={t('management.acp.toggleStatus')}
                        title={t('management.acp.toggleStatus')}
                        disabled={pendingIds.has(agent.id)}
                        className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Power className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditing(agent);
                        }}
                        aria-label={t('management.acp.edit')}
                        title={t('management.acp.edit')}
                        className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.08)] hover:text-foreground"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(agent);
                        }}
                        aria-label={t('management.acp.delete')}
                        title={t('management.acp.delete')}
                        disabled={pendingIds.has(agent.id)}
                        className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-red-500/10 hover:text-red-400 disabled:cursor-not-allowed disabled:opacity-40"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* 消息互通 */}
          <div className="glass-panel flex min-h-[20rem] flex-col p-4">
            <h2 className="pb-2 text-sm font-semibold">
              {selected
                ? t('management.acp.msgTitle') + `：${selected.name}`
                : t('management.acp.msgSelect')}
            </h2>
            {selected && (
              <>
                <div className="flex-1 space-y-2 overflow-y-auto py-2">
                  {messages.length === 0 ? (
                    <p className="py-8 text-center text-xs text-muted-foreground">
                      {t('management.acp.msgEmpty')}
                    </p>
                  ) : (
                    messages
                      .slice()
                      .reverse()
                      .map((msg) => (
                        <div
                          key={msg.id}
                          className={cn(
                            'max-w-[85%] rounded-lg px-3 py-2 text-xs',
                            msg.is_sent
                              ? 'ml-auto bg-primary/15 text-foreground'
                              : 'bg-[rgba(255,255,255,0.06)] text-foreground',
                          )}
                        >
                          <p className="mb-0.5 text-[10px] text-muted-foreground">
                            {msg.is_sent
                              ? t('management.acp.fromMe')
                              : `${t('management.acp.fromPeer')} · ${msg.from_agent_name}`}
                          </p>
                          <p className="whitespace-pre-wrap break-words">
                            {extractMessageText(msg.content)}
                          </p>
                        </div>
                      ))
                  )}
                </div>
                <div className="flex items-center gap-2 border-t border-[var(--glass-border)] pt-3">
                  <input
                    value={msgInput}
                    onChange={(e) => setMsgInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        void handleSend();
                      }
                    }}
                    placeholder={t('management.acp.msgPlaceholder', { name: selected.name })}
                    aria-label={t('management.acp.msgPlaceholder', { name: selected.name })}
                    disabled={isSending}
                    className="flex-1 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none disabled:opacity-50"
                  />
                  <button
                    type="button"
                    onClick={() => void handleSend()}
                    disabled={isSending || !msgInput.trim()}
                    aria-label={t('management.acp.msgSend')}
                    className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
                  >
                    <Send className="h-3.5 w-3.5" />
                    {isSending ? t('management.acp.msgSending') : t('management.acp.msgSend')}
                  </button>
                </div>
                {sendError && (
                  <p className="pt-2 text-xs text-red-400">{t('management.acp.sendFailed')}</p>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {showCreate && (
        <AcpFormModal
          agent={null}
          onClose={() => setShowCreate(false)}
          onSaved={() => void load()}
        />
      )}
      {editing && (
        <AcpFormModal
          agent={editing}
          onClose={() => setEditing(null)}
          onSaved={() => void load()}
        />
      )}
    </div>
  );
}
