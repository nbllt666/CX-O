/**
 * CoverPanel — 翻唱面板（split-audio-workstation-cxfc-modelstation SubTask 4.2 +
 * enhance-cover-pitch-analysis-duet SubTask 4.2/4.3）
 *
 * 演进自原 SVCPanel：训练/数据集 UI 已随训练域整体迁至模型工作站独立前端
 * （CXO-ModelStation/frontend），本面板仅保留翻唱链路：
 * - 模式切换：单人翻唱 / 双人合唱（双人模式渲染 DuetPanel，默认单人）
 * - 单人翻唱：
 *   - 模型选择（VWS /api/sovits-svc/models，只读扫描 ModelStation 模型目录）
 *   - 音频输入双通道：
 *     ① 主通道本地上传（<input type="file"> → POST /api/audio-uploads → 取 audio_path）
 *     ② 辅助通道手输服务端已有音频路径（沿原 SVCPanel infer 的路径输入方式）
 *   - 音域分析：audioPath/模型变化（防抖 500ms）→ POST /api/cover/analyze →
 *     transpose 预填（用户手改后不覆盖，重新上传重置）+ 源/目标音域对比条 +
 *     range_warning / profile_unavailable 展示；失败静默降级不阻塞手填
 *   - 参数：speaker_id / transpose（变调半音）/ cluster_model_path（可选）
 *   - 推理 → 结果 audio_url 经 getVoiceWorkstationAudioUrl 内嵌 <audio controls> 播放
 *
 * 消费 voiceworkstationApi 的受控上传 / So-VITS-SVC / 音域分析域。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, MicVocal, Upload, Users } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type { CoverAnalyzeResult, SVCModel, VoiceWsAudioResult } from '@/api/clients/voiceworkstation';
import DuetPanel from './DuetPanel';

const inputClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

const selectClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

/** 音域区间条：在共享 MIDI 刻度 [scaleMin, scaleMax] 上渲染 [low, high] 区间（纯 CSS/内联样式） */
function RangeBar({
  label,
  low,
  high,
  scaleMin,
  scaleMax,
}: {
  label: string;
  low: number;
  high: number;
  scaleMin: number;
  scaleMax: number;
}) {
  const span = Math.max(scaleMax - scaleMin, 1);
  const left = ((low - scaleMin) / span) * 100;
  const width = Math.max(((high - low) / span) * 100, 1.5);
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{label}</span>
        <span>
          {low.toFixed(1)} – {high.toFixed(1)} MIDI
        </span>
      </div>
      <div className="relative h-2 rounded bg-[rgba(255,255,255,0.08)]">
        <div className="absolute h-2 rounded bg-primary/70" style={{ left: `${left}%`, width: `${width}%` }} />
      </div>
    </div>
  );
}

