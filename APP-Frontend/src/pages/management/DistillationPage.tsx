/**
 * 蒸馏页（DistillationPage）
 *
 * 对接 server/core/distillation 的蒸馏工作流，提供三种蒸馏路径：
 * - 单次蒸馏：启动 → 推进（含主动追问应答）→ 终结
 * - 批量切分：超长文本切分 → 分组状态 → 逐会话终结并创建角色卡 Agent
 * - 角色卡导入：上传 PNG/JSON 角色卡 → 解析 → 从角色卡启动蒸馏
 *
 * 数据全部来自 distillationApi（/api/v1/distillation/*）。
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowRight,
  FlaskConical,
  Layers,
  Play,
  RefreshCw,
  Sparkles,
  Upload,
  User,
} from 'lucide-react';
import { Button } from '@/components/ui-v2/button';
import { Card, CardBody, CardHeader } from '@/components/ui-v2/card';
import { Input, Textarea } from '@/components/ui-v2/input';
import { Badge } from '@/components/ui-v2/badge';
import { distillationApi } from '@/api/clients/distillation';
import type {
  AdvanceDistillationResult,
  BatchGroupStatus,
  BatchStartResult,
  DistillationSession,
  DistillationSourceType,
  FinalizeDistillationResult,
  ParseCharacterCardResult,
  StartDistillationResult,
} from '@/api/clients/distillation';
import { cn } from '@/lib/utils';

type Mode = 'single' | 'batch' | 'card';

const SOURCE_TYPES: DistillationSourceType[] = [
  'text',
  'conversation_log',
  'character_card',
  'image',
  'video',
  'audio',
];
const GOALS = ['memory', 'agent', 'memory_and_agent'];

/** 后端状态机 S_* 状态与 agent_action 动作的合法值（用于决定是否走国际化映射，未知值回退原文）。 */
const KNOWN_STATES: ReadonlySet<string> = new Set([
  'S_INIT',
  'S_PREREAD',
  'S_QUESTION',
  'S_REFLECT',
  'S_CROSSVALIDATE',
  'S_EXTRACT',
  'S_STORAGE_DECISION',
  'S_FINALIZE',
  'S_REJECT',
]);
const KNOWN_ACTIONS: ReadonlySet<string> = new Set([
  'ask_user',
  'proceed',
  'reflect',
  'cross_validate',
  'extract',
  'decide',
  'finalize',
  'reject',
]);

const selectCls =
  'w-full px-3 py-2 text-sm rounded-[var(--radius-lg)] bg-[rgba(255,255,255,0.06)] ' +
  'text-[var(--text-primary)] border border-[var(--glass-border)] focus:outline-none ' +
  'focus:ring-2 focus:ring-[var(--color-accent)]';

export default function DistillationPage() {
  const { t } = useTranslation();
  const [mode, setMode] = useState<Mode>('single');

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.distillation.subtitle')}</p>
      </div>

      {/* 模式切换 */}
      <div className="flex flex-wrap gap-2">
        {(Object.keys(MODE_META) as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={cn(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors',
              mode === m
                ? 'bg-primary text-primary-foreground'
                : 'border border-[var(--glass-border)] text-muted-foreground hover:bg-[rgba(255,255,255,0.06)]',
            )}
          >
            {MODE_META[m].icon}
            {t(`management.distillation.mode.${m}`)}
          </button>
        ))}
      </div>

      {mode === 'single' && <SingleDistillation />}
      {mode === 'batch' && <BatchDistillation />}
      {mode === 'card' && <CharacterCardImport />}
    </div>
  );
}

const MODE_META: Record<Mode, { icon: React.ReactNode }> = {
  single: { icon: <Sparkles className="h-3.5 w-3.5" /> },
  batch: { icon: <Layers className="h-3.5 w-3.5" /> },
  card: { icon: <User className="h-3.5 w-3.5" /> },
};

