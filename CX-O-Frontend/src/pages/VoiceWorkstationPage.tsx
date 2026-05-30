import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';
import { cn } from '../lib/utils';
import { PageHeader } from '../components/layout';
import { Button, Card, CardBody, Input, Textarea, Badge } from '../components/ui';
import { useTranslation } from 'react-i18next';

type VoxCPMMode = 'design' | 'controllable_clone' | 'ultimate_clone';
type StepIndex = 0 | 1 | 2 | 3;

const STEPS = [
  { id: 'voxcpm', labelKey: 'step1' },
  { id: 'cosyvoice', labelKey: 'step2' },
  { id: 'train', labelKey: 'step3' },
  { id: 'infer', labelKey: 'step4' },
];

export function VoiceWorkstationPage() {
  const { t } = useTranslation();
  const [activeStep, setActiveStep] = useState<StepIndex>(0);

  const [voxcpmMode, setVoxcpmMode] = useState<VoxCPMMode>('design');
  const [voxcpmText, setVoxcpmText] = useState('');
  const [voxcpmControl, setVoxcpmControl] = useState('');
  const [voxcpmRefAudioPath, setVoxcpmRefAudioPath] = useState('');
  const [voxcpmPromptAudioPath, setVoxcpmPromptAudioPath] = useState('');
  const [voxcpmPromptText, setVoxcpmPromptText] = useState('');
  const [voxcpmStatus, setVoxcpmStatus] = useState<{ status: string; model_path: string } | null>(null);
  const [voxcpmOutput, setVoxcpmOutput] = useState('');
  const [voxcpmGenerating, setVoxcpmGenerating] = useState(false);

  const [cosyBaseAudioPath, setCosyBaseAudioPath] = useState('');
  const [cosySampleText, setCosySampleText] = useState('');
  const [cosyTransitionText, setCosyTransitionText] = useState('');
  const [cosyGenerating, setCosyGenerating] = useState(false);
  const [cosyExporting, setCosyExporting] = useState(false);
  const [cosyImporting, setCosyImporting] = useState(false);
  const [cosyEmotionsCount, setCosyEmotionsCount] = useState(0);
  const [cosyTransitionsCount, setCosyTransitionsCount] = useState(0);
  const [cosyOutputDir, setCosyOutputDir] = useState('');
  const importFileRef = useRef<HTMLInputElement>(null);

  const [trainDataDir, setTrainDataDir] = useState('');
  const [trainSpeakerName, setTrainSpeakerName] = useState('');
  const [trainEpochs, setTrainEpochs] = useState(100);
  const [trainBatchSize, setTrainBatchSize] = useState(4);
  const [trainLearningRate, setTrainLearningRate] = useState(0.0001);
  const [trainPreprocessing, setTrainPreprocessing] = useState(false);
  const [trainTraining, setTrainTraining] = useState(false);
  const [trainStatus, setTrainStatus] = useState<{ status: string; progress?: number; message?: string; models?: string[] } | null>(null);
  const [trainModels, setTrainModels] = useState<string[]>([]);

  const [inferModel, setInferModel] = useState('');
  const [inferInputAudioPath, setInferInputAudioPath] = useState('');
  const [inferTranspose, setInferTranspose] = useState(0);
  const [inferInferring, setInferInferring] = useState(false);
  const [inferOutputPath, setInferOutputPath] = useState('');

  useEffect(() => {
    api.getVoxCPMStatus().then(setVoxcpmStatus).catch(() => setVoxcpmStatus(null));
  }, []);

  useEffect(() => {
    if (activeStep !== 2) return;
    const poll = () => {
      api.getSoVITSSVCStatus().then((s) => {
        setTrainStatus(s);
        if (s.models) setTrainModels(s.models);
      }).catch(() => {});
    };
    poll();
    const interval = setInterval(poll, 5000);
    return () => clearInterval(interval);
  }, [activeStep]);

  useEffect(() => {
    if (activeStep === 3) {
      api.getSoVITSSVCStatus().then((s) => {
        if (s.models) setTrainModels(s.models);
      }).catch(() => {});
    }
  }, [activeStep]);

  const handleVoxCPMGenerate = async () => {
    setVoxcpmGenerating(true);
    try {
      const result = await api.generateVoxCPM({
        mode: voxcpmMode,
        text: voxcpmText,
        control: voxcpmMode !== 'ultimate_clone' ? voxcpmControl : undefined,
        reference_audio_path: voxcpmMode === 'controllable_clone' ? voxcpmRefAudioPath : undefined,
        prompt_audio_path: voxcpmMode === 'ultimate_clone' ? voxcpmPromptAudioPath : undefined,
        prompt_text: voxcpmMode === 'ultimate_clone' ? voxcpmPromptText : undefined,
      });
      setVoxcpmOutput(result.output_path);
      setCosyBaseAudioPath(result.output_path);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setVoxcpmGenerating(false);
    }
  };

  const handleCosyGenerate = async () => {
    setCosyGenerating(true);
    try {
      const result = await api.pregenerateRefs({
        base_audio_path: cosyBaseAudioPath,
        sample_text: cosySampleText || undefined,
        transition_text: cosyTransitionText || undefined,
      });
      setCosyEmotionsCount(result.emotions_count);
      setCosyTransitionsCount(result.transitions_count);
      setCosyOutputDir(cosyBaseAudioPath.replace(/\.[^.]+$/, '') + '_refs');
      setTrainDataDir(cosyBaseAudioPath.replace(/\.[^.]+$/, '') + '_refs');
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setCosyGenerating(false);
    }
  };

  const handleCosyExport = async () => {
    setCosyExporting(true);
    try {
      const blob = await api.exportEmotionRefsZip({
        base_audio_path: cosyBaseAudioPath,
        sample_text: cosySampleText || undefined,
        transition_text: cosyTransitionText || undefined,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'emotion_refs.zip';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setCosyExporting(false);
    }
  };

  const handleCosyImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCosyImporting(true);
    try {
      const result = await api.importEmotionRefsZip(file);
      setCosyEmotionsCount(result.meta.emotions.length);
      setCosyTransitionsCount(result.meta.transitions.length);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setCosyImporting(false);
      if (importFileRef.current) importFileRef.current.value = '';
    }
  };

  const handlePreprocess = async () => {
    setTrainPreprocessing(true);
    try {
      await api.sovitsSVCPreprocess({
        training_data_dir: trainDataDir,
        speaker_name: trainSpeakerName,
      });
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
        training_data_dir: trainDataDir,
        model_name: trainSpeakerName || undefined,
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

  const handleInfer = async () => {
    setInferInferring(true);
    try {
      const result = await api.sovitsSVCInfer({
        input_audio_path: inferInputAudioPath,
        ref_audio_path: inferModel || undefined,
      });
      setInferOutputPath(result.output_path);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setInferInferring(false);
    }
  };

  const modeOptions: { value: VoxCPMMode; labelKey: string }[] = [
    { value: 'design', labelKey: 'design' },
    { value: 'controllable_clone', labelKey: 'controllableClone' },
    { value: 'ultimate_clone', labelKey: 'ultimateClone' },
  ];

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-6">
        <PageHeader title={t('voiceWorkstation.title')} description={t('voiceWorkstation.description')} />
      </div>

      <div className="px-6 pb-4">
        <div className="flex items-center gap-1">
          {STEPS.map((step, idx) => (
            <button
              key={step.id}
              onClick={() => setActiveStep(idx as StepIndex)}
              className={cn(
                'flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
                activeStep === idx
                  ? 'bg-[var(--color-accent)] text-white'
                  : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'
              )}
            >
              <span className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold bg-white/20">
                {idx + 1}
              </span>
              {t(`voiceWorkstation.${step.labelKey}`)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {activeStep === 0 && (
          <Card>
            <CardBody className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
                  {t('voiceWorkstation.mode')}
                </label>
                <div className="flex gap-2">
                  {modeOptions.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setVoxcpmMode(opt.value)}
                      className={cn(
                        'px-4 py-2 rounded-lg text-sm font-medium transition-colors border',
                        voxcpmMode === opt.value
                          ? 'bg-[var(--color-accent)] text-white border-[var(--color-accent)]'
                          : 'bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] border-[var(--color-border)] hover:border-[var(--color-accent)]'
                      )}
                    >
                      {t(`voiceWorkstation.${opt.labelKey}`)}
                    </button>
                  ))}
                </div>
              </div>

              <Textarea
                label={t('voiceWorkstation.targetText')}
                value={voxcpmText}
                onChange={(e) => setVoxcpmText(e.target.value)}
                placeholder={t('voiceWorkstation.targetTextPlaceholder')}
                rows={4}
              />

              {voxcpmMode !== 'ultimate_clone' && (
                <Textarea
                  label={t('voiceWorkstation.controlInstruction')}
                  value={voxcpmControl}
                  onChange={(e) => setVoxcpmControl(e.target.value)}
                  placeholder={t('voiceWorkstation.controlInstructionPlaceholder')}
                  rows={3}
                />
              )}

              {voxcpmMode === 'controllable_clone' && (
                <Input
                  label={t('voiceWorkstation.refAudioPath')}
                  value={voxcpmRefAudioPath}
                  onChange={(e) => setVoxcpmRefAudioPath(e.target.value)}
                  placeholder={t('voiceWorkstation.refAudioPathPlaceholder')}
                />
              )}

              {voxcpmMode === 'ultimate_clone' && (
                <>
                  <Input
                    label={t('voiceWorkstation.promptAudioPath')}
                    value={voxcpmPromptAudioPath}
                    onChange={(e) => setVoxcpmPromptAudioPath(e.target.value)}
                    placeholder={t('voiceWorkstation.promptAudioPathPlaceholder')}
                  />
                  <Input
                    label={t('voiceWorkstation.promptText')}
                    value={voxcpmPromptText}
                    onChange={(e) => setVoxcpmPromptText(e.target.value)}
                    placeholder={t('voiceWorkstation.promptTextPlaceholder')}
                  />
                </>
              )}

              <div className="flex items-center gap-4">
                <Button onClick={handleVoxCPMGenerate} loading={voxcpmGenerating}>
                  {t('voiceWorkstation.generate')}
                </Button>
                {voxcpmStatus && (
                  <Badge variant={voxcpmStatus.status === 'ready' ? 'success' : 'warning'}>
                    VoxCPM: {voxcpmStatus.status}
                  </Badge>
                )}
              </div>

              {voxcpmOutput && (
                <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)]">
                  <span className="text-sm text-[var(--color-text-secondary)]">{t('voiceWorkstation.outputPath')}:</span>
                  <span className="ml-2 text-sm font-mono text-[var(--color-text-primary)]">{voxcpmOutput}</span>
                </div>
              )}
            </CardBody>
          </Card>
        )}

        {activeStep === 1 && (
          <Card>
            <CardBody className="space-y-5">
              <Input
                label={t('voiceWorkstation.baseAudioPath')}
                value={cosyBaseAudioPath}
                onChange={(e) => setCosyBaseAudioPath(e.target.value)}
                placeholder={t('voiceWorkstation.baseAudioPathPlaceholder')}
              />

              <Input
                label={t('voiceWorkstation.sampleText')}
                value={cosySampleText}
                onChange={(e) => setCosySampleText(e.target.value)}
                placeholder={t('voiceWorkstation.sampleTextPlaceholder')}
              />

              <Input
                label={t('voiceWorkstation.transitionText')}
                value={cosyTransitionText}
                onChange={(e) => setCosyTransitionText(e.target.value)}
                placeholder={t('voiceWorkstation.transitionTextPlaceholder')}
              />

              <div className="flex items-center gap-3">
                <Button onClick={handleCosyGenerate} loading={cosyGenerating}>
                  {t('voiceWorkstation.generateRefs')}
                </Button>
                <Button variant="secondary" onClick={handleCosyExport} loading={cosyExporting}>
                  {t('voiceWorkstation.exportZip')}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => importFileRef.current?.click()}
                  loading={cosyImporting}
                >
                  {t('voiceWorkstation.importZip')}
                </Button>
                <input
                  ref={importFileRef}
                  type="file"
                  accept=".zip"
                  className="hidden"
                  onChange={handleCosyImport}
                />
              </div>

              {(cosyEmotionsCount > 0 || cosyTransitionsCount > 0) && (
                <div className="flex gap-4">
                  <Badge variant="info">
                    {t('voiceWorkstation.emotionCount')}: {cosyEmotionsCount}
                  </Badge>
                  <Badge variant="info">
                    {t('voiceWorkstation.transitionCount')}: {cosyTransitionsCount}
                  </Badge>
                </div>
              )}

              {cosyOutputDir && (
                <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)]">
                  <span className="text-sm text-[var(--color-text-secondary)]">{t('voiceWorkstation.outputDir')}:</span>
                  <span className="ml-2 text-sm font-mono text-[var(--color-text-primary)]">{cosyOutputDir}</span>
                </div>
              )}
            </CardBody>
          </Card>
        )}

        {activeStep === 2 && (
          <Card>
            <CardBody className="space-y-5">
              <Input
                label={t('voiceWorkstation.trainingDataDir')}
                value={trainDataDir}
                onChange={(e) => setTrainDataDir(e.target.value)}
                placeholder={t('voiceWorkstation.trainingDataDirPlaceholder')}
              />

              <Input
                label={t('voiceWorkstation.speakerName')}
                value={trainSpeakerName}
                onChange={(e) => setTrainSpeakerName(e.target.value)}
                placeholder={t('voiceWorkstation.speakerNamePlaceholder')}
              />

              <div className="flex gap-4">
                <Button variant="secondary" onClick={handlePreprocess} loading={trainPreprocessing}>
                  {t('voiceWorkstation.preprocess')}
                </Button>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <Input
                  label={t('voiceWorkstation.epochs')}
                  type="number"
                  value={trainEpochs}
                  onChange={(e) => setTrainEpochs(Number(e.target.value))}
                />
                <Input
                  label={t('voiceWorkstation.batchSize')}
                  type="number"
                  value={trainBatchSize}
                  onChange={(e) => setTrainBatchSize(Number(e.target.value))}
                />
                <Input
                  label={t('voiceWorkstation.learningRate')}
                  type="number"
                  step="0.0001"
                  value={trainLearningRate}
                  onChange={(e) => setTrainLearningRate(Number(e.target.value))}
                />
              </div>

              <div className="flex items-center gap-3">
                <Button onClick={handleStartTrain} loading={trainTraining} disabled={trainTraining}>
                  {t('voiceWorkstation.startTraining')}
                </Button>
                {trainTraining && (
                  <Button variant="danger" onClick={handleStopTrain}>
                    {t('voiceWorkstation.stopTraining')}
                  </Button>
                )}
              </div>

              {trainStatus && (
                <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)] space-y-2">
                  <div className="flex items-center gap-2">
                    <Badge variant={trainStatus.status === 'training' ? 'warning' : trainStatus.status === 'idle' ? 'default' : 'success'}>
                      {trainStatus.status}
                    </Badge>
                    {trainStatus.progress !== undefined && (
                      <div className="flex-1">
                        <div className="w-full bg-[var(--color-bg-primary)] rounded-full h-2">
                          <div
                            className="bg-[var(--color-accent)] h-2 rounded-full transition-all"
                            style={{ width: `${trainStatus.progress}%` }}
                          />
                        </div>
                        <span className="text-xs text-[var(--color-text-tertiary)]">{trainStatus.progress}%</span>
                      </div>
                    )}
                  </div>
                  {trainStatus.message && (
                    <p className="text-sm text-[var(--color-text-secondary)]">{trainStatus.message}</p>
                  )}
                </div>
              )}

              {trainModels.length > 0 && (
                <div>
                  <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
                    {t('voiceWorkstation.modelList')}
                  </label>
                  <div className="space-y-1">
                    {trainModels.map((model) => (
                      <div key={model} className="px-3 py-2 rounded-lg bg-[var(--color-bg-tertiary)] text-sm font-mono text-[var(--color-text-primary)]">
                        {model}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardBody>
          </Card>
        )}

        {activeStep === 3 && (
          <Card>
            <CardBody className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
                  {t('voiceWorkstation.modelSelect')}
                </label>
                <select
                  value={inferModel}
                  onChange={(e) => setInferModel(e.target.value)}
                  className="w-full px-4 py-2.5 text-sm rounded-[var(--radius-md)] bg-[var(--color-bg-primary)] text-[var(--color-text-primary)] border border-[var(--color-border)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:border-transparent"
                >
                  <option value="">{t('voiceWorkstation.selectModel')}</option>
                  {trainModels.map((model) => (
                    <option key={model} value={model}>{model}</option>
                  ))}
                </select>
              </div>

              <Input
                label={t('voiceWorkstation.inputAudioPath')}
                value={inferInputAudioPath}
                onChange={(e) => setInferInputAudioPath(e.target.value)}
                placeholder={t('voiceWorkstation.inputAudioPathPlaceholder')}
              />

              <div>
                <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-1.5">
                  {t('voiceWorkstation.transpose')}: {inferTranspose}
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
                {t('voiceWorkstation.startInference')}
              </Button>

              {inferOutputPath && (
                <div className="space-y-3">
                  <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)]">
                    <span className="text-sm text-[var(--color-text-secondary)]">{t('voiceWorkstation.outputPath')}:</span>
                    <span className="ml-2 text-sm font-mono text-[var(--color-text-primary)]">{inferOutputPath}</span>
                  </div>
                  <audio controls className="w-full">
                    <source src={inferOutputPath} />
                  </audio>
                </div>
              )}
            </CardBody>
          </Card>
        )}
      </div>
    </div>
  );
}