export default function CoverPanel() {
  const { t } = useTranslation();

  // ── 模型列表 ──
  const [models, setModels] = useState<SVCModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelPath, setModelPath] = useState('');

  // ── 音频输入双通道 ──
  // audioPath 为 infer 的唯一音频来源：主通道上传成功后回填 audio_path，
  // 辅助通道手输服务端路径直接写入同一状态。
  const [audioPath, setAudioPath] = useState('');
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadFailed, setUploadFailed] = useState(false);

  // ── 推理参数 ──
  const [speakerId, setSpeakerId] = useState(0);
  const [transpose, setTranspose] = useState(0);
  const [clusterModelPath, setClusterModelPath] = useState('');

  // ── 推理状态 ──
  const [inferring, setInferring] = useState(false);
  const [inferFailed, setInferFailed] = useState(false);
  const [inferResult, setInferResult] = useState<VoiceWsAudioResult | null>(null);

  // ── 模式切换：单人翻唱 / 双人合唱（双人模式渲染 DuetPanel，默认单人）──
  const [mode, setMode] = useState<'solo' | 'duet'>('solo');

  // ── 音域分析（enhance-cover-pitch-analysis-duet SubTask 4.2）──
  // audioPath/模型变化（上传回填、模型切换）→ 500ms 防抖后自动 analyze；
  // 失败静默降级（不阻塞手填 transpose）；响应按序号防乱序，仅采纳最新一次。
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<CoverAnalyzeResult | null>(null);
  // 用户手改过 transpose 则 analyze 不再覆盖预填；重新上传时重置（spec 冻结口径）
  const transposeTouchedRef = useRef(false);
  const analyzeSeqRef = useRef(0);

  // 选中模型 → analyze 的 model_name：SVC 模型名去扩展名后即训练 speaker 名（so-vits 惯例）
  const analyzeModelName = useMemo(() => {
    const selected = models.find((m) => m.path === modelPath);
    return selected ? selected.name.replace(/\.(pth|pt|ckpt)$/i, '') : undefined;
  }, [models, modelPath]);

  useEffect(() => {
    const path = audioPath.trim();
    if (!path) {
      analyzeSeqRef.current += 1;
      setAnalyzeLoading(false);
      setAnalyzeResult(null);
      return;
    }
    const seq = analyzeSeqRef.current + 1;
    analyzeSeqRef.current = seq;
    const timer = setTimeout(() => {
      setAnalyzeLoading(true);
      voiceworkstationApi
        .analyzeCover(path, analyzeModelName)
        .then((result) => {
          if (analyzeSeqRef.current !== seq) return; // 丢弃过期响应
          setAnalyzeResult(result);
          if (typeof result.recommended_transpose === 'number' && !transposeTouchedRef.current) {
            setTranspose(result.recommended_transpose);
          }
        })
        .catch((error) => {
          if (analyzeSeqRef.current !== seq) return;
          // 静默降级：analyze 失败不阻塞手填 transpose
          console.warn('[CoverPanel] cover analyze failed:', error);
          setAnalyzeResult(null);
        })
        .finally(() => {
          if (analyzeSeqRef.current === seq) setAnalyzeLoading(false);
        });
    }, 500);
    return () => clearTimeout(timer);
  }, [audioPath, analyzeModelName]);

  const refreshModels = useCallback(() => {
    setModelsLoading(true);
    voiceworkstationApi
      .listSoVITSSVCModels()
      .then((r) => setModels(r.models ?? []))
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, []);

  useEffect(() => {
    refreshModels();
  }, [refreshModels]);

  /** 主通道：本地上传 → 取 audio_path 回填，展示服务端重生成后的文件名 */
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadFailed(false);
    try {
      const res = await voiceworkstationApi.uploadAudio(file);
      // 重新上传视为新分析起点：重置手改标记，允许推荐值覆盖预填（spec 冻结口径）
      transposeTouchedRef.current = false;
      setAudioPath(res.audio_path);
      setUploadedFilename(res.filename);
    } catch (error) {
      console.error('[CoverPanel] upload failed:', error);
      setUploadFailed(true);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  /** 提交翻唱推理：audio_path 可来自上传回填或手输服务端路径 */
  const handleInfer = async () => {
    if (!audioPath.trim()) return;
    setInferring(true);
    setInferFailed(false);
    setInferResult(null);
    try {
      const res = await voiceworkstationApi.sovitsSVCInfer({
        audio_path: audioPath.trim(),
        model_path: modelPath || undefined,
        speaker_id: speakerId,
        transpose,
        cluster_model_path: clusterModelPath.trim() || undefined,
      });
      setInferResult(res);
    } catch (error) {
      console.error('[CoverPanel] infer failed:', error);
      setInferFailed(true);
    } finally {
      setInferring(false);
    }
  };

  return (
    <section className="glass-panel space-y-6 p-5">
      {/* 模式切换：单人翻唱 / 双人合唱（组件状态持久于本面板，默认单人） */}
      <div className="flex gap-2" data-testid="cover-mode-switch">
        <button
          type="button"
          onClick={() => setMode('solo')}
          data-testid="cover-mode-solo"
          className={
            mode === 'solo'
              ? 'rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85'
              : 'rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]'
          }
        >
          <MicVocal className="mr-1 inline h-4 w-4" />
          {t('management.audioWorkstation.coverModeSolo')}
        </button>
        <button
          type="button"
          onClick={() => setMode('duet')}
          data-testid="cover-mode-duet"
          className={
            mode === 'duet'
              ? 'rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85'
              : 'rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]'
          }
        >
          <Users className="mr-1 inline h-4 w-4" />
          {t('management.audioWorkstation.coverModeDuet')}
        </button>
      </div>

      {mode === 'duet' ? (
        <DuetPanel />
      ) : (
      <div className="space-y-3">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <MicVocal className="h-4 w-4 text-primary" />
          {t('management.audioWorkstation.coverTitle')}
        </h4>

        {/* 模型选择 */}
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.coverModel')}</label>
          {modelsLoading ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="cover-models-loading">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t('management.audioWorkstation.coverModelsLoading')}
            </p>
          ) : models.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="cover-no-models">
              {t('management.audioWorkstation.coverNoModels')}
            </p>
          ) : (
            <select
              value={modelPath}
              onChange={(e) => setModelPath(e.target.value)}
              className={selectClassName}
              data-testid="cover-model-select"
            >
              <option value="">{t('management.audioWorkstation.coverSelectModel')}</option>
              {models.map((m) => (
                <option key={m.path} value={m.path}>
                  {m.name}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* 音频输入主通道：本地上传 */}
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.coverUpload')}</label>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => document.getElementById('cover-audio-upload')?.click()}
              disabled={uploading}
              className="rounded-lg bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
              data-testid="cover-upload-btn"
            >
              {uploading && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
              <Upload className="mr-1 inline h-3.5 w-3.5" />
              {t('management.audioWorkstation.coverUploadBtn')}
            </button>
            <input
              id="cover-audio-upload"
              type="file"
              accept=".wav,.mp3,.flac,.ogg,.m4a"
              className="hidden"
              onChange={handleUpload}
              data-testid="cover-upload-input"
            />
            {uploadedFilename && (
              <span className="truncate text-sm text-muted-foreground" data-testid="cover-uploaded-filename">
                {t('management.audioWorkstation.coverUploadedFile')}: {uploadedFilename}
              </span>
            )}
          </div>
          {uploadFailed && (
            <p className="text-xs text-red-400" data-testid="cover-upload-error">
              {t('management.audioWorkstation.coverUploadFailed')}
            </p>
          )}
        </div>

        {/* 音频输入辅助通道：手输服务端路径 */}
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.coverAudioPath')}</label>
          <input
            value={audioPath}
            onChange={(e) => setAudioPath(e.target.value)}
            placeholder={t('management.audioWorkstation.coverAudioPathPlaceholder')}
            className={inputClassName}
            data-testid="cover-audio-path-input"
          />
        </div>

        {/* 推理参数 */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="space-y-1.5">
            <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.coverSpeakerId')}</label>
            <input
              type="number"
              value={speakerId}
              onChange={(e) => setSpeakerId(Number(e.target.value))}
              className={inputClassName}
              data-testid="cover-speaker-id-input"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.coverTranspose')}</label>
            <input
              type="number"
              value={transpose}
              onChange={(e) => {
                transposeTouchedRef.current = true;
                setTranspose(Number(e.target.value));
              }}
              className={inputClassName}
              data-testid="cover-transpose-input"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm text-muted-foreground">{t('management.audioWorkstation.coverClusterModelPath')}</label>
            <input
              value={clusterModelPath}
              onChange={(e) => setClusterModelPath(e.target.value)}
              placeholder={t('management.audioWorkstation.coverClusterModelPathPlaceholder')}
              className={inputClassName}
              data-testid="cover-cluster-model-input"
            />
          </div>
        </div>

        {/* 音域分析结果：推荐预填徽标 + 源/目标音域对比条 + 覆盖警告 / 画像不可得提示 */}
        {(analyzeLoading || analyzeResult) && (
          <div className="space-y-2" data-testid="cover-analyze-block">
            {analyzeLoading && (
              <p className="flex items-center gap-2 text-xs text-muted-foreground" data-testid="cover-analyze-loading">
                <Loader2 className="h-3 w-3 animate-spin" />
                {t('management.audioWorkstation.coverAnalyzeRunning')}
              </p>
            )}
            {analyzeResult?.recommended_transpose !== undefined && (
              <span
                className="inline-block rounded-full border border-emerald-400/60 px-2 py-0.5 text-xs text-emerald-300"
                data-testid="cover-analyze-recommended"
              >
                {t('management.audioWorkstation.coverAnalyzeRecommended', {
                  n:
                    analyzeResult.recommended_transpose > 0
                      ? `+${analyzeResult.recommended_transpose}`
                      : `${analyzeResult.recommended_transpose}`,
                })}
              </span>
            )}
            {analyzeResult?.separation_used && (
              <p className="text-xs text-muted-foreground" data-testid="cover-analyze-separation-used">
                {t('management.audioWorkstation.coverAnalyzeSeparationUsed')}
              </p>
            )}
            {analyzeResult?.profile && analyzeResult?.target_profile && (
              <div
                className="space-y-1.5 rounded-lg border border-[var(--glass-border)] p-3"
                data-testid="cover-range-compare"
              >
                {(() => {
                  const src = analyzeResult.profile;
                  const tgt = analyzeResult.target_profile;
                  const scaleMin = Math.min(src.range_low_midi, tgt.range_low_midi) - 1;
                  const scaleMax = Math.max(src.range_high_midi, tgt.range_high_midi) + 1;
                  return (
                    <>
                      <RangeBar
                        label={t('management.audioWorkstation.coverAnalyzeSourceRange')}
                        low={src.range_low_midi}
                        high={src.range_high_midi}
                        scaleMin={scaleMin}
                        scaleMax={scaleMax}
                      />
                      <RangeBar
                        label={t('management.audioWorkstation.coverAnalyzeTargetRange')}
                        low={tgt.range_low_midi}
                        high={tgt.range_high_midi}
                        scaleMin={scaleMin}
                        scaleMax={scaleMax}
                      />
                    </>
                  );
                })()}
              </div>
            )}
            {analyzeResult?.range_warning && (
              <p
                className="rounded-lg border border-amber-400/60 px-3 py-2 text-xs text-amber-300"
                data-testid="cover-range-warning"
              >
                {t('management.audioWorkstation.coverRangeWarning')}：{analyzeResult.range_warning}
              </p>
            )}
            {analyzeResult?.profile_unavailable && (
              <p className="text-xs text-muted-foreground" data-testid="cover-profile-unavailable">
                {t('management.audioWorkstation.coverProfileUnavailable')}：{analyzeResult.profile_unavailable}
              </p>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={() => void handleInfer()}
          disabled={inferring || !audioPath.trim()}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          data-testid="cover-infer-btn"
        >
          {inferring && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
          {t('management.audioWorkstation.coverInfer')}
        </button>

        {inferFailed && (
          <p className="text-xs text-red-400" data-testid="cover-infer-error">
            {t('management.audioWorkstation.coverInferFailed')}
          </p>
        )}

        {inferResult && (
          <div className="space-y-2" data-testid="cover-infer-result">
            <p className="text-sm text-muted-foreground">
              {t('management.audioWorkstation.coverInferResult')} · {inferResult.output_filename}
            </p>
            <audio controls className="w-full" src={getVoiceWorkstationAudioUrl(inferResult.audio_url)} data-testid="cover-audio-player" />
          </div>
        )}
      </div>
      )}
    </section>
  );
}
