/**
 * 参考音频管理 Tab：基于 VoxCPM 的两模式参考音频生成（克隆 / 提示词）。
 *
 * - 克隆模式：参考音频路径 + 目标文本 + 风格指令（过渡文本），可选极致克隆
 * - 提示词模式：自然语言音色描述（映射到 sample_text），凭空设计新音色
 * pregenerate 为异步任务：提交后轮询 GET /api/ref-audio/status 展示进度与结果。
 * Spec: refactor-audiostation-engine-consolidation Task 9.4
 */
import { useState, useEffect, useRef } from 'react';
import { api } from '@/api/client';
import type { RefAudioMode, RefAudioStatus } from '@/api/client';
import { cn } from '@/lib/utils';
import { Button, Card, CardBody, Input, Textarea, Badge, Toggle } from '@/components/ui';
import { useTranslation } from 'react-i18next';

const modeOptions: { value: RefAudioMode; labelKey: string; descKey: string }[] = [
  { value: 'clone', labelKey: 'refModeClone', descKey: 'refModeCloneDesc' },
  { value: 'design', labelKey: 'refModeDesign', descKey: 'refModeDesignDesc' },
];

export function RefAudioPanel() {
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = () => {
    stopPolling();
    const tick = async () => {
      try {
        const s = await api.getRefAudioStatus();
        setRefStatus(s);
        if (!s.is_running) {
          stopPolling();
          setRunning(false);
        }
      } catch {
        // 查询失败静默，下一轮继续
      }
    };
    tick();
    pollRef.current = setInterval(tick, 2000);
  };

  // 挂载时拉取一次状态（恢复中断会话的运行态）
  useEffect(() => {
    api.getRefAudioStatus().then((s) => {
      setRefStatus(s);
      if (s.is_running) {
        setRunning(true);
        startPolling();
      }
    }).catch(() => {});
    return () => stopPolling();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    setRefStatus(null);
    try {
      await api.pregenerateRefs(buildRequest());
      startPolling();
    } catch (err) {
      setRunning(false);
      alert(err instanceof Error ? err.message : String(err));
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await api.exportEmotionRefsZip(buildRequest());
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'emotion_refs.zip';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImporting(true);
    try {
      const result = await api.importEmotionRefsZip(file);
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
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setImporting(false);
      e.target.value = '';
    }
  };

  const progress = refStatus?.progress;
  const result = refStatus?.result;

  return (
    <Card>
      <CardBody className="space-y-5">
        {/* 模式选择 */}
        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
            {t('audioWorkstation.refMode')}
          </label>
          <div className="flex gap-2">
            {modeOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setMode(opt.value)}
                className={cn(
                  'px-4 py-2 rounded-lg text-sm font-medium transition-colors border',
                  mode === opt.value
                    ? 'bg-[var(--color-accent)] text-white border-[var(--color-accent)]'
                    : 'bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] border-[var(--color-border)] hover:border-[var(--color-accent)]'
                )}
              >
                {t(`audioWorkstation.${opt.labelKey}`)}
              </button>
            ))}
          </div>
          <p className="text-xs text-[var(--color-text-tertiary)] mt-2">
            {t(`audioWorkstation.${modeOptions.find((o) => o.value === mode)?.descKey ?? 'refModeCloneDesc'}`)}
          </p>
        </div>

        {/* 克隆模式：参考音频路径 */}
        {mode === 'clone' && (
          <Input
            label={t('audioWorkstation.baseAudioPath')}
            value={baseAudioPath}
            onChange={(e) => setBaseAudioPath(e.target.value)}
            placeholder={t('audioWorkstation.baseAudioPathPlaceholder')}
          />
        )}

        {/* 提示词模式：音色描述；克隆模式：目标文本 */}
        <Textarea
          label={mode === 'design' ? t('audioWorkstation.refDesign') : t('audioWorkstation.sampleText')}
          value={sampleText}
          onChange={(e) => setSampleText(e.target.value)}
          placeholder={mode === 'design' ? t('audioWorkstation.refDesignPlaceholder') : t('audioWorkstation.sampleTextPlaceholder')}
          rows={3}
        />

        <Input
          label={t('audioWorkstation.transitionText')}
          value={transitionText}
          onChange={(e) => setTransitionText(e.target.value)}
          placeholder={t('audioWorkstation.transitionTextPlaceholder')}
        />

        {/* 极致克隆（仅克隆模式）*/}
        {mode === 'clone' && (
          <div className="space-y-1">
            <Toggle
              label={t('audioWorkstation.ultimateCloneToggle')}
              value={ultimateClone}
              onChange={setUltimateClone}
            />
            <p className="text-xs text-[var(--color-text-tertiary)] px-1">
              {t('audioWorkstation.ultimateCloneHelp')}
            </p>
          </div>
        )}

        {/* 操作 */}
        <div className="flex items-center gap-3 flex-wrap">
          <Button onClick={handleGenerate} loading={running} disabled={running || (mode === 'clone' && !baseAudioPath.trim())}>
            {t('audioWorkstation.generateRefs')}
          </Button>
          <Button variant="secondary" onClick={handleExport} loading={exporting} disabled={exporting}>
            {t('audioWorkstation.exportZip')}
          </Button>
          <Button
            variant="secondary"
            onClick={() => document.getElementById('ref-audio-import')?.click()}
            loading={importing}
            disabled={importing}
          >
            {t('audioWorkstation.importZip')}
          </Button>
          <input
            id="ref-audio-import"
            type="file"
            accept=".zip"
            className="hidden"
            onChange={handleImport}
          />
        </div>

        {/* 进度 */}
        {running && (
          <div className="p-3 rounded-lg bg-[var(--color-bg-tertiary)] space-y-2">
            <div className="flex items-center gap-2">
              <Badge variant="warning">{t('audioWorkstation.refRunning')}</Badge>
              {progress && progress.total > 0 && (
                <span className="text-xs text-[var(--color-text-tertiary)]">
                  {t('audioWorkstation.refProgress', { current: progress.current, total: progress.total })}
                </span>
              )}
            </div>
            {progress?.message && (
              <p className="text-sm text-[var(--color-text-secondary)]">{progress.message}</p>
            )}
            {progress && progress.total > 0 && (
              <div className="w-full bg-[var(--color-bg-primary)] rounded-full h-2">
                <div
                  className="bg-[var(--color-accent)] h-2 rounded-full transition-all"
                  style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
                />
              </div>
            )}
          </div>
        )}

        {/* 错误 */}
        {refStatus?.error && !running && (
          <div className="p-3 rounded-lg bg-red-500/10">
            <p className="text-sm text-red-500">{t('audioWorkstation.refErrorMessage')}: {refStatus.error}</p>
          </div>
        )}

        {/* 结果 */}
        {result && !running && (
          <div className="flex gap-4">
            <Badge variant="info">
              {t('audioWorkstation.emotionCount')}: {result.emotions}
            </Badge>
            <Badge variant="info">
              {t('audioWorkstation.transitionCount')}: {result.transitions}
            </Badge>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
