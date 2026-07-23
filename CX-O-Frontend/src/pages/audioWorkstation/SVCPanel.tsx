/**
 * SVC 训练推理 Tab：数据集管理 + 预处理 + 训练 + 推理 + 批量数据集生成（多引擎）。
 *
 * 合并自原 VoiceWorkstationPage step3/step4，并新增批量数据集生成面板（引擎选择）。
 * Spec: refactor-audiostation-engine-consolidation Task 9。
 */
import { useState, useEffect, useCallback } from 'react';
import { api, getVoiceWorkstationAudioUrl } from '@/api/client';
import type {
  SVCModel,
  SVCDataset,
  SVCTrainStatus,
  BatchDatasetTask,
  BatchDatasetEngine,
} from '@/api/client';
import { Button, Card, CardBody, Input, Badge } from '@/components/ui';
import { useTranslation } from 'react-i18next';

const engineOptions: { value: BatchDatasetEngine; labelKey: string }[] = [
  { value: 'voxcpm', labelKey: 'engineVoxcpm' },
  { value: 'orpheustts', labelKey: 'engineOrpheus' },
  { value: 'f5tts', labelKey: 'engineF5tts' },
];

const selectClassName =
  'w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent';

export function SVCPanel() {
  const { t } = useTranslation();

  // ── 数据集管理 + 训练 ──
  const [trainDataDir, setTrainDataDir] = useState('');
  const [trainSpeakerName, setTrainSpeakerName] = useState('');
  const [trainOutputName, setTrainOutputName] = useState('');
  const [trainEpochs, setTrainEpochs] = useState(100);
  const [trainBatchSize, setTrainBatchSize] = useState(4);
  const [trainLearningRate, setTrainLearningRate] = useState(0.0001);
  const [trainPreprocessing, setTrainPreprocessing] = useState(false);
  const [trainPreprocessDone, setTrainPreprocessDone] = useState(false);
  const [trainTraining, setTrainTraining] = useState(false);
  const [trainStatus, setTrainStatus] = useState<SVCTrainStatus | null>(null);
  const [trainModels, setTrainModels] = useState<SVCModel[]>([]);
  const [datasets, setDatasets] = useState<SVCDataset[]>([]);
  const [datasetImporting, setDatasetImporting] = useState(false);
  const [datasetSpeakerName, setDatasetSpeakerName] = useState('');

  // ── 推理 ──
  const [inferModelPath, setInferModelPath] = useState('');
  const [inferAudioPath, setInferAudioPath] = useState('');
  const [inferSpeakerId, setInferSpeakerId] = useState(0);
  const [inferTranspose, setInferTranspose] = useState(0);
  const [inferClusterModelPath, setInferClusterModelPath] = useState('');
  const [inferInferring, setInferInferring] = useState(false);
  const [inferResult, setInferResult] = useState<{ status: string; output_filename: string; audio_url: string } | null>(null);

  // ── 批量数据集生成（多引擎）──
  const [batchSpeaker, setBatchSpeaker] = useState('');
  const [batchEngine, setBatchEngine] = useState<BatchDatasetEngine>('voxcpm');
  const [batchTexts, setBatchTexts] = useState('');
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchTask, setBatchTask] = useState<BatchDatasetTask | null>(null);

  const refreshDatasets = useCallback(() => {
    api.listSVCDatasets().then((r) => setDatasets(r.datasets)).catch(() => {});
  }, []);

  useEffect(() => {
    refreshDatasets();
    const poll = () => {
      api.getSoVITSSVCStatus().then((s) => {
        setTrainStatus(s);
        setTrainModels(s.models || []);
        if (s.status !== 'running') setTrainTraining(false);
      }).catch(() => {});
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, [refreshDatasets]);

  useEffect(() => {
    api.getSoVITSSVCStatus().then((s) => {
      setTrainModels(s.models || []);
    }).catch(() => {});
  }, []);

  // ── 训练处理 ──
  const handlePreprocess = async () => {
    setTrainPreprocessing(true);
    setTrainPreprocessDone(false);
    try {
      await api.sovitsSVCPreprocess({
        training_data_dir: trainDataDir,
        speaker_name: trainSpeakerName,
      });
      setTrainPreprocessDone(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setTrainPreprocessing(false);
    }
  };

  const handleStartTrain = async () => {
    setTrainTraining(true);
    try {
      await api.startSoVITSSVCTrain({
        training_data_dir: trainDataDir || undefined,
        output_name: trainOutputName || undefined,
        epochs: trainEpochs,
        batch_size: trainBatchSize,
        learning_rate: trainLearningRate,
      });
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
      setTrainTraining(false);
    }
  };

  const handleStopTrain = async () => {
    try {
      await api.stopSoVITSSVCTrain();
      setTrainTraining(false);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  const handleImportDataset = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : [];
    if (files.length === 0 || !datasetSpeakerName.trim()) return;
    setDatasetImporting(true);
    try {
      await api.importSVCDataset(datasetSpeakerName.trim(), files);
      refreshDatasets();
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setDatasetImporting(false);
      e.target.value = '';
    }
  };

  const handleDeleteDataset = async (name: string) => {
    if (!window.confirm(t('audioWorkstation.confirmDeleteDataset'))) return;
    try {
      await api.deleteSVCDataset(name);
      refreshDatasets();
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  // ── 推理处理 ──
  const handleInfer = async () => {
    setInferInferring(true);
    setInferResult(null);
    try {
      const result = await api.sovitsSVCInfer({
        audio_path: inferAudioPath,
        model_path: inferModelPath || undefined,
        speaker_id: inferSpeakerId,
        transpose: inferTranspose,
        cluster_model_path: inferClusterModelPath || undefined,
      });
      setInferResult(result);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setInferInferring(false);
    }
  };

  // ── 批量数据集生成处理 ──
  const handleBatchSubmit = async () => {
    const lines = batchTexts
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0 || !batchSpeaker.trim()) return;
    setBatchSubmitting(true);
    setBatchTask(null);
    try {
      const res = await api.submitVoxCPMBatchDataset({
        speaker_name: batchSpeaker.trim(),
        texts: lines.map((text) => ({ text })),
        engine: batchEngine,
      });
      // 轮询任务进度
      const taskId = res.task_id;
      const poll = async () => {
        try {
          const task = await api.getVoxCPMBatchDatasetTask(taskId);
          setBatchTask(task);
          if (task.status === 'pending' || task.status === 'running') {
            setTimeout(poll, 2000);
          }
        } catch {
          // 查询失败静默，下一轮继续
        }
      };
      poll();
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setBatchSubmitting(false);
    }
  };

  const trainBadgeVariant = (status: string) =>
    status === 'running' ? 'warning' : status === 'completed' ? 'success' : status === 'failed' ? 'error' : 'default';

  return (
    <div className="space-y-6">
      {/* 批量数据集生成（多引擎）*/}
      <Card>
        <CardBody className="space-y-5">
          <div>
            <h3 className="text-sm font-medium text-[var(--color-text-primary)]">
              {t('audioWorkstation.batchDataset')}
            </h3>
            <p className="text-xs text-[var(--color-text-tertiary)] mt-1">
              {t('audioWorkstation.batchDatasetDesc')}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Input
              label={t('audioWorkstation.speakerName')}
              value={batchSpeaker}
              onChange={(e) => setBatchSpeaker(e.target.value)}
              placeholder={t('audioWorkstation.speakerNamePlaceholder')}
            />
            <div>
              <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
                {t('audioWorkstation.batchEngine')}
              </label>
              <select
                value={batchEngine}
                onChange={(e) => setBatchEngine(e.target.value as BatchDatasetEngine)}
                className={selectClassName}
              >
                {engineOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(`audioWorkstation.${opt.labelKey}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
              {t('audioWorkstation.batchTexts')}
            </label>
            <textarea
              value={batchTexts}
              onChange={(e) => setBatchTexts(e.target.value)}
              placeholder={t('audioWorkstation.batchTextsPlaceholder')}
              rows={5}
              className={selectClassName}
            />
          </div>

          <Button onClick={handleBatchSubmit} loading={batchSubmitting} disabled={batchSubmitting}>
            {t('audioWorkstation.batchSubmit')}
          </Button>

          {batchTask && (
            <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)] space-y-2">
              <div className="flex items-center gap-2">
                <Badge variant={trainBadgeVariant(batchTask.status)}>{batchTask.status}</Badge>
                <Badge variant="info">{batchTask.engine}</Badge>
                {batchTask.total > 0 && (
                  <span className="text-xs text-[var(--color-text-tertiary)]">
                    {batchTask.done} / {batchTask.total}
                  </span>
                )}
              </div>
              {batchTask.current_text && (
                <p className="text-sm text-[var(--color-text-secondary)] truncate">{batchTask.current_text}</p>
              )}
              {batchTask.error && <p className="text-sm text-red-500">{batchTask.error}</p>}
            </div>
          )}
        </CardBody>
      </Card>

      {/* 数据集管理 + 训练 */}
      <Card>
        <CardBody className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
              {t('audioWorkstation.datasets')}
            </label>
            {datasets.length === 0 ? (
              <p className="text-sm text-[var(--color-text-tertiary)]">{t('audioWorkstation.noDatasets')}</p>
            ) : (
              <div className="space-y-1">
                {datasets.map((ds) => (
                  <div
                    key={ds.name}
                    className="flex items-center justify-between px-3 py-2 rounded-lg bg-[var(--color-bg-tertiary)]"
                  >
                    <span className="text-sm font-mono text-[var(--color-text-primary)]">{ds.name}</span>
                    <div className="flex items-center gap-3">
                      <Badge variant="info">
                        {t('audioWorkstation.datasetFiles')}: {ds.file_count}
                      </Badge>
                      <Button variant="danger" size="sm" onClick={() => handleDeleteDataset(ds.name)}>
                        {t('audioWorkstation.deleteDataset')}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center gap-3 mt-3">
              <Input
                value={datasetSpeakerName}
                onChange={(e) => setDatasetSpeakerName(e.target.value)}
                placeholder={t('audioWorkstation.speakerNamePlaceholder')}
              />
              <Button
                variant="secondary"
                onClick={() => document.getElementById('svc-dataset-file')?.click()}
                loading={datasetImporting}
                disabled={!datasetSpeakerName.trim()}
              >
                {t('audioWorkstation.importDataset')}
              </Button>
              <input
                id="svc-dataset-file"
                type="file"
                multiple
                accept=".wav,.mp3,.flac,.ogg,.zip"
                className="hidden"
                onChange={handleImportDataset}
              />
            </div>
          </div>

          <Input
            label={t('audioWorkstation.trainingDataDir')}
            value={trainDataDir}
            onChange={(e) => setTrainDataDir(e.target.value)}
            placeholder={t('audioWorkstation.trainingDataDirPlaceholder')}
          />

          <div className="grid grid-cols-2 gap-4">
            <Input
              label={t('audioWorkstation.speakerName')}
              value={trainSpeakerName}
              onChange={(e) => setTrainSpeakerName(e.target.value)}
              placeholder={t('audioWorkstation.speakerNamePlaceholder')}
            />
            <Input
              label={t('audioWorkstation.outputName')}
              value={trainOutputName}
              onChange={(e) => setTrainOutputName(e.target.value)}
              placeholder={t('audioWorkstation.outputNamePlaceholder')}
            />
          </div>

          <div className="flex items-center gap-3">
            <Button variant="secondary" onClick={handlePreprocess} loading={trainPreprocessing}>
              {t('audioWorkstation.preprocess')}
            </Button>
            {trainPreprocessDone && (
              <Badge variant="success">{t('audioWorkstation.preprocessDone')}</Badge>
            )}
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Input
              label={t('audioWorkstation.epochs')}
              type="number"
              value={trainEpochs}
              onChange={(e) => setTrainEpochs(Number(e.target.value))}
            />
            <Input
              label={t('audioWorkstation.batchSize')}
              type="number"
              value={trainBatchSize}
              onChange={(e) => setTrainBatchSize(Number(e.target.value))}
            />
            <Input
              label={t('audioWorkstation.learningRate')}
              type="number"
              step="0.0001"
              value={trainLearningRate}
              onChange={(e) => setTrainLearningRate(Number(e.target.value))}
            />
          </div>

          <div className="flex items-center gap-3">
            <Button onClick={handleStartTrain} loading={trainTraining} disabled={trainTraining}>
              {t('audioWorkstation.startTraining')}
            </Button>
            {trainTraining && (
              <Button variant="danger" onClick={handleStopTrain}>
                {t('audioWorkstation.stopTraining')}
              </Button>
            )}
          </div>

          {trainStatus && (
            <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)] space-y-2">
              <div className="flex items-center gap-2">
                <Badge variant={trainBadgeVariant(trainStatus.status)}>{trainStatus.status}</Badge>
                {trainStatus.total_epochs > 0 && (
                  <span className="text-xs text-[var(--color-text-tertiary)]">
                    {trainStatus.epoch} / {trainStatus.total_epochs}
                  </span>
                )}
                {trainStatus.status === 'running' && (
                  <div className="flex-1">
                    <div className="w-full bg-[var(--color-bg-primary)] rounded-full h-2">
                      <div
                        className="bg-[var(--color-accent)] h-2 rounded-full transition-all"
                        style={{ width: `${Math.round(trainStatus.progress * 100)}%` }}
                      />
                    </div>
                    <span className="text-xs text-[var(--color-text-tertiary)]">
                      {Math.round(trainStatus.progress * 100)}%
                    </span>
                  </div>
                )}
              </div>
              {trainStatus.message && (
                <p className="text-sm text-[var(--color-text-secondary)]">{trainStatus.message}</p>
              )}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
              {t('audioWorkstation.modelList')}
            </label>
            {trainModels.length === 0 ? (
              <p className="text-sm text-[var(--color-text-tertiary)]">{t('audioWorkstation.noModels')}</p>
            ) : (
              <div className="space-y-1">
                {trainModels.map((model) => (
                  <div key={model.path} className="px-3 py-2 rounded-lg bg-[var(--color-bg-tertiary)] text-sm font-mono text-[var(--color-text-primary)]">
                    {model.name}
                  </div>
                ))}
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* 推理 */}
      <Card>
        <CardBody className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
              {t('audioWorkstation.modelSelect')}
            </label>
            <select
              value={inferModelPath}
              onChange={(e) => setInferModelPath(e.target.value)}
              className={selectClassName}
            >
              <option value="">{t('audioWorkstation.selectModel')}</option>
              {trainModels.map((model) => (
                <option key={model.path} value={model.path}>{model.name}</option>
              ))}
            </select>
          </div>

          <Input
            label={t('audioWorkstation.inputAudioPath')}
            value={inferAudioPath}
            onChange={(e) => setInferAudioPath(e.target.value)}
            placeholder={t('audioWorkstation.inputAudioPathPlaceholder')}
          />

          <div className="grid grid-cols-2 gap-4">
            <Input
              label={t('audioWorkstation.speakerId')}
              type="number"
              value={inferSpeakerId}
              onChange={(e) => setInferSpeakerId(Number(e.target.value))}
            />
            <Input
              label={t('audioWorkstation.clusterModelPath')}
              value={inferClusterModelPath}
              onChange={(e) => setInferClusterModelPath(e.target.value)}
              placeholder={t('audioWorkstation.clusterModelPathPlaceholder')}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
              {t('audioWorkstation.transpose')}: {inferTranspose}
            </label>
            <input
              type="range"
              min="-12"
              max="12"
              value={inferTranspose}
              onChange={(e) => setInferTranspose(Number(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between text-xs text-[var(--color-text-tertiary)]">
              <span>-12</span>
              <span>0</span>
              <span>+12</span>
            </div>
          </div>

          <Button onClick={handleInfer} loading={inferInferring}>
            {t('audioWorkstation.startInference')}
          </Button>

          {inferResult && (
            <div className="space-y-3">
              <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)]">
                <span className="text-sm text-[var(--color-text-secondary)]">{t('audioWorkstation.outputFileName')}:</span>
                <span className="ml-2 text-sm font-mono text-[var(--color-text-primary)]">{inferResult.output_filename}</span>
              </div>
              <audio controls className="w-full" src={getVoiceWorkstationAudioUrl(inferResult.audio_url)} />
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