// --------------------------------------------------------------------------- //
// 单次蒸馏
// --------------------------------------------------------------------------- //
function SingleDistillation() {
  const { t } = useTranslation();
  const stateLabel = (val?: string) =>
    val && KNOWN_STATES.has(val) ? t(`management.distillation.states.${val}`) : (val ?? '');
  const actionLabel = (val?: string) =>
    val && KNOWN_ACTIONS.has(val) ? t(`management.distillation.actions.${val}`) : (val ?? '');
  const [sourceType, setSourceType] = useState('text');
  const [sourceRef, setSourceRef] = useState('');
  const [templateId, setTemplateId] = useState('default');
  const [maxTurns, setMaxTurns] = useState(4);
  const [askUser, setAskUser] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [session, setSession] = useState<StartDistillationResult | null>(null);
  const [status, setStatus] = useState<DistillationSession | null>(null);
  const [advanceResult, setAdvanceResult] = useState<AdvanceDistillationResult | null>(null);
  const [userResponse, setUserResponse] = useState('');
  const [finalResult, setFinalResult] = useState<FinalizeDistillationResult | null>(null);

  const handleStart = async () => {
    setBusy(true);
    setError(null);
    setStatus(null);
    setAdvanceResult(null);
    setFinalResult(null);
    try {
      const res = await distillationApi.start({
        source_type: sourceType as DistillationSourceType,
        source_ref: sourceRef,
        template_id: templateId,
        max_turns: maxTurns,
        ask_user_on_ambiguity: askUser,
      });
      setSession(res);
      const st = await distillationApi.getSession(res.session_id);
      setStatus(st);
    } catch (e) {
      console.error('distillation start failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const reloadStatus = async () => {
    if (!session) return;
    setError(null);
    try {
      const st = await distillationApi.getSession(session.session_id);
      setStatus(st);
    } catch (e) {
      console.error('distillation status failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleAdvance = async () => {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const res = await distillationApi.advance(session.session_id, userResponse || undefined);
      setUserResponse('');
      setAdvanceResult(res);
      const st = await distillationApi.getSession(session.session_id);
      setStatus(st);
    } catch (e) {
      console.error('distillation advance failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleFinalize = async () => {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const res = await distillationApi.finalize(session.session_id);
      setFinalResult(res);
      const st = await distillationApi.getSession(session.session_id);
      setStatus(st);
    } catch (e) {
      console.error('distillation finalize failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">{t('management.distillation.singleTitle')}</span>
        </CardHeader>
        <CardBody className="space-y-3">
          <div>
            <label className="mb-1.5 block text-sm font-medium text-[var(--text-secondary)]">
              {t('management.distillation.sourceType')}
            </label>
            <select
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              className={selectCls}
            >
              {SOURCE_TYPES.map((s) => (
                <option key={s} value={s}>
                  {t(`management.distillation.sourceTypes.${s}`)}
                </option>
              ))}
            </select>
          </div>
          <Input
            label={t('management.distillation.templateId')}
            value={templateId}
            onChange={(e) => setTemplateId(e.target.value)}
          />
          <Textarea
            label={t('management.distillation.sourceRef')}
            value={sourceRef}
            onChange={(e) => setSourceRef(e.target.value)}
            placeholder={t('management.distillation.sourceRefPlaceholder')}
            rows={4}
          />
          <div className="flex items-center gap-4">
            <Input
              label={t('management.distillation.maxTurns')}
              type="number"
              min={1}
              max={6}
              value={maxTurns}
              onChange={(e) => setMaxTurns(Number(e.target.value))}
            />
            <label className="flex items-center gap-2 pt-5 text-sm text-[var(--text-secondary)]">
              <input
                type="checkbox"
                checked={askUser}
                onChange={(e) => setAskUser(e.target.checked)}
                className="accent-[var(--color-primary)]"
              />
              {t('management.distillation.askUser')}
            </label>
          </div>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <Button onClick={() => void handleStart()} loading={busy} icon={<Play className="h-4 w-4" />}>
            {t('management.distillation.start')}
          </Button>
        </CardBody>
      </Card>

      {session && (
        <Card>
          <CardHeader className="flex items-center justify-between">
            <span className="text-sm font-semibold">{t('management.distillation.sessionTitle')}</span>
            <Button variant="ghost" size="sm" onClick={() => void reloadStatus()} icon={<RefreshCw className="h-3.5 w-3.5" />}>
              {t('management.distillation.refresh')}
            </Button>
          </CardHeader>
          <CardBody className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge>{session.session_id}</Badge>
              <Badge variant="secondary">{status?.state ? stateLabel(status.state) : stateLabel(session.initial_state)}</Badge>
              {advanceResult?.agent_action && <Badge variant="anime">{actionLabel(advanceResult.agent_action)}</Badge>}
            </div>

            {session.preread_summary && (
              <p className="line-clamp-3 whitespace-pre-wrap text-xs text-muted-foreground">
                {session.preread_summary}
              </p>
            )}

            {status && status.ambiguity_questions.length > 0 && (
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-[var(--text-secondary)]">
                  {t('management.distillation.questions')}
                </p>
                {status.ambiguity_questions.map((q, i) => (
                  <p key={i} className="text-xs text-muted-foreground">
                    · {q}
                  </p>
                ))}
              </div>
            )}

            {advanceResult?.next_needed && (
              <div className="space-y-2">
                <Textarea
                  label={t('management.distillation.userResponse')}
                  value={userResponse}
                  onChange={(e) => setUserResponse(e.target.value)}
                  rows={2}
                />
                <Button size="sm" onClick={() => void handleAdvance()} loading={busy} icon={<ArrowRight className="h-4 w-4" />}>
                  {t('management.distillation.advance')}
                </Button>
              </div>
            )}

            {!advanceResult?.next_needed && (
              <Button size="sm" variant="secondary" onClick={() => void handleAdvance()} loading={busy}>
                {t('management.distillation.advance')}
              </Button>
            )}

            <div className="flex gap-2 border-t border-[var(--glass-border)] pt-3">
              <Button variant="secondary" size="sm" onClick={() => void handleFinalize()} loading={busy}>
                {t('management.distillation.finalize')}
              </Button>
            </div>

            {finalResult && (
              <div className="space-y-1.5 rounded-lg border border-[var(--glass-border)] p-3 text-xs">
                <p className="font-medium text-[var(--text-primary)]">
                  {t('management.distillation.result')}
                </p>
                <p className="text-muted-foreground">
                  {t('management.distillation.stored')}: {finalResult.stored ? '✓' : '✗'}
                </p>
                <p className="text-muted-foreground">
                  {t('management.distillation.location')}: {finalResult.location}
                </p>
                {finalResult.memory_id != null && (
                  <p className="text-muted-foreground">
                    {t('management.distillation.memoryId')}: {finalResult.memory_id}
                  </p>
                )}
                <p className="text-muted-foreground">{finalResult.reason}</p>
              </div>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 批量切分
// --------------------------------------------------------------------------- //
function BatchDistillation() {
  const { t } = useTranslation();
  const [sourceRef, setSourceRef] = useState('');
  const [templateId, setTemplateId] = useState('default');
  const [chunkSize, setChunkSize] = useState(4000);
  const [goal, setGoal] = useState<'memory' | 'agent' | 'memory_and_agent'>('memory');
  const [targetAgentId, setTargetAgentId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState<BatchStartResult | null>(null);
  const [group, setGroup] = useState<BatchGroupStatus | null>(null);

  const handleStart = async () => {
    setBusy(true);
    setError(null);
    setGroup(null);
    try {
      const res = await distillationApi.startBatch({
        source_type: 'text',
        source_ref: sourceRef,
        template_id: templateId,
        chunk_size: chunkSize,
        distillation_goal: goal,
        target_agent_id: targetAgentId || null,
      });
      setBatch(res);
      const g = await distillationApi.getGroupStatus(res.session_group_id);
      setGroup(g);
    } catch (e) {
      console.error('batch start failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const reloadGroup = async () => {
    if (!batch) return;
    setError(null);
    try {
      const g = await distillationApi.getGroupStatus(batch.session_group_id);
      setGroup(g);
    } catch (e) {
      console.error('group status failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleFinalizeAgent = async (sessionId: string) => {
    setBusy(true);
    setError(null);
    try {
      await distillationApi.finalizeAgent(sessionId);
      if (batch) await reloadGroup();
    } catch (e) {
      console.error('finalize agent failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">{t('management.distillation.batchTitle')}</span>
        </CardHeader>
        <CardBody className="space-y-3">
          <Textarea
            label={t('management.distillation.sourceRef')}
            value={sourceRef}
            onChange={(e) => setSourceRef(e.target.value)}
            placeholder={t('management.distillation.sourceRefPlaceholder')}
            rows={5}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('management.distillation.templateId')}
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
            />
            <Input
              label={t('management.distillation.chunkSize')}
              type="number"
              min={500}
              value={chunkSize}
              onChange={(e) => setChunkSize(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium text-[var(--text-secondary)]">
              {t('management.distillation.goal')}
            </label>
            <select
              value={goal}
              onChange={(e) => setGoal(e.target.value as typeof goal)}
              className={selectCls}
            >
              {GOALS.map((g) => (
                <option key={g} value={g}>
                  {t(`management.distillation.goals.${g}`)}
                </option>
              ))}
            </select>
          </div>
          <Input
            label={t('management.distillation.targetAgent')}
            value={targetAgentId}
            onChange={(e) => setTargetAgentId(e.target.value)}
            placeholder="default"
          />
          {error && <p className="text-xs text-red-400">{error}</p>}
          <Button onClick={() => void handleStart()} loading={busy} icon={<Play className="h-4 w-4" />}>
            {t('management.distillation.startBatch')}
          </Button>
        </CardBody>
      </Card>

      {batch && (
        <Card>
          <CardHeader className="flex items-center justify-between">
            <span className="text-sm font-semibold">{t('management.distillation.groupTitle')}</span>
            <Button variant="ghost" size="sm" onClick={() => void reloadGroup()} icon={<RefreshCw className="h-3.5 w-3.5" />}>
              {t('management.distillation.refresh')}
            </Button>
          </CardHeader>
          <CardBody className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge>{batch.session_group_id}</Badge>
              <Badge variant="secondary">
                {t('management.distillation.completed')}: {group?.completed_count ?? 0}/{group?.total_count ?? batch.total_chunks}
              </Badge>
            </div>
            <div className="space-y-2">
              {batch.sessions.map((s) => (
                <div
                  key={s.session_id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-[var(--glass-border)] p-2.5 text-xs"
                >
                  <span className="truncate text-muted-foreground">
                    #{s.chunk_index} · {s.session_id}
                  </span>
                  <Button size="sm" variant="secondary" onClick={() => void handleFinalizeAgent(s.session_id)} loading={busy}>
                    {t('management.distillation.finalizeAgent')}
                  </Button>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// 角色卡导入
// --------------------------------------------------------------------------- //
function CharacterCardImport() {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parsed, setParsed] = useState<ParseCharacterCardResult | null>(null);
  const [startResult, setStartResult] = useState<string | null>(null);

  const handleParse = async (file: File) => {
    setBusy(true);
    setError(null);
    setParsed(null);
    setStartResult(null);
    try {
      const res = await distillationApi.parseCharacterCard(file);
      setParsed(res);
    } catch (e) {
      console.error('parse card failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleStartFromCard = async () => {
    if (!parsed) return;
    setBusy(true);
    setError(null);
    try {
      const res = await distillationApi.startFromCharacterCard({
        character_card_data: parsed.character_card_data,
        distillation_goal: 'memory_and_agent',
      });
      setStartResult(res.distillation.session_group_id);
    } catch (e) {
      console.error('start from card failed:', e);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="lg:max-w-2xl">
      <CardHeader className="flex items-center gap-2">
        <User className="h-4 w-4 text-primary" />
        <span className="text-sm font-semibold">{t('management.distillation.cardTitle')}</span>
      </CardHeader>
      <CardBody className="space-y-3">
        <input
          ref={fileRef}
          type="file"
          accept=".png,.json"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) {
              setFileName(f.name);
              void handleParse(f);
            }
          }}
        />
        <Button
          variant="secondary"
          onClick={() => fileRef.current?.click()}
          loading={busy}
          icon={<Upload className="h-4 w-4" />}
        >
          {fileName || t('management.distillation.uploadCard')}
        </Button>

        {error && <p className="text-xs text-red-400">{error}</p>}

        {parsed && (
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] p-3 text-xs">
            <p className="font-medium text-[var(--text-primary)]">
              {t('management.distillation.cardName')}: {parsed.character_card_data.name}
            </p>
            {parsed.character_card_data.description && (
              <p className="line-clamp-3 text-muted-foreground">
                {parsed.character_card_data.description}
              </p>
            )}
            <p className="text-muted-foreground">
              {t('management.distillation.sourceRefLength')}: {parsed.source_ref_length}
            </p>
            <Button size="sm" onClick={() => void handleStartFromCard()} loading={busy} icon={<Sparkles className="h-3.5 w-3.5" />}>
              {t('management.distillation.startFromCard')}
            </Button>
            {startResult && (
              <p className="text-xs text-emerald-400">
                {t('management.distillation.groupId')}: {startResult}
              </p>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}