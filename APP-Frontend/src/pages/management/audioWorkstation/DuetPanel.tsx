/**
 * DuetPanel — 双人合唱面板（enhance-cover-pitch-analysis-duet SubTask 4.3）
 *
 * 分离式双人合唱前端（后端契约：POST /api/cover/duet 202 {task_id} →
 * GET /api/cover/duet/{task_id} 轮询 → /api/audio-files/duet/{task_id}/final.wav 播放）：
 * - 源曲上传：复用 audio-uploads 受控上传（独立 audioPath 状态，与 CoverPanel 互不共享）
 * - model_a / model_b 下拉（可空 = 该声部保留原声）
 * - auto_transpose 开关（默认开）；关闭时展示 transpose_a / transpose_b 手输
 * - 高级折叠（默认收起）：query_a / query_b 文本查询描述 + gain_a / gain_b / accompaniment_gain
 * - 提交 → task_id → 轮询（默认 2s，completed / failed 停止；模式对齐 CompositionPanel pollTask 注入）
 * - 六阶段徽标（separate / split / analyze / svc_a / svc_b / mix）+ completed 播放成品 + failed 错误展示
 *
 * 503（分离引擎未就绪）识别：normalizeError 将后端 detail 拼入 message，
 * 后端守卫消息恒含 setup_separation / 分离引擎 关键字，据此切换专用提示。
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Loader2, Upload, Users } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type { DuetSubmitRequest, DuetTaskStatus, SVCModel } from '@/api/clients/voiceworkstation';

const inputClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

const selectClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

/** 六阶段（与后端 duet_pipeline.DUET_STAGES 顺序一致） */
const DUET_STAGES = ['separate', 'split', 'analyze', 'svc_a', 'svc_b', 'mix'] as const;

const POLL_INTERVAL_MS = 2000;

/** 阶段状态徽标配色（pending / running / completed / skipped / failed） */
const STAGE_BADGE_CLASS: Record<string, string> = {
  pending: 'border-[var(--glass-border)] text-muted-foreground',
  running: 'border-blue-400/60 text-blue-300',
  completed: 'border-emerald-400/60 text-emerald-300',
  skipped: 'border-amber-400/60 text-amber-300',
  failed: 'border-red-400/60 text-red-300',
};

/** 后端 503 守卫消息识别（normalizeError 会把 detail 拼进 Error.message） */
function isSeparationUnavailableError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error);
  return message.includes('setup_separation') || message.includes('分离引擎');
}

export interface DuetPanelProps {
  /** 任务轮询函数（默认 voiceworkstationApi.getDuetCoverTask；测试可注入 mock，对齐 CompositionPanel） */
  pollTask?: (taskId: string) => Promise<DuetTaskStatus>;
  /** 轮询间隔（默认 2000ms，≥2s） */
  pollIntervalMs?: number;
}

