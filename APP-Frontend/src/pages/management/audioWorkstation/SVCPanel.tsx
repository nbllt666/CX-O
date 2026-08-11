/**
 * SVC 训练推理 Tab（SubTask 7.4 · 音频工作站）
 *
 * 功能深度对齐 CX-O-Frontend SVCPanel：
 * - 批量数据集生成（多引擎：voxcpm / orpheustts / f5tts）+ 任务进度轮询
 * - 数据集管理（列表 / 导入文件 / 删除）
 * - 数据预处理 + 训练多参数（output_name）+ 训练状态轮询（5s）
 * - 推理完整参数（speaker_id / cluster_model_path / transpose 滑杆）
 *
 * 消费 voiceworkstationApi 的 So-VITS-SVC / VoxCPM 域。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, MicVocal, Database, Layers } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type {
  SVCTrainStatus,
  SVCModel,
  SVCDataset,
  BatchDatasetTask,
  BatchDatasetEngine,
  VoiceWsAudioResult,
} from '@/api/clients/voiceworkstation';

const engineOptions: { value: BatchDatasetEngine; label: string }[] = [
  { value: 'voxcpm', label: 'VoxCPM' },
  { value: 'orpheustts', label: 'Orpheus TTS' },
  { value: 'f5tts', label: 'F5TTS' },
];

const inputClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

const selectClassName =
  'w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm text-[var(--color-text-primary)] focus:border-[rgba(255,183,225,0.4)] focus:outline-none';

export default function SVCPanel() {
  const { t } = useTranslation();

  // ── 数据集管理 + 预处理 + 训练 ──
  const [datasets, setDatasets] = useState<SVCDataset[]>([]);
  const [datasetImporting, setDatasetImporting] = useState(false);
  const [datasetSpeakerName, setDatasetSpeakerName] = useState('');
  const [trainDataDir, setTrainDataDir] = useState('');
  const [trainSpeakerName, setTrainSpeakerName] = useState('');
  const [trainOutputName, setTrainOutputName] = useState('');
  const [trainEpochs, setTrainEpochs] = useState(100);
  const [trainBatchSize, setTrainBatchSize] = useState(4);
  const [trainLearningRate, setTrainLearningRate] = useState(0.0001);
  const [trainPreprocessing, setTrainPreprocessing] = useState(false);
  const [trainPreprocessDone, setTrainPreprocessDone] = useState(false);
  const [trainStatus, setTrainStatus] = useState<SVCTrainStatus | null>(null);
  const [trainModels, setTrainModels] = useState<SVCModel[]>([]);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // ── 推理 ──
  const [inferModelPath, setInferModelPath] = useState('');
  const [inferAudioPath, setInferAudioPath] = useState('');
  const [inferSpeakerId, setInferSpeakerId] = useState(0);
  const [inferTranspose, setInferTranspose] = useState(0);
  const [inferClusterModelPath, setInferClusterModelPath] = useState('');
  const [inferResult, setInferResult] = useState<VoiceWsAudioResult | null>(null);

  // ── 批量数据集生成（多引擎）──
  const [batchSpeaker, setBatchSpeaker] = useState('');
  const [batchEngine, setBatchEngine] = useState<BatchDatasetEngine>('voxcpm');
  const [batchTexts, setBatchTexts] = useState('');
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchTask, setBatchTask] = useState<BatchDatasetTask | null>(null);

  const refreshDatasets = useCallback(() => {
    voiceworkstationApi
      .listSVCDatasets()
      .then((r) => setDatasets(r.datasets ?? []))
      .catch(() => setDatasets([]));
  }, []);

  // 训练状态轮询（5s）
  useEffect(() => {
    const poll = () => {
      voiceworkstationApi
        .getSoVITSSVCStatus()
        .then((s) => {
          setTrainStatus(s);
          setTrainModels(s.models ?? []);
        })
        .catch(() => {});
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    refreshDatasets();
  }, [refreshDatasets]);

  const handleImportDataset = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length === 0 || !datasetSpeakerName.trim()) return;
    setDatasetImporting(true);
    setFailed(false);
    try {
      await voiceworkstationApi.importSVCDataset(datasetSpeakerName.trim(), files);
      refreshDatasets();
    } catch (error) {
      console.error('[SVCPanel] import dataset failed:', error);
      setFailed(true);
    } finally {
      setDatasetImporting(false);
      e.target.value = '';
    }
  };

  const handleDeleteDataset = async (name: string) => {
    if (!window.confirm(t('management.audioWorkstation.svcConfirmDeleteDataset'))) return;
    setFailed(false);
    try {
      await voiceworkstationApi.deleteSVCDataset(name);
      refreshDatasets();
    } catch (error) {
      console.error('[SVCPanel] delete dataset failed:', error);
      setFailed(true);
    }
  };

  const handlePreprocess = async () => {
    if (!trainDataDir.trim() || !trainSpeakerName.trim()) return;
    setTrainPreprocessing(true);
    setTrainPreprocessDone(false);
    setFailed(false);
    try {
      await voiceworkstationApi.sovitsSVCPreprocess({
        training_data_dir: trainDataDir.trim(),
        speaker_name: trainSpeakerName.trim(),
      });
      setTrainPreprocessDone(true);
    } catch (error) {
      console.error('[SVCPanel] preprocess failed:', error);
      setFailed(true);
    } finally {
      setTrainPreprocessing(false);
    }
  };

  const handleTrain = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await voiceworkstationApi.startSoVITSSVCTrain({
        training_data_dir: trainDataDir.trim() || undefined,
        output_name: trainOutputName.trim() || undefined,
        epochs: trainEpochs || 100,
        batch_size: trainBatchSize || 4,
        learning_rate: trainLearningRate || 0.0001,
      });
    } catch (error) {
      console.error('[SVCPanel] train failed:', error);
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const handleStop = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await voiceworkstationApi.stopSoVITSSVCTrain();
    } catch (error) {
      console.error('[SVCPanel] stop failed:', error);
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const handleInfer = async () => {
    if (!inferAudioPath.trim()) return;
    setBusy(true);
    setFailed(false);
    setInferResult(null);
    try {
      const res = await voiceworkstationApi.sovitsSVCInfer({
        audio_path: inferAudioPath.trim(),
        model_path: inferModelPath || undefined,
        speaker_id: inferSpeakerId,
        transpose: inferTranspose,
        cluster_model_path: inferClusterModelPath.trim() || undefined,
      });
      setInferResult(res);
    } catch (error) {
      console.error('[SVCPanel] infer failed:', error);
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const handleBatchSubmit = async () => {
    const texts = batchTexts
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0)
      .map((text) => ({ text }));
    if (texts.length === 0 || !batchSpeaker.trim()) return;
    setBatchSubmitting(true);
    setBatchTask(null);
    setFailed(false);
    try {
      const res = await voiceworkstationApi.submitVoxCPMBatchDataset({
        speaker_name: batchSpeaker.trim(),
        texts,
        engine: batchEngine,
      });
      // 轮询批量任务进度
      const taskId = res.task_id;
      const poll = async () => {
        try {
          const task = await voiceworkstationApi.getVoxCPMBatchDatasetTask(taskId);
          setBatchTask(task);
          if (task.status === 'pending' || task.status === 'running') {
            setTimeout(poll, 2000);
          }
        } catch {
          // 查询失败静默，下一轮继续
        }
      };
      poll();
    } catch (error) {
      console.error('[SVCPanel] batch submit failed:', error);
      setFailed(true);
    } finally {
      setBatchSubmitting(false);
    }
  };

  const running = trainStatus?.status === 'running' || trainStatus?.status === 'preprocessing';

  return (
    <section className="glass-panel space-y-6 p-5">
      {/* 批量数据集生成（多引擎） */}
      <div className="space-y-4">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <Layers className="h-4 w-4 text-accent" />
          {t('management.audioWorkstation.svcBatchDataset')}
        </h4>
        <p className="text-xs text-muted-foreground">{t('management.audioWorkstation.svcBatchDatasetDesc')}</p>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Field label={t('management.audioWorkstation.svcSpeakerName')}>
            <input
              value={batchSpeaker}
              onChange={(e) => setBatchSpeaker(e.target.value)}
              placeholder={t('management.audioWorkstation.svcSpeakerNamePlaceholder')}
              className={inputClassName}
            />
          </Field>
          <Field label={t('management.audioWorkstation.svcBatchEngine')}>
            <select value={batchEngine} onChange={(e) => setBatchEngine(e.target.value as BatchDatasetEngine)} className={selectClassName}>
              {engineOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label={t('management.audioWorkstation.svcBatchTexts')}>
          <textarea
            value={batchTexts}
            onChange={(e) => setBatchTexts(e.target.value)}
            placeholder={t('management.audioWorkstation.svcBatchTextsPlaceholder')}
            rows={5}
            className={inputClassName}
          />
        </Field>
        <button
          type="button"
          onClick={() => void handleBatchSubmit()}
          disabled={batchSubmitting || !batchSpeaker.trim()}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-accent-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {batchSubmitting && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
          {t('management.audioWorkstation.svcBatchSubmit')}
        </button>
        {batchTask && (
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="rounded bg-accent/20 px-2 py-0.5 text-xs font-medium text-accent">{batchTask.status}</span>
              <span className="text-xs text-muted-foreground">{batchTask.engine}</span>
              {batchTask.total > 0 && (
                <span className="text-xs text-muted-foreground">
                  {batchTask.done} / {batchTask.total}
                </span>
              )}
            </div>
            {batchTask.current_text && <p className="truncate text-sm text-muted-foreground">{batchTask.current_text}</p>}
            {batchTask.error && <p className="text-sm text-red-400">{batchTask.error}</p>}
          </div>
        )}
      </div>

      {/* 数据集管理 + 预处理 + 训练 */}
      <div className="space-y-4">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <Database className="h-4 w-4 text-secondary" />
          {t('management.audioWorkstation.svcDatasets')}
        </h4>
        {datasets.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t('management.audioWorkstation.svcNoDatasets')}</p>
        ) : (
          <div className="space-y-1">
            {datasets.map((ds) => (
              <div
                key={ds.name}
                className="flex items-center justify-between rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2"
              >
                <span className="font-mono text-sm">{ds.name}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-muted-foreground">
                    {t('management.audioWorkstation.svcDatasetFiles')}: {ds.file_count}
                  </span>
                  <button
                    type="button"
                    onClick={() => void handleDeleteDataset(ds.name)}
                    className="rounded-md border border-red-500/40 px-2 py-1 text-xs font-medium text-red-400 transition-opacity hover:bg-red-500/10"
                  >
                    {t('management.audioWorkstation.svcDeleteDataset')}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-end gap-3">
          <div className="flex-1">
            <Field label={t('management.audioWorkstation.svcSpeakerName')}>
              <input
                value={datasetSpeakerName}
                onChange={(e) => setDatasetSpeakerName(e.target.value)}
                placeholder={t('management.audioWorkstation.svcSpeakerNamePlaceholder')}
                className={inputClassName}
              />
            </Field>
          </div>
          <button
            type="button"
            onClick={() => document.getElementById('svc-dataset-file')?.click()}
            disabled={datasetImporting || !datasetSpeakerName.trim()}
            className="rounded-lg bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {datasetImporting && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
            {t('management.audioWorkstation.svcImportDataset')}
          </button>
          <input id="svc-dataset-file" type="file" multiple accept=".wav,.mp3,.flac,.ogg,.zip" className="hidden" onChange={handleImportDataset} />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Field label={t('management.audioWorkstation.svcDataDir')}>
            <input
              value={trainDataDir}
              onChange={(e) => setTrainDataDir(e.target.value)}
              placeholder={t('management.audioWorkstation.svcDataDirPlaceholder')}
              className={inputClassName}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t('management.audioWorkstation.svcSpeaker')}>
              <input
                value={trainSpeakerName}
                onChange={(e) => setTrainSpeakerName(e.target.value)}
                placeholder={t('management.audioWorkstation.svcSpeakerPlaceholder')}
                className={inputClassName}
              />
            </Field>
            <Field label={t('management.audioWorkstation.svcOutputName')}>
              <input
                value={trainOutputName}
                onChange={(e) => setTrainOutputName(e.target.value)}
                placeholder={t('management.audioWorkstation.svcOutputNamePlaceholder')}
                className={inputClassName}
              />
            </Field>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void handlePreprocess()}
            disabled={trainPreprocessing || running || !trainDataDir.trim() || !trainSpeakerName.trim()}
            className="rounded-lg bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {trainPreprocessing && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
            {t('management.audioWorkstation.svcPreprocess')}
          </button>
          {trainPreprocessDone && (
            <span className="rounded bg-success/20 px-2 py-0.5 text-xs font-medium text-success">
              {t('management.audioWorkstation.svcPreprocessDone')}
            </span>
          )}
        </div>

        <div className="grid grid-cols-3 gap-3">
          <Field label={t('management.audioWorkstation.svcEpochs')}>
            <input type="number" value={trainEpochs} onChange={(e) => setTrainEpochs(Number(e.target.value))} className={inputClassName} />
          </Field>
          <Field label={t('management.audioWorkstation.svcBatch')}>
            <input type="number" value={trainBatchSize} onChange={(e) => setTrainBatchSize(Number(e.target.value))} className={inputClassName} />
          </Field>
          <Field label={t('management.audioWorkstation.svcLearningRate')}>
            <input type="number" step="0.0001" value={trainLearningRate} onChange={(e) => setTrainLearningRate(Number(e.target.value))} className={inputClassName} />
          </Field>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void handleTrain()}
            disabled={busy || running}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {busy && running && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
            {t('management.audioWorkstation.svcStartTrain')}
          </button>
          {running && (
            <button
              type="button"
              onClick={() => void handleStop()}
              disabled={busy}
              className="rounded-lg border border-red-500/40 px-4 py-2 text-sm font-medium text-red-400 transition-opacity hover:bg-red-500/10 disabled:opacity-50"
            >
              {t('management.audioWorkstation.svcStopTrain')}
            </button>
          )}
        </div>

        {trainStatus && trainStatus.status !== 'idle' && (
          <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">
                {t('management.audioWorkstation.svcStatusLabel')}: {trainStatus.status}
              </span>
              {trainStatus.total_epochs > 0 && (
                <span className="text-xs text-muted-foreground">
                  {trainStatus.epoch} / {trainStatus.total_epochs}
                </span>
              )}
              {trainStatus.status === 'running' && (
                <span className="text-xs text-muted-foreground">{Math.round(trainStatus.progress * 100)}%</span>
              )}
            </div>
            {trainStatus.message && <p className="text-sm text-muted-foreground">{trainStatus.message}</p>}
          </div>
        )}

        <div>
          <span className="mb-2 block text-sm text-muted-foreground">{t('management.audioWorkstation.svcModelList')}</span>
          {trainModels.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('management.audioWorkstation.svcNoModels')}</p>
          ) : (
            <div className="space-y-1">
              {trainModels.map((model) => (
                <div key={model.path} className="px-3 py-2 font-mono text-sm text-muted-foreground">
                  {model.name}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 推理 */}
      <div className="space-y-3">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <MicVocal className="h-4 w-4 text-primary" />
          {t('management.audioWorkstation.svcInferTitle')}
        </h4>
        <Field label={t('management.audioWorkstation.svcModel')}>
          <select value={inferModelPath} onChange={(e) => setInferModelPath(e.target.value)} className={selectClassName}>
            <option value="">{t('management.audioWorkstation.svcSelectModel')}</option>
            {trainModels.map((m) => (
              <option key={m.path} value={m.path}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t('management.audioWorkstation.svcInferAudioPath')}>
          <input
            value={inferAudioPath}
            onChange={(e) => setInferAudioPath(e.target.value)}
            placeholder={t('management.audioWorkstation.svcInferAudioPlaceholder')}
            className={inputClassName}
          />
        </Field>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Field label={t('management.audioWorkstation.svcSpeakerId')}>
            <input type="number" value={inferSpeakerId} onChange={(e) => setInferSpeakerId(Number(e.target.value))} className={inputClassName} />
          </Field>
          <Field label={t('management.audioWorkstation.svcClusterModelPath')}>
            <input
              value={inferClusterModelPath}
              onChange={(e) => setInferClusterModelPath(e.target.value)}
              placeholder={t('management.audioWorkstation.svcClusterModelPathPlaceholder')}
              className={inputClassName}
            />
          </Field>
        </div>
        <div>
          <span className="mb-1.5 block text-sm text-muted-foreground">
            {t('management.audioWorkstation.svcTranspose')}: {inferTranspose}
          </span>
          <input
            type="range"
            min="-12"
            max="12"
            value={inferTranspose}
            onChange={(e) => setInferTranspose(Number(e.target.value))}
            className="w-full"
          />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>-12</span>
            <span>0</span>
            <span>+12</span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void handleInfer()}
          disabled={busy || !inferAudioPath.trim()}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {busy && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
          {t('management.audioWorkstation.svcInfer')}
        </button>
      </div>

      {failed && <p className="text-xs text-red-400">{t('management.audioWorkstation.svcActionFailed')}</p>}

      {inferResult && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {t('management.audioWorkstation.svcInferResult')} · {inferResult.output_filename}
          </p>
          <audio controls className="w-full" src={getVoiceWorkstationAudioUrl(inferResult.audio_url)} />
        </div>
      )}
    </section>
  );
}

function Field(props: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-sm text-muted-foreground">{props.label}</label>
      {props.children}
    </div>
  );
}