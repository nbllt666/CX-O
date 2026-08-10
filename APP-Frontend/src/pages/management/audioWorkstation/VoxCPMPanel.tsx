/**
 * VoxCPM 生成 Tab（SubTask 7.4 · 音频工作站）
 *
 * 消费 voiceworkstationApi.generateVoxCPM / getVoxCPMStatus。
 * 三种模式：声音设计 / 可控克隆 / 极致克隆；生成结果内嵌播放。
 */
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Sparkles } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type { VoxCPMMode, VoiceWsAudioResult, VoxCPMStatus } from '@/api/clients/voiceworkstation';

const MODES: VoxCPMMode[] = ['design', 'controllable_clone', 'ultimate_clone'];

export default function VoxCPMPanel() {
  const { t } = useTranslation();
  const [mode, setMode] = useState<VoxCPMMode>('design');
  const [text, setText] = useState('');
  const [control, setControl] = useState('');
  const [refAudioPath, setRefAudioPath] = useState('');
  const [promptAudioPath, setPromptAudioPath] = useState('');
  const [promptText, setPromptText] = useState('');
  const [cfg, setCfg] = useState('');
  const [steps, setSteps] = useState('');
  const [status, setStatus] = useState<VoxCPMStatus | null>(null);
  const [result, setResult] = useState<VoiceWsAudioResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const loadStatus = useCallback(() => {
    voiceworkstationApi
      .getVoxCPMStatus()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleGenerate = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setFailed(false);
    setResult(null);
    try {
      const cfgNum = Number.parseFloat(cfg);
      const stepsNum = Number.parseInt(steps, 10);
      const res = await voiceworkstationApi.generateVoxCPM({
        mode,
        text,
        control: mode !== 'ultimate_clone' ? control || undefined : undefined,
        reference_audio_path: mode === 'controllable_clone' ? refAudioPath || undefined : undefined,
        prompt_audio_path: mode === 'ultimate_clone' ? promptAudioPath || undefined : undefined,
        prompt_text: mode === 'ultimate_clone' ? promptText || undefined : undefined,
        cfg_value: Number.isFinite(cfgNum) ? cfgNum : undefined,
        inference_timesteps: Number.isFinite(stepsNum) ? stepsNum : undefined,
      });
      setResult(res);
    } catch (error) {
      console.error('[VoxCPMPanel] generate failed:', error);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="glass-panel space-y-5 p-5">
      <div>
        <label className="mb-2 block text-sm text-muted-foreground">
          {t('management.audioWorkstation.voxcpmMode')}
        </label>
        <div className="flex flex-wrap gap-2">
          {MODES.map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
              style={
                mode === m
                  ? { background: 'var(--color-primary, #e879b8)', color: '#fff' }
                  : undefined
              }
            >
              {t(`management.audioWorkstation.voxcpmMode_${m}`)}
            </button>
          ))}
        </div>
      </div>

      <Field label={t('management.audioWorkstation.voxcpmText')}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder={t('management.audioWorkstation.voxcpmTextPlaceholder')}
          className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
      </Field>

      {mode !== 'ultimate_clone' && (
        <Field label={t('management.audioWorkstation.voxcpmControl')}>
          <input
            value={control}
            onChange={(e) => setControl(e.target.value)}
            placeholder={t('management.audioWorkstation.voxcpmControlPlaceholder')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </Field>
      )}

      {mode === 'controllable_clone' && (
        <Field label={t('management.audioWorkstation.voxcpmRefAudioPath')}>
          <input
            value={refAudioPath}
            onChange={(e) => setRefAudioPath(e.target.value)}
            placeholder={t('management.audioWorkstation.voxcpmRefAudioPathPlaceholder')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </Field>
      )}

      {mode === 'ultimate_clone' && (
        <>
          <Field label={t('management.audioWorkstation.voxcpmPromptAudioPath')}>
            <input
              value={promptAudioPath}
              onChange={(e) => setPromptAudioPath(e.target.value)}
              placeholder={t('management.audioWorkstation.voxcpmPromptAudioPathPlaceholder')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </Field>
          <Field label={t('management.audioWorkstation.voxcpmPromptText')}>
            <input
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              placeholder={t('management.audioWorkstation.voxcpmPromptTextPlaceholder')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
          </Field>
        </>
      )}

      <div className="grid grid-cols-2 gap-4">
        <Field label={t('management.audioWorkstation.voxcpmCfg')}>
          <input
            type="number"
            step="0.1"
            value={cfg}
            onChange={(e) => setCfg(e.target.value)}
            placeholder={t('management.audioWorkstation.voxcpmOptional')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </Field>
        <Field label={t('management.audioWorkstation.voxcpmSteps')}>
          <input
            type="number"
            value={steps}
            onChange={(e) => setSteps(e.target.value)}
            placeholder={t('management.audioWorkstation.voxcpmOptional')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </Field>
      </div>

      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => void handleGenerate()}
          disabled={loading || !text.trim()}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {loading ? t('management.audioWorkstation.voxcpmGenerating') : t('management.audioWorkstation.voxcpmGenerate')}
        </button>
        {status && (
          <span className="text-xs text-muted-foreground">
            {t('management.audioWorkstation.voxcpmStatus')}: {status.status}
          </span>
        )}
      </div>

      {failed && <p className="text-xs text-red-400">{t('management.audioWorkstation.voxcpmGenerateFailed')}</p>}

      {result && (
        <div className="space-y-3">
          <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2 text-sm">
            <span className="text-muted-foreground">{t('management.audioWorkstation.voxcpmOutput')}:</span>{' '}
            <span className="font-mono text-xs">{result.output_filename}</span>
          </div>
          <audio controls className="w-full" src={getVoiceWorkstationAudioUrl(result.audio_url)} />
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
