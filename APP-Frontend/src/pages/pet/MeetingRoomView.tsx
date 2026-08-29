/**
 * 会议室视图（管理界面加入口，路由 /meeting）。
 *
 * 多 Agent 语音会议协调器的前端控制台：
 * - 建会：选若干 Agent 参与者 → POST /api/meeting/start
 * - 会议中：展示房间状态/参与者/当前发言者（token_holder）
 * - 操作：并入/移出 Agent、用户发言（POST speak 触发发言权仲裁）、结束会议
 * - 视觉提示：轮询拉到当下发言者后由 useMeetingWebSocket 广播给各桌宠窗（说话高亮）
 *
 * 字段全部以 CX-O-SERVER/server/core/meeting/ 的模型为准。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AtSign,
  Bot,
  Eye,
  EyeOff,
  Loader2,
  MessageSquarePlus,
  Mic,
  Play,
  Square,
  UserMinus,
  UserPlus,
  Video,
} from 'lucide-react';
import { agentsApi } from '@/api/clients/agents';
import type { Agent } from '@/api/types';
import type { MeetingAgentSpec, MeetingRecentMessage } from '@/api/clients/meeting';
import { useMeetingWebSocket } from '@/hooks/useMeetingWebSocket';
import { Button } from '@/components/ui-v2/button';
import { Card, CardBody, CardHeader } from '@/components/ui-v2/card';
import { Badge } from '@/components/ui-v2/badge';
import { cn } from '@/lib/utils';
import { isElectron } from '@/lib/isElectron';

/** 会议操作忙碌动作枚举（busy 守卫的粒度） */
type MeetingBusyAction = 'start' | 'speak' | 'join' | 'leave' | 'end' | 'toggle-audience';

