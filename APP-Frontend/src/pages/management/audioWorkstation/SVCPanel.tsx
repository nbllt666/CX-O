/**
 * SVC 训练推理 Tab（SubTask 7.4 · 音频工作站）
 *
 * 消费 voiceworkstationApi 的 So-VITS-SVC 域：
 * getSoVITSSVCStatus / listSoVITSSVCModels / sovitsSVCPreprocess /
 * startSoVITSSVCTrain / stopSoVITSSVCTrain / sovitsSVCInfer。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Cpu, Loader2, TrainFront, MicVocal } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type { SVCTrainStatus, SVCModel, VoiceWsAudioResult } from '@/api/clients/voiceworkstation';

export default function SVCPanel() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<SVCTrainStatus | null>(null);
  const [models, setModels] = useState<SVCModel[]>([]);
  const [dataDir, setDataDir] = useState('');
  const [speaker, setSpeaker] = useState('');
  const [epochs, setEpochs] = useState('100');
  const [batchSize, setBatchSize] = useState('4');
  const [lr, setLr] = useState('0.0001');
  const [inferAudioPath, setInferAudioPath] = useState('');
  const [inferModel, setInferModel] = useState('');
  const [transpose, setTranspose] = useState('0');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [inferResult, setInferResult] = useState<VoiceWsAudioResult | null>(null);

  const load = useCallback(() => {
    voiceworkstationApi.getSoVITSSVCStatus().then(setStatus).catch(() => setStatus(null));
    voiceworkstationApi
      .listSoVITSSVCModels()
      .then((res) => setModels(res.models ?? []))
      .catch(() => setModels([]));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handlePreprocess = async () => {
    if (!dataDir.trim() || !speaker.trim()) return;
    setBusy(true);
    setFailed(false);
    try {
      await voiceworkstationApi.sovitsSVCPreprocess({ training_data_dir: dataDir.trim(), speaker_name: speaker.trim() });
      await load();
    } catch (error) {
      console.error('[SVCPanel] preprocess failed:', error);
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const handleTrain = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await voiceworkstationApi.startSoVITSSVCTrain({
        training_data_dir: dataDir.trim() || undefined,
        epochs: Number.parseInt(epochs, 10) || 100,
        batch_size: Number.parseInt(batchSize, 10) || 4,
        learning_rate: Number.parseFloat(lr) || 0.0001,
      });
      await load();
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
      await load();
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
        model_path: inferModel || undefined,
        transpose: Number.parseInt(transpose, 10) || 0,
      });
      setInferResult(res);
    } catch (error) {
      console.error('[SVCPanel] infer failed:', error);
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const running = status?.status === 'running' || status?.status === 'preprocessing';

  return (
    <section className="glass-panel space-y-6 p-5">
      {/* 训练状态 */}
      <div>
        <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <Cpu className="h-4 w-4 text-primary" />
          {t('management.audioWorkstation.svcStatusTitle')}
        </h4>
        <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2 text-sm">
          <span className="text-muted-foreground">
            {t('management.audioWorkstation.svcStatusLabel')}:{' '}
            {status?.status ?? t('management.audioWorkstation.svcIdle')}
          </span>
          {status && running && status.total_epochs > 0 && (
            <span className="ml-3 text-xs text-muted-foreground">
              {t('management.audioWorkstation.svcEpoch')}: {status.epoch}/{status.total_epochs} · {status.progress}%
            </span>
          )}
        </div>
      </div>

      {/* 数据预处理 + 训练 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-3">
          <h4 className="flex items-center gap-2 text-sm font-semibold">
            <TrainFront className="h-4 w-4 text-secondary" />
            {t('management.audioWorkstation.svcPreprocess')}
          </h4>
          <Field label={t('management.audioWorkstation.svcDataDir')}>
            <input
              value={dataDir}
              onChange={(e) => setDataDir(e.target.value)}
              placeholder={t('management.audioWorkstation.svcDataDirPlaceholder')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </Field>
          <Field label={t('management.audioWorkstation.svcSpeaker')}>
            <input
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
              placeholder={t('management.audioWorkstation.svcSpeakerPlaceholder')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </Field>
          <button
            type="button"
            onClick={() => void handlePreprocess()}
            disabled={busy || running || !dataDir.trim() || !speaker.trim()}
            className="rounded-lg bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {t('management.audioWorkstation.svcPreprocess')}
          </button>
        </div>

        <div className="space-y-3">
          <h4 className="flex items-center gap-2 text-sm font-semibold">
            <TrainFront className="h-4 w-4 text-accent" />
            {t('management.audioWorkstation.svcTrainTitle')}
          </h4>
          <div className="grid grid-cols-3 gap-3">
            <Field label={t('management.audioWorkstation.svcEpochs')}>
              <input type="number" value={epochs} onChange={(e) => setEpochs(e.target.value)} className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none" />
            </Field>
            <Field label={t('management.audioWorkstation.svcBatch')}>
              <input type="number" value={batchSize} onChange={(e) => setBatchSize(e.target.value)} className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none" />
            </Field>
            <Field label={t('management.audioWorkstation.svcLearningRate')}>
              <input value={lr} onChange={(e) => setLr(e.target.value)} className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none" />
            </Field>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void handleTrain()}
              disabled={busy || running}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {busy && running ? (
                <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />
              ) : null}
              {t('management.audioWorkstation.svcStartTrain')}
            </button>
            <button
              type="button"
              onClick={() => void handleStop()}
              disabled={busy || !running}
              className="rounded-lg border border-red-500/40 px-4 py-2 text-sm font-medium text-red-400 transition-opacity hover:bg-red-500/10 disabled:opacity-50"
            >
              {t('management.audioWorkstation.svcStopTrain')}
            </button>
          </div>
        </div>
      </div>

      {/* 推理 */}
      <div className="space-y-3">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <MicVocal className="h-4 w-4 text-primary" />
          {t('management.audioWorkstation.svcInferTitle')}
        </h4>
        <Field label={t('management.audioWorkstation.svcInferAudioPath')}>
          <input
            value={inferAudioPath}
            onChange={(e) => setInferAudioPath(e.target.value)}
            placeholder={t('management.audioWorkstation.svcInferAudioPlaceholder')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label={t('management.audioWorkstation.svcModel')}>
            <select
              value={inferModel}
              onChange={(e) => setInferModel(e.target.value)}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            >
              <option value="">{t('management.audioWorkstation.svcNoModels')}</option>
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('management.audioWorkstation.svcTranspose')}>
            <input value={transpose} onChange={(e) => setTranspose(e.target.value)} className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none" />
          </Field>
        </div>
        <button
          type="button"
          onClick={() => void handleInfer()}
          disabled={busy || !inferAudioPath.trim()}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {t('management.audioWorkstation.svcInfer')}
        </button>
      </div>

      {failed && <p className="text-xs text-red-400">{t('management.audioWorkstation.svcActionFailed')}</p>}

      {inferResult && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">{t('management.audioWorkstation.svcInferResult')}</p>
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
