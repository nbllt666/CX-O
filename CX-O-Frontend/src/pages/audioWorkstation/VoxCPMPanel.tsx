/**
 * VoxCPM 生成 Tab：单条参考音频生成（声音设计 / 可控克隆 / 极致克隆）。
 *
 * 提取自原 VoiceWorkstationPage step1。Spec: refactor-audiostation-engine-consolidation Task 9。
 */
import { useState, useEffect } from 'react';
import { api, getVoiceWorkstationAudioUrl } from '@/api/client';
import type { VoxCPMMode, VoiceWsAudioResult } from '@/api/client';
import { cn } from '@/lib/utils';
import { Button, Card, CardBody, Input, Textarea, Badge } from '@/components/ui-v2';
import { useTranslation } from 'react-i18next';

const modeOptions: { value: VoxCPMMode; labelKey: string }[] = [
  { value: 'design', labelKey: 'design' },
  { value: 'controllable_clone', labelKey: 'controllableClone' },
  { value: 'ultimate_clone', labelKey: 'ultimateClone' },
];

export function VoxCPMPanel() {
  const { t } = useTranslation();
  const [voxcpmMode, setVoxcpmMode] = useState<VoxCPMMode>('design');
  const [voxcpmText, setVoxcpmText] = useState('');
  const [voxcpmControl, setVoxcpmControl] = useState('');
  const [voxcpmRefAudioPath, setVoxcpmRefAudioPath] = useState('');
  const [voxcpmPromptAudioPath, setVoxcpmPromptAudioPath] = useState('');
  const [voxcpmPromptText, setVoxcpmPromptText] = useState('');
  const [voxcpmCfgValue, setVoxcpmCfgValue] = useState('');
  const [voxcpmTimesteps, setVoxcpmTimesteps] = useState('');
  const [voxcpmStatus, setVoxcpmStatus] = useState<{ status: string; model_path: string } | null>(null);
  const [voxcpmResult, setVoxcpmResult] = useState<VoiceWsAudioResult | null>(null);
  const [voxcpmGenerating, setVoxcpmGenerating] = useState(false);

  useEffect(() => {
    api.getVoxCPMStatus().then(setVoxcpmStatus).catch(() => setVoxcpmStatus(null));
  }, []);

  const handleVoxCPMGenerate = async () => {
    setVoxcpmGenerating(true);
    setVoxcpmResult(null);
    try {
      const cfg = parseFloat(voxcpmCfgValue);
      const steps = parseInt(voxcpmTimesteps, 10);
      const result = await api.generateVoxCPM({
        mode: voxcpmMode,
        text: voxcpmText,
        control: voxcpmMode !== 'ultimate_clone' ? voxcpmControl : undefined,
        reference_audio_path: voxcpmMode === 'controllable_clone' ? voxcpmRefAudioPath : undefined,
        prompt_audio_path: voxcpmMode === 'ultimate_clone' ? voxcpmPromptAudioPath : undefined,
        prompt_text: voxcpmMode === 'ultimate_clone' ? voxcpmPromptText : undefined,
        cfg_value: !isNaN(cfg) ? cfg : undefined,
        inference_timesteps: !isNaN(steps) ? steps : undefined,
      });
      setVoxcpmResult(result);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setVoxcpmGenerating(false);
    }
  };

  return (
    <Card>
      <CardBody className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
            {t('audioWorkstation.mode')}
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
                {t(`audioWorkstation.${opt.labelKey}`)}
              </button>
            ))}
          </div>
        </div>

        <Textarea
          label={t('audioWorkstation.targetText')}
          value={voxcpmText}
          onChange={(e) => setVoxcpmText(e.target.value)}
          placeholder={t('audioWorkstation.targetTextPlaceholder')}
          rows={4}
        />

        {voxcpmMode !== 'ultimate_clone' && (
          <Textarea
            label={t('audioWorkstation.controlInstruction')}
            value={voxcpmControl}
            onChange={(e) => setVoxcpmControl(e.target.value)}
            placeholder={t('audioWorkstation.controlInstructionPlaceholder')}
            rows={3}
          />
        )}

        {voxcpmMode === 'controllable_clone' && (
          <Input
            label={t('audioWorkstation.refAudioPath')}
            value={voxcpmRefAudioPath}
            onChange={(e) => setVoxcpmRefAudioPath(e.target.value)}
            placeholder={t('audioWorkstation.refAudioPathPlaceholder')}
          />
        )}

        {voxcpmMode === 'ultimate_clone' && (
          <>
            <Input
              label={t('audioWorkstation.promptAudioPath')}
              value={voxcpmPromptAudioPath}
              onChange={(e) => setVoxcpmPromptAudioPath(e.target.value)}
              placeholder={t('audioWorkstation.promptAudioPathPlaceholder')}
            />
            <Input
              label={t('audioWorkstation.promptText')}
              value={voxcpmPromptText}
              onChange={(e) => setVoxcpmPromptText(e.target.value)}
              placeholder={t('audioWorkstation.promptTextPlaceholder')}
            />
          </>
        )}

        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
            {t('audioWorkstation.advancedParams')}
          </label>
          <div className="grid grid-cols-2 gap-4">
            <Input
              label={t('audioWorkstation.cfgValue')}
              type="number"
              step="0.1"
              value={voxcpmCfgValue}
              onChange={(e) => setVoxcpmCfgValue(e.target.value)}
              placeholder={t('audioWorkstation.optionalPlaceholder')}
            />
            <Input
              label={t('audioWorkstation.inferenceTimesteps')}
              type="number"
              value={voxcpmTimesteps}
              onChange={(e) => setVoxcpmTimesteps(e.target.value)}
              placeholder={t('audioWorkstation.optionalPlaceholder')}
            />
          </div>
        </div>

        <div className="flex items-center gap-4">
          <Button onClick={handleVoxCPMGenerate} loading={voxcpmGenerating}>
            {t('audioWorkstation.generate')}
          </Button>
          {voxcpmStatus && (
            <Badge variant={voxcpmStatus.status === 'healthy' ? 'success' : 'warning'}>
              VoxCPM: {voxcpmStatus.status}
            </Badge>
          )}
        </div>

        {voxcpmResult && (
          <div className="space-y-3">
            <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)]">
              <span className="text-sm text-[var(--color-text-secondary)]">{t('audioWorkstation.outputFileName')}:</span>
              <span className="ml-2 text-sm font-mono text-[var(--color-text-primary)]">{voxcpmResult.output_filename}</span>
            </div>
            <audio controls className="w-full" src={getVoiceWorkstationAudioUrl(voxcpmResult.audio_url)} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
