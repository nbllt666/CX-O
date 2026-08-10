/**
 * 参考音频管理 Tab（SubTask 7.4 · 音频工作站）
 *
 * 消费 voiceworkstationApi.pregenerateRefs / getRefAudioStatus（轮询）/
 * exportEmotionRefsZip / importEmotionRefsZip。
 * 克隆/提示词两模式；pre 生成是异步任务，提交后轮询展示进度与结果。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Loader2, Upload, Wand2 } from 'lucide-react';
import { voiceworkstationApi } from '@/api/clients/voiceworkstation';
import type { RefAudioMode, RefAudioStatus } from '@/api/clients/voiceworkstation';

const MODES: { value: RefAudioMode; labelKey: string; descKey: string }[] = [
  { value: 'clone', labelKey: 'refModeClone', descKey: 'refModeCloneDesc' },
  { value: 'design', labelKey: 'refModeDesign', descKey: 'refModeDesignDesc' },
];

export default function RefAudioPanel() {
  const { t } = useTranslation();
  const [mode, setMode] = useState<RefAudioMode>('clone');
  const [baseAudioPath, setBaseAudioPath] = useState('');
  const [sampleText, setSampleText] = useState('');
  const [transitionText, setTransitionText] = useState('');
  const [ultimateClone, setUltimateClone] = useState(false);
  const [running, setRunning] = useState(false);
  const [refStatus, setRefStatus] = useState<RefAudioStatus | null>(null);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [failed, setFailed] = useState(false);
  const [actionFailed, setActionFailed] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    const tick = async () => {
      try {
        const s = await voiceworkstationApi.getRefAudioStatus();
        setRefStatus(s);
        if (!s.is_running) {
          stopPolling();
          setRunning(false);
        }
      } catch {
        // 查询失败静默，下一轮继续
      }
    };
    void tick();
    pollRef.current = setInterval(tick, 2000);
  }, [stopPolling]);

  useEffect(() => {
    voiceworkstationApi
      .getRefAudioStatus()
      .then((s) => {
        setRefStatus(s);
        if (s.is_running) {
          setRunning(true);
          startPolling();
        }
      })
      .catch(() => setRefStatus(null));
    return () => stopPolling();
  }, [startPolling, stopPolling]);

  const buildRequest = () => ({
    base_audio_path: mode === 'clone' ? baseAudioPath : '',
    sample_text: sampleText || undefined,
    transition_text: transitionText || undefined,
    mode,
    ultimate_clone: mode === 'clone' ? ultimateClone : undefined,
  });

  const handleGenerate = async () => {
    if (mode === 'clone' && !baseAudioPath.trim()) return;
    setRunning(true);
    setFailed(false);
    setRefStatus(null);
    try {
      await voiceworkstationApi.pregenerateRefs(buildRequest());
      startPolling();
    } catch (error) {
      console.error('[RefAudioPanel] pregenerate failed:', error);
      setRunning(false);
      setFailed(true);
    }
  };

  const handleExport = async () => {
    setExporting(true);
    setActionFailed(false);
    try {
      const blob = await voiceworkstationApi.exportEmotionRefsZip(buildRequest());
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'emotion_refs.zip';
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('[RefAudioPanel] export failed:', error);
      setActionFailed(true);
    } finally {
      setExporting(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setImporting(true);
    setActionFailed(false);
    try {
      const result = await voiceworkstationApi.importEmotionRefsZip(file);
      setRefStatus({
        is_running: false,
        progress: null,
        result: {
          emotions: result.meta.emotions.length,
          transitions: result.meta.transitions.length,
          total: result.meta.emotions.length + result.meta.transitions.length,
          skipped: false,
        },
        error: null,
      });
    } catch (error) {
      console.error('[RefAudioPanel] import failed:', error);
      setActionFailed(true);
    } finally {
      setImporting(false);
    }
  };

  const progress = refStatus?.progress;
  const result = refStatus?.result;
  const activeDesc = MODES.find((m) => m.value === mode)?.descKey ?? 'refModeCloneDesc';

  return (
    <section className="glass-panel space-y-5 p-5">
      {/* 模式选择 */}
      <div>
        <label className="mb-2 block text-sm text-muted-foreground">
          {t('management.audioWorkstation.refMode')}
        </label>
        <div className="flex flex-wrap gap-2">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => setMode(m.value)}
              className="rounded-lg px-3 py-1.5 text-xs font-medium transition-colors"
              style={mode === m.value ? { background: 'var(--color-primary, #e879b8)', color: '#fff' } : undefined}
            >
              {t(`management.audioWorkstation.${m.labelKey}`)}
            </button>
          ))}
        </div>
        <p className="mt-1.5 text-xs text-muted-foreground/70">
          {t(`management.audioWorkstation.${activeDesc}`)}
        </p>
      </div>

      {mode === 'clone' && (
        <Field label={t('management.audioWorkstation.refBaseAudioPath')}>
          <input
            value={baseAudioPath}
            onChange={(e) => setBaseAudioPath(e.target.value)}
            placeholder={t('management.audioWorkstation.refBaseAudioPathPlaceholder')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </Field>
      )}

      <Field label={mode === 'design' ? t('management.audioWorkstation.refDesign') : t('management.audioWorkstation.refSampleText')}>
        <textarea
          value={sampleText}
          onChange={(e) => setSampleText(e.target.value)}
          rows={3}
          placeholder={mode === 'design' ? t('management.audioWorkstation.refDesignPlaceholder') : t('management.audioWorkstation.refSampleTextPlaceholder')}
          className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
      </Field>

      <Field label={t('management.audioWorkstation.refTransitionText')}>
        <input
          value={transitionText}
          onChange={(e) => setTransitionText(e.target.value)}
          placeholder={t('management.audioWorkstation.refTransitionTextPlaceholder')}
          className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
      </Field>

      {mode === 'clone' && (
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={ultimateClone}
            onChange={(e) => setUltimateClone(e.target.checked)}
            className="h-4 w-4 accent-primary"
          />
          {t('management.audioWorkstation.refUltimateClone')}
        </label>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void handleGenerate()}
          disabled={running || (mode === 'clone' && !baseAudioPath.trim())}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
          {running ? t('management.audioWorkstation.refRunning') : t('management.audioWorkstation.refGenerate')}
        </button>
        <button
          type="button"
          onClick={() => void handleExport()}
          disabled={exporting}
          className="flex items-center gap-2 rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          {t('management.audioWorkstation.refExport')}
        </button>
        <button
          type="button"
          onClick={() => document.getElementById('ref-audio-import')?.click()}
          disabled={importing}
          className="flex items-center gap-2 rounded-lg border border-[var(--glass-border)] px-4 py-2 text-sm text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-50"
        >
          <Upload className="h-4 w-4" />
          {t('management.audioWorkstation.refImport')}
        </button>
        <input
          id="ref-audio-import"
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => void handleImport(e)}
        />
      </div>

      {failed && <p className="text-xs text-red-400">{t('management.audioWorkstation.refGenerateFailed')}</p>}
      {actionFailed && <p className="text-xs text-red-400">{t('management.audioWorkstation.refActionFailed')}</p>}

      {/* 进度 */}
      {running && (
        <div className="space-y-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{t('management.audioWorkstation.refRunning')}</span>
            {progress && progress.total > 0 && (
              <span>
                {t('management.audioWorkstation.refProgress', { current: progress.current, total: progress.total })}
              </span>
            )}
          </div>
          {progress?.message && <p className="text-sm text-muted-foreground">{progress.message}</p>}
          {progress && progress.total > 0 && (
            <div className="h-2 overflow-hidden rounded-full bg-[rgba(255,255,255,0.08)]">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
              />
            </div>
          )}
        </div>
      )}

      {result && !running && (
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>
            {t('management.audioWorkstation.refEmotionCount')}: {result.emotions}
          </span>
          <span>
            {t('management.audioWorkstation.refTransitionCount')}: {result.transitions}
          </span>
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