export default function MeetingRoomView() {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [userName, setUserName] = useState('user');
  const [selected, setSelected] = useState<string[]>([]);
  const [speakText, setSpeakText] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [speakResult, setSpeakResult] = useState<string | null>(null);
  const [activeRoomId, setActiveRoomId] = useState<string | null>(null);
  // 建会面板：是否开启观众席（随 start 提交）
  const [startWithAudience, setStartWithAudience] = useState(false);
  // 输入框当前点名的 agent_id（@agent 快捷点名；发言时作为 speak.mention）
  const [mentionTarget, setMentionTarget] = useState<string | null>(null);
  // 会议操作忙碌标记（对齐 DreamPage busyAction 模式）：
  // 任一异步会议操作进行中时统一禁用操作按钮，防止并发触发；异步操作 try/finally 复位
  const [busyAction, setBusyAction] = useState<MeetingBusyAction | null>(null);

  const loadAgents = useCallback(async () => {
    try {
      const list = await agentsApi.getAgents();
      const filtered = list.filter((a) => a.id !== 'memory-agent');
      setAgents(filtered);
      setSelected((prev) => (prev.length > 0 ? prev : filtered.map((a) => a.id)));
      setActionError(null);
    } catch {
      setActionError(t('management.meeting.agentsLoadError'));
    } finally {
      setLoaded(true);
    }
  }, [t]);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  // 会议状态订阅：activeRoomId 为空则不轮询；建会后切换到对应房间
  const meeting = useMeetingWebSocket({ roomId: activeRoomId });
  const snapshot = meeting.snapshot;
  const inMeeting = snapshot?.state === 'in_meeting' || snapshot?.state === 'paused';
  const participants = snapshot?.agents ?? [];

  const handleStart = async () => {
    if (busyAction) return;
    setActionError(null);
    if (selected.length === 0) {
      setActionError(t('management.meeting.noParticipants'));
      return;
    }
    const specs: MeetingAgentSpec[] = selected.map((id) => {
      const a = agents.find((x) => x.id === id);
      return { agent_id: id, name: a?.name ?? id };
    });
    setBusyAction('start');
    try {
      const room = await meeting.start({
        user: userName.trim() || 'user',
        agents: specs,
        audience_enabled: startWithAudience,
      });
      if (!room) {
        setActionError(t('management.meeting.startFailed'));
        return;
      }
      setActiveRoomId(room.room_id);
    } finally {
      setBusyAction(null);
    }
  };

  const handleEnd = async () => {
    if (busyAction) return;
    setBusyAction('end');
    try {
      const ok = await meeting.end();
      if (ok) {
        setActiveRoomId(null);
        setSpeakResult(null);
        setActionError(null);
      } else {
        setActionError(t('management.meeting.endFailed'));
      }
    } finally {
      setBusyAction(null);
    }
  };

  const handleSpeak = async () => {
    if (!speakText.trim() || busyAction) return;
    setActionError(null);
    setBusyAction('speak');
    try {
      const res = await meeting.speak(speakText.trim(), {
        role: 'user',
        username: userName.trim() || 'user',
        mention: mentionTarget ?? undefined,
      });
      if (res) {
        setSpeakResult(res.turns.map((tm) => `[${tm.speaker}] ${tm.text}`).join('\n'));
        setSpeakText('');
        setMentionTarget(null);
      } else {
        setSpeakResult(t('management.meeting.speakFailed'));
      }
    } finally {
      setBusyAction(null);
    }
  };

  // @agent 快捷点名：把 @名 插入输入框并记录点名目标（speak 时作为 mention）
  const handleMention = (agent: MeetingAgentSpec) => {
    setMentionTarget(agent.agent_id);
    setSpeakText((prev) => {
      const base = prev.trim() ? `${prev.trim()} ` : '';
      return `${base}@${agent.name || agent.agent_id} `;
    });
  };

  const toggleSelected = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  // 互动空间派生数据：观众席开关状态 + 统一消息流 + 角色身份 meta
  const audienceEnabled = snapshot?.audience_enabled ?? false;
  const messages = snapshot?.recent_messages ?? [];

  const roleMeta = (role: MeetingRecentMessage['role']): { label: string; className: string } => {
    switch (role) {
      case 'audience':
        return { label: t('management.meeting.role.audience'), className: 'text-pink-400' };
      case 'agent':
        return { label: t('management.meeting.role.agent'), className: 'text-primary' };
      default:
        return { label: t('management.meeting.role.user'), className: 'text-sky-400' };
    }
  };

  const handleToggleAudience = async () => {
    if (busyAction) return;
    setActionError(null);
    setBusyAction('toggle-audience');
    try {
      const next = !audienceEnabled;
      const s = await meeting.toggleAudience(next);
      if (!s) setActionError(t('management.meeting.actionFailed'));
    } finally {
      setBusyAction(null);
    }
  };

  // 移出参与者（原内联 then 链提取为具名 handler，纳入 busy 守卫）
  const handleLeave = async (agentId: string) => {
    if (busyAction) return;
    setBusyAction('leave');
    try {
      const r = await meeting.leave(agentId);
      setActionError(r ? null : t('management.meeting.actionFailed'));
    } finally {
      setBusyAction(null);
    }
  };

  // 并入 agent（原内联 then 链提取为具名 handler，纳入 busy 守卫）
  const handleJoin = async (agent: Agent) => {
    if (busyAction) return;
    setBusyAction('join');
    try {
      const r = await meeting.join({ agent_id: agent.id, name: agent.name });
      setActionError(r ? null : t('management.meeting.actionFailed'));
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <p className="text-sm text-muted-foreground">
        {t('management.meeting.subtitle')}
        {!isElectron() && (
          <span className="ml-2 text-xs opacity-60">({t('management.meeting.browserMode')})</span>
        )}
      </p>

      {actionError && <p className="text-xs text-red-400">{actionError}</p>}

      {!loaded ? (
        <div className="glass-panel p-8 text-center text-sm text-muted-foreground">
          {t('common.loading')}
        </div>
      ) : !inMeeting ? (
        // ── 建会面板 ──
        <Card>
          <CardHeader>{t('management.meeting.pickTitle')}</CardHeader>
          <CardBody className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                {t('management.meeting.fieldUser')}
              </label>
              <input
                value={userName}
                onChange={(e) => setUserName(e.target.value)}
                className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
                {t('management.meeting.pickParticipants')}
              </label>
              <div className="flex flex-wrap gap-2">
                {agents.length === 0 ? (
                  <p className="text-xs text-muted-foreground">{t('management.meeting.noAgents')}</p>
                ) : (
                  agents.map((a) => {
                    const on = selected.includes(a.id);
                    return (
                      <button
                        key={a.id}
                        type="button"
                        aria-pressed={on}
                        onClick={() => toggleSelected(a.id)}
                        className={cn(
                          'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors',
                          on
                            ? 'border-[var(--color-primary)] bg-primary/15 text-primary'
                            : 'border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
                        )}
                      >
                        <Bot className="h-3.5 w-3.5" />
                        {a.name}
                      </button>
                    );
                  })
                )}
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-xs text-muted-foreground">
                <Eye className="h-3.5 w-3.5" />
                {t('management.meeting.startWithAudience')}
              </span>
              <button
                type="button"
                data-testid="audience-toggle-start"
                aria-pressed={startWithAudience}
                onClick={() => setStartWithAudience((v) => !v)}
                className={cn(
                  'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors',
                  startWithAudience
                    ? 'border-[var(--color-primary)] bg-primary/15 text-primary'
                    : 'border-[var(--glass-border)] text-muted-foreground',
                )}
              >
                <EyeOff className="h-3.5 w-3.5" />
                {startWithAudience
                  ? t('management.meeting.audienceOn')
                  : t('management.meeting.audienceOff')}
              </button>
            </div>
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                onClick={() => void handleStart()}
                icon={<Play className="h-4 w-4" />}
                disabled={selected.length === 0 || !!busyAction}
              >
                {t('management.meeting.start')}
              </Button>
            </div>
          </CardBody>
        </Card>
      ) : (
        // ── 会议进行中 ──
        <div className="space-y-4">
          <Card>
            <CardHeader className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <Video className="h-4 w-4" />
                {t('management.meeting.liveTitle')}
              </span>
              <div className="flex items-center gap-2">
                {meeting.isPolling && (
                  <Badge variant="secondary">
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    {t('management.meeting.sync')}
                  </Badge>
                )}
                <Badge variant="success">
                  {t(`management.meeting.state.${snapshot?.state ?? 'in_meeting'}`)}
                </Badge>
              </div>
            </CardHeader>
            <CardBody className="space-y-3 text-xs text-muted-foreground">
              <p>
                {t('management.meeting.roomId')}：
                <span className="text-foreground">{snapshot?.room_id}</span>
              </p>
              <p>
                {t('management.meeting.currentSpeaker')}：
                <span className="ml-1 text-foreground">
                  {snapshot?.token_holder ?? t('management.meeting.noSpeaker')}
                </span>
              </p>
              {/* 观众席开关：绑定当前房间 audience_enabled（调 toggleAudience 启停弹幕通道） */}
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  {audienceEnabled ? (
                    <Eye className="h-3.5 w-3.5 text-primary" />
                  ) : (
                    <EyeOff className="h-3.5 w-3.5" />
                  )}
                  {t('management.meeting.audience')}
                </span>
                <button
                  type="button"
                  data-testid="audience-toggle-live"
                  aria-pressed={audienceEnabled}
                  disabled={!!busyAction}
                  onClick={() => void handleToggleAudience()}
                  className={cn(
                    'flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs transition-colors disabled:opacity-50',
                    audienceEnabled
                      ? 'border-[var(--color-primary)] bg-primary/15 text-primary'
                      : 'border-[var(--glass-border)] text-muted-foreground',
                  )}
                >
                  {audienceEnabled
                    ? t('management.meeting.audienceOn')
                    : t('management.meeting.audienceOff')}
                </button>
              </div>
              {meeting.isError && (
                <p className="text-xs text-red-400">{t('management.meeting.statePollError')}</p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>{t('management.meeting.participantsTitle')}</CardHeader>
            <CardBody className="space-y-2">
              {participants.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t('management.meeting.noParticipants')}</p>
              ) : (
                participants.map((p) => {
                  const isSpeaker = p.agent_id === snapshot?.token_holder;
                  return (
                    <div
                      key={p.agent_id}
                      className={cn(
                        'flex items-center justify-between gap-2 rounded-lg border px-3 py-2',
                        isSpeaker
                          ? 'border-[var(--color-primary)] bg-primary/15'
                          : 'border-[var(--glass-border)]',
                      )}
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        {isSpeaker ? (
                          <Mic className="h-4 w-4 shrink-0 text-primary" />
                        ) : (
                          <Bot className="h-4 w-4 shrink-0 text-muted-foreground" />
                        )}
                        <span className="truncate text-sm text-foreground">
                          {p.name || p.agent_id}
                        </span>
                        {isSpeaker &&
                          <Badge variant="anime">{t('management.meeting.speaking')}</Badge>}
                        {!isSpeaker && (
                          <Badge variant="secondary">{t('management.meeting.standby')}</Badge>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!!busyAction}
                        onClick={() => void handleLeave(p.agent_id)}
                        icon={<UserMinus className="h-3.5 w-3.5" />}
                      >
                        {t('management.meeting.leave')}
                      </Button>
                    </div>
                  );
                })
              )}
              {/* 可并入的其余 agent */}
              {agents
                .filter((a) => !participants.some((p) => p.agent_id === a.id))
                .map((a) => (
                  <Button
                    key={a.id}
                    variant="secondary"
                    size="sm"
                    disabled={!!busyAction}
                    onClick={() => void handleJoin(a)}
                    icon={<UserPlus className="h-3.5 w-3.5" />}
                  >
                    {a.name}
                  </Button>
                ))}
            </CardBody>
          </Card>

          {/* 统一消息流：user/audience/agent 三态身份渲染（最近消息） */}
          <Card>
            <CardHeader>{t('management.meeting.recentMessages')}</CardHeader>
            <CardBody className="space-y-2">
              {messages.length === 0 ? (
                <p className="text-xs text-muted-foreground">{t('management.meeting.messageEmpty')}</p>
              ) : (
                <ul className="space-y-2">
                  {messages.map((m, i) => {
                    const meta = roleMeta(m.role);
                    const displayName =
                      m.role === 'user' ? meta.label : m.speaker || meta.label;
                    return (
                      <li
                        key={i}
                        className="rounded-lg border border-[var(--glass-border)] px-3 py-2"
                      >
                        <span className={cn('text-xs font-medium', meta.className)}>
                          {displayName}
                        </span>
                        <p className="mt-1 text-sm text-foreground">{m.text}</p>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>{t('management.meeting.speakTitle')}</CardHeader>
            <CardBody className="space-y-3">
              {/* @agent 快捷点名：点击插入 @名 到输入框并标记点名目标 */}
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <AtSign className="h-3.5 w-3.5" />
                  {t('management.meeting.mention')}
                  {mentionTarget && (
                    <span className="text-primary">@{participants.find((p) => p.agent_id === mentionTarget)?.name || mentionTarget}</span>
                  )}
                </span>
                {participants.map((p) => (
                  <button
                    key={p.agent_id}
                    type="button"
                    data-testid={`mention-${p.agent_id}`}
                    onClick={() => handleMention(p)}
                    className={cn(
                      'flex items-center gap-1 rounded-lg border px-2 py-1 text-xs transition-colors',
                      mentionTarget === p.agent_id
                        ? 'border-[var(--color-primary)] bg-primary/15 text-primary'
                        : 'border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
                    )}
                  >
                    @{p.name || p.agent_id}
                  </button>
                ))}
              </div>
              <textarea
                value={speakText}
                onChange={(e) => setSpeakText(e.target.value)}
                rows={3}
                placeholder={t('management.meeting.speakPlaceholder')}
                className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
              />
              <div className="flex justify-end gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void handleSpeak()}
                  icon={<MessageSquarePlus className="h-4 w-4" />}
                  disabled={!speakText.trim() || !!busyAction}
                >
                  {t('management.meeting.speak')}
                </Button>
                <Button
                  size="sm"
                  onClick={() => void handleEnd()}
                  icon={<Square className="h-4 w-4" />}
                  disabled={!!busyAction}
                >
                  {t('management.meeting.end')}
                </Button>
              </div>
              {speakResult && (
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-black/30 p-3 text-xs text-muted-foreground">
                  {speakResult}
                </pre>
              )}
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  );
}