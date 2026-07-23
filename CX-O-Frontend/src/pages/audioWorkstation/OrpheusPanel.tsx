/**
 * Orpheus 合成 Tab：情感语音合成（直调 docker vLLM）。
 *
 * - 文本输入：支持内联 <laugh>/<giggle> 等情感标签（原样透传）
 * - voice 选择、情感标签快捷插入
 * - 流式 / 非流式切换：流式逐块接收裸 PCM 并补 WAV 头播放
 * - 合成结果内嵌播放
 * Spec: refactor-audiostation-engine-consolidation Task 9.3
 */
import { useState, useEffect, useRef } from 'react';
import { api, getVoiceWorkstationAudioUrl } from '@/api/client';
import type { OrpheusStatus } from '@/api/client';
import { Button, Card, CardBody, Input, Textarea, Badge, Toggle } from '@/components/ui';
import { useTranslation } from 'react-i18next';

const EMOTION_TAGS = ['<laugh>', '<giggle>', '<sigh>', '<cry>', '<whisper>', '<shout>', '<gasp>', '<groan>'];

export function OrpheusPanel() {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [voice, setVoice] = useState('');
  const [stream, setStream] = useState(false);
  const [synthesizing, setSynthesizing] = useState(false);
  const [receivedBytes, setReceivedBytes] = useState(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<OrpheusStatus | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    api.getOrpheusStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  const insertTag = (tag: string) => {
    const el = textRef.current;
    if (!el) {
      setText((prev) => prev + tag);
      return;
    }
    const start = el.selectionStart ?? text.length;
    const end = el.selectionEnd ?? text.length;
    const next = text.slice(0, start) + tag + text.slice(end);
    setText(next);
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + tag.length;
      el.setSelectionRange(pos, pos);
    });
  };

  const handleSynthesize = async () => {
    if (!text.trim()) return;
    setSynthesizing(true);
    setReceivedBytes(0);
    // 释放上一次的 object URL
    if (audioUrl && audioUrl.startsWith('blob:')) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    try {
      if (stream) {
        const blob = await api.synthesizeOrpheusStream(
          { text, voice: voice.trim() || undefined },
          (bytes) => setReceivedBytes(bytes),
        );
        setAudioUrl(URL.createObjectURL(blob));
      } else {
        const result = await api.synthesizeOrpheus({ text, voice: voice.trim() || undefined });
        setAudioUrl(getVoiceWorkstationAudioUrl(result.audio_url));
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : String(err));
    } finally {
      setSynthesizing(false);
    }
  };

  const unavailable = status?.status === 'unhealthy';

  return (
    <Card>
      <CardBody className="space-y-5">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium text-[var(--color-text-primary)]">
            {t('audioWorkstation.orpheusTitle')}
          </h3>
          {status && (
            <Badge variant={status.status === 'healthy' ? 'success' : 'warning'}>
              {t('audioWorkstation.orpheusStatus')}: {status.status}
            </Badge>
          )}
        </div>

        {unavailable && (
          <p className="text-sm text-amber-500">{t('audioWorkstation.orpheusUnavailable')}</p>
        )}

        <Textarea
          ref={textRef}
          label={t('audioWorkstation.orpheusText')}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('audioWorkstation.orpheusTextPlaceholder')}
          rows={5}
        />

        <div>
          <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">
            {t('audioWorkstation.orpheusEmotionTags')}
          </label>
          <div className="flex flex-wrap gap-2">
            {EMOTION_TAGS.map((tag) => (
              <button
                key={tag}
                onClick={() => insertTag(tag)}
                className="px-2.5 py-1 rounded-md text-xs font-mono bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)] border border-[var(--color-border)] hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] transition-colors"
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        <Input
          label={t('audioWorkstation.orpheusVoice')}
          value={voice}
          onChange={(e) => setVoice(e.target.value)}
          placeholder={t('audioWorkstation.orpheusVoicePlaceholder')}
        />

        <div className="space-y-1">
          <Toggle
            label={t('audioWorkstation.orpheusStream')}
            value={stream}
            onChange={setStream}
          />
          <p className="text-xs text-[var(--color-text-tertiary)] px-1">{t('audioWorkstation.orpheusStreamHelp')}</p>
        </div>

        <div className="flex items-center gap-3">
          <Button onClick={handleSynthesize} loading={synthesizing} disabled={synthesizing || !text.trim()}>
            {t('audioWorkstation.orpheusSynthesize')}
          </Button>
          {synthesizing && stream && receivedBytes > 0 && (
            <Badge variant="info">
              {t('audioWorkstation.orpheusReceived', { kb: Math.round(receivedBytes / 1024) })}
            </Badge>
          )}
        </div>

        {synthesizing && (
          <p className="text-sm text-[var(--color-text-secondary)]">
            {stream ? t('audioWorkstation.orpheusStreaming') : t('audioWorkstation.orpheusSynthesizing')}
          </p>
        )}

        {audioUrl && (
          <div className="space-y-2">
            <span className="text-sm text-[var(--color-text-secondary)]">{t('audioWorkstation.orpheusPlay')}</span>
            <audio controls autoPlay className="w-full" src={audioUrl} />
          </div>
        )}
      </CardBody>
    </Card>
  );
}
