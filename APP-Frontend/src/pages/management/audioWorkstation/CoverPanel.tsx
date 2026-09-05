/**
 * CoverPanel — 翻唱面板（split-audio-workstation-cxfc-modelstation SubTask 4.2）
 *
 * 演进自原 SVCPanel：训练/数据集 UI 已随训练域整体迁至模型工作站独立前端
 * （CXO-ModelStation/frontend），本面板仅保留翻唱推理链路：
 * - 模型选择（VWS /api/sovits-svc/models，只读扫描 ModelStation 模型目录）
 * - 音频输入双通道：
 *   ① 主通道本地上传（<input type="file"> → POST /api/audio-uploads → 取 audio_path）
 *   ② 辅助通道手输服务端已有音频路径（沿原 SVCPanel infer 的路径输入方式）
 * - 参数：speaker_id / transpose（变调半音）/ cluster_model_path（可选）
 * - 推理 → 结果 audio_url 经 getVoiceWorkstationAudioUrl 内嵌 <audio controls> 播放
 *
 * 消费 voiceworkstationApi 的受控上传 / So-VITS-SVC 域。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, MicVocal, Upload } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type { SVCModel, VoiceWsAudioResult } from '@/api/clients/voiceworkstation';

const inputClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

const selectClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

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
              onChange={(e) => setTranspose(Number(e.target.value))}
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
    </section>
  );
}