export default function DuetPanel({ pollTask, pollIntervalMs = POLL_INTERVAL_MS }: DuetPanelProps) {
  const { t } = useTranslation();

  const resolvedPollTask = useMemo(
    () => pollTask ?? ((taskId: string) => voiceworkstationApi.getDuetCoverTask(taskId)),
    [pollTask],
  );

  // ── 模型列表 ──
  const [models, setModels] = useState<SVCModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);

  // ── 源曲上传（独立 audioPath）──
  const [audioPath, setAudioPath] = useState('');
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadFailed, setUploadFailed] = useState(false);

  // ── 声部模型 ──
  const [modelA, setModelA] = useState('');
  const [modelB, setModelB] = useState('');

  // ── 变调 ──
  const [autoTranspose, setAutoTranspose] = useState(true);
  const [transposeA, setTransposeA] = useState(0);
  const [transposeB, setTransposeB] = useState(0);

  // ── 高级折叠（默认收起）──
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [queryA, setQueryA] = useState('');
  const [queryB, setQueryB] = useState('');
  const [gainA, setGainA] = useState(1);
  const [gainB, setGainB] = useState(1);
  const [accompanimentGain, setAccompanimentGain] = useState(0.8);

  // ── 任务状态 ──
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [separationUnavailable, setSeparationUnavailable] = useState(false);
  const [task, setTask] = useState<DuetTaskStatus | null>(null);

  useEffect(() => {
    setModelsLoading(true);
    voiceworkstationApi
      .listSoVITSSVCModels()
      .then((r) => setModels(r.models ?? []))
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, []);

  /** 主通道：本地上传 → audio_path 回填（与 CoverPanel 同款 audio-uploads 流程） */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadFailed(false);
    try {
      const res = await voiceworkstationApi.uploadAudio(file);
      setAudioPath(res.audio_path);
      setUploadedFilename(res.filename);
    } catch (error) {
      console.error('[DuetPanel] upload failed:', error);
      setUploadFailed(true);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  /** 提交双人合唱任务（auto_transpose 开启时不发送显式 transpose，交由后端画像对齐） */
  const handleSubmit = async () => {
    if (!audioPath.trim() || submitting) return;
    setSubmitting(true);
    setSubmitError(null);
    setSeparationUnavailable(false);
    setTask(null);
    const payload: DuetSubmitRequest = {
      audio_path: audioPath.trim(),
      model_a: modelA || null,
      model_b: modelB || null,
      auto_transpose: autoTranspose,
      transpose_a: autoTranspose ? null : transposeA,
      transpose_b: autoTranspose ? null : transposeB,
      query_a: queryA.trim() || null,
      query_b: queryB.trim() || null,
      gain_a: gainA,
      gain_b: gainB,
      accompaniment_gain: accompanimentGain,
    };
    try {
      const res = await voiceworkstationApi.submitDuetCover(payload);
      setTask({
        task_id: res.task_id,
        created_at: '',
        status: 'pending',
        stage: 'pending',
        progress: 0,
        stages: {},
        transposes: { a: 0, b: 0, source: 'fallback', source_a: 'fallback', source_b: 'fallback', notes: [] },
        analysis: {},
        notes: [],
        error: null,
        finished_at: null,
        audio_url: null,
      });
    } catch (error) {
      console.error('[DuetPanel] submit failed:', error);
      if (isSeparationUnavailableError(error)) {
        setSeparationUnavailable(true);
      } else {
        setSubmitError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      setSubmitting(false);
    }
  };

  // ── 任务轮询（对齐 CompositionPanel：立即首轮 + setInterval，completed/failed 停止）──
  const activeTaskId = task?.status === 'completed' || task?.status === 'failed' ? null : task?.task_id;
  useEffect(() => {
    if (!activeTaskId) return;
    let stopped = false;
    let timer: ReturnType<typeof setInterval>;
    const poll = async () => {
      try {
        const next = await resolvedPollTask(activeTaskId);
        if (!stopped) setTask(next);
      } catch {
        // 任务查询失败时静默，下一轮继续
      }
    };
    poll();
    timer = setInterval(poll, pollIntervalMs);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [activeTaskId, resolvedPollTask, pollIntervalMs]);

  const modelOptions = (value: string, onChange: (v: string) => void, testId: string) => (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={selectClassName} data-testid={testId}>
      <option value="">{t('management.audioWorkstation.duetKeepOriginal')}</option>
      {models.map((m) => (
        <option key={m.path} value={m.path}>
          {m.name}
        </option>
      ))}
    </select>
  );

  return (
    <section className="space-y-4" data-testid="duet-panel">
      <h4 className="flex items-center gap-2 text-sm font-semibold">
        <Users className="h-4 w-4 text-primary" />
        {t('management.audioWorkstation.duetTitle')}
      </h4>

      {/* 源曲上传（audio-uploads 同款流程）+ 辅助路径 */}
      <div className="space-y-1.5">
        <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetUpload')}</label>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => document.getElementById('duet-audio-upload')?.click()}
            disabled={uploading}
            className="rounded-lg bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
            data-testid="duet-upload-btn"
          >
            {uploading && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
            <Upload className="mr-1 inline h-3.5 w-3.5" />
            {t('management.audioWorkstation.duetUploadBtn')}
          </button>
          <input
            id="duet-audio-upload"
            type="file"
            accept=".wav,.mp3,.flac,.ogg,.m4a"
            className="hidden"
            onChange={handleUpload}
            data-testid="duet-upload-input"
          />
          {uploadedFilename && (
            <span className="truncate text-sm text-muted-foreground" data-testid="duet-uploaded-filename">
              {t('management.audioWorkstation.duetUploadedFile')}: {uploadedFilename}
            </span>
          )}
        </div>
        <input
          value={audioPath}
          onChange={(e) => setAudioPath(e.target.value)}
          placeholder={t('management.audioWorkstation.coverAudioPathPlaceholder')}
          className={inputClassName}
          data-testid="duet-audio-path-input"
        />
        {uploadFailed && (
          <p className="text-xs text-red-400" data-testid="duet-upload-error">
            {t('management.audioWorkstation.duetUploadFailed')}
          </p>
        )}
      </div>

      {/* 两路模型选择（可空 = 保留原声） */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetModelA')}</label>
          {modelsLoading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="duet-models-loading">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t('management.audioWorkstation.coverModelsLoading')}
            </p>
          ) : (
            modelOptions(modelA, setModelA, 'duet-model-a-select')
          )}
        </div>
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetModelB')}</label>
          {modelsLoading ? (
            <p className="text-sm text-muted-foreground">{t('management.audioWorkstation.coverModelsLoading')}</p>
          ) : (
            modelOptions(modelB, setModelB, 'duet-model-b-select')
          )}
        </div>
      </div>

      {/* auto_transpose 开关；关闭时展示手输 transpose */}
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="duet-auto-transpose-label">
          <input
            type="checkbox"
            checked={autoTranspose}
            onChange={(e) => setAutoTranspose(e.target.checked)}
            data-testid="duet-auto-transpose-toggle"
          />
          {t('management.audioWorkstation.duetAutoTranspose')}
        </label>
        {!autoTranspose && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetTransposeA')}</label>
              <input
                type="number"
                value={transposeA}
                onChange={(e) => setTransposeA(Number(e.target.value))}
                className={inputClassName}
                data-testid="duet-transpose-a-input"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetTransposeB')}</label>
              <input
                type="number"
                value={transposeB}
                onChange={(e) => setTransposeB(Number(e.target.value))}
                className={inputClassName}
                data-testid="duet-transpose-b-input"
              />
            </div>
          </div>
        )}
      </div>

      {/* 高级折叠（默认收起）：查询描述 + 增益 */}
      <div className="space-y-2">
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-[var(--color-text-primary)]"
          data-testid="duet-advanced-toggle"
        >
          {showAdvanced ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          {t('management.audioWorkstation.duetAdvanced')}
        </button>
        {showAdvanced && (
          <div className="space-y-3 rounded-lg border border-[var(--glass-border)] p-3">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetQueryA')}</label>
                <input
                  value={queryA}
                  onChange={(e) => setQueryA(e.target.value)}
                  placeholder={t('management.audioWorkstation.duetQueryAPlaceholder')}
                  className={inputClassName}
                  data-testid="duet-query-a-input"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetQueryB')}</label>
                <input
                  value={queryB}
                  onChange={(e) => setQueryB(e.target.value)}
                  placeholder={t('management.audioWorkstation.duetQueryBPlaceholder')}
                  className={inputClassName}
                  data-testid="duet-query-b-input"
                />
              </div>
            </div>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetGainA')}</label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  value={gainA}
                  onChange={(e) => setGainA(Number(e.target.value))}
                  className={inputClassName}
                  data-testid="duet-gain-a-input"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetGainB')}</label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  value={gainB}
                  onChange={(e) => setGainB(Number(e.target.value))}
                  className={inputClassName}
                  data-testid="duet-gain-b-input"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm text-muted-foreground">
                  {t('management.audioWorkstation.duetAccompanimentGain')}
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  value={accompanimentGain}
                  onChange={(e) => setAccompanimentGain(Number(e.target.value))}
                  className={inputClassName}
                  data-testid="duet-accompaniment-gain-input"
                />
              </div>
            </div>
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => void handleSubmit()}
        disabled={submitting || !audioPath.trim()}
        className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        data-testid="duet-submit-btn"
      >
        {submitting && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
        {t('management.audioWorkstation.duetSubmit')}
      </button>

      {separationUnavailable && (
        <p className="text-xs text-red-400" data-testid="duet-separation-unavailable">
          {t('management.audioWorkstation.duetSeparationUnavailable')}
        </p>
      )}
      {submitError && (
        <p className="text-xs text-red-400" data-testid="duet-submit-error">
          {t('management.audioWorkstation.duetSubmitFailed')}：{submitError}
        </p>
      )}

      {/* 任务进度：阶段徽标 + 进度 */}
      {task && (
        <div className="space-y-2" data-testid="duet-task">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span data-testid="duet-task-status">{t(`management.audioWorkstation.status.${task.status}`)}</span>
            <span>{Math.round(task.progress * 100)}%</span>
          </div>
          <div className="flex flex-wrap gap-2" data-testid="duet-stages">
            {DUET_STAGES.map((stage) => {
              const stageStatus = task.stages?.[stage] ?? 'pending';
              return (
                <span
                  key={stage}
                  data-testid={`duet-stage-${stage}`}
                  data-status={stageStatus}
                  className={`rounded border px-2 py-0.5 text-xs ${STAGE_BADGE_CLASS[stageStatus] ?? STAGE_BADGE_CLASS.pending}`}
                >
                  {t(`management.audioWorkstation.duetStage_${stage}`)}
                </span>
              );
            })}
          </div>
          {task.notes.length > 0 && (
            <ul className="space-y-0.5 text-xs text-muted-foreground" data-testid="duet-notes">
              {task.notes.map((note, i) => (
                <li key={i}>· {note}</li>
              ))}
            </ul>
          )}
          {task.status === 'failed' && (
            <p className="text-xs text-red-400" data-testid="duet-task-error">
              [{task.stage}] {task.error}
            </p>
          )}
          {task.status === 'completed' && (
            <div className="space-y-2" data-testid="duet-result">
              <p className="text-sm text-muted-foreground" data-testid="duet-transposes">
                {t('management.audioWorkstation.duetTransposes')}: {task.transposes?.a ?? 0} / {task.transposes?.b ?? 0}
              </p>
              <p className="text-sm text-muted-foreground">{t('management.audioWorkstation.duetResult')}</p>
              <audio
                controls
                className="w-full"
                src={getVoiceWorkstationAudioUrl(
                  task.audio_url ?? `/api/audio-files/duet/${task.task_id}/final.wav`,
                )}
                data-testid="duet-audio-player"
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}
