/**
 * Orpheus 合成 Tab（SubTask 7.4 · 音频工作站）
 *
 * 消费 voiceworkstationApi.getOrpheusStatus / synthesizeOrpheus / synthesizeOrpheusStream。
 * 支持内联情感标签快捷插入；流式/非流式切换；流式逐块接收裸 PCM 补 WAV 头播放。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Play, AudioLines } from 'lucide-react';
import { voiceworkstationApi, getVoiceWorkstationAudioUrl } from '@/api/clients/voiceworkstation';
import type { OrpheusStatus } from '@/api/clients/voiceworkstation';

const EMOTION_TAGS = ['<laugh>', '<giggle>', '<sigh>', '<cry>', '<whisper>', '<shout>', '<gasp>', '<groan>'];

export default function OrpheusPanel() {
  const { t } = useTranslation();
  const [text, setText] = useState('');
  const [voice, setVoice] = useState('');
  const [stream, setStream] = useState(false);
  const [synthesizing, setSynthesizing] = useState(false);
  const [receivedBytes, setReceivedBytes] = useState(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<OrpheusStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const loadStatus = useCallback(() => {
    voiceworkstationApi.getOrpheusStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const insertTag = (tag: string) => {
    const el = textRef.current;
    const start = el?.selectionStart ?? text.length;
    const end = el?.selectionEnd ?? text.length;
    const next = text.slice(0, start) + tag + text.slice(end);
    setText(next);
    requestAnimationFrame(() => {
      if (el) {
        el.focus();
        const pos = start + tag.length;
        el.setSelectionRange(pos, pos);
      }
    });
  };

  const handleSynthesize = async () => {
    if (!text.trim()) return;
    setSynthesizing(true);
    setFailed(false);
    setReceivedBytes(0);
    if (audioUrl?.startsWith('blob:')) URL.revokeObjectURL(audioUrl);
    setAudioUrl(null);
    try {
      const payload = { text, voice: voice.trim() || undefined };
      if (stream) {
        const blob = await voiceworkstationApi.synthesizeOrpheusStream(payload, (bytes) =>
          setReceivedBytes(bytes),
        );
        setAudioUrl(URL.createObjectURL(blob));
      } else {
        const res = await voiceworkstationApi.synthesizeOrpheus(payload);
        setAudioUrl(getVoiceWorkstationAudioUrl(res.audio_url));
      }
    } catch (error) {
      console.error('[OrpheusPanel] synthesize failed:', error);
      setFailed(true);
    } finally {
      setSynthesizing(false);
    }
  };

  const unhealthy = status?.status === 'unhealthy';

  return (
    <section className="glass-panel space-y-5 p-5">
      <div className="flex items-center gap-3">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <AudioLines className="h-4 w-4 text-primary" />
          {t('management.audioWorkstation.orpheusTitle')}
        </h4>
        {status && (
          <span className="text-xs text-muted-foreground">
            {t('management.audioWorkstation.orpheusStatus')}: {status.status}
          </span>
        )}
      </div>

      {unhealthy && (
        <p className="text-xs text-amber-400">{t('management.audioWorkstation.orpheusUnavailable')}</p>
      )}

      <textarea
        ref={textRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={5}
        placeholder={t('management.audioWorkstation.orpheusTextPlaceholder')}
        aria-label={t('management.audioWorkstation.orpheusText')}
        className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
      />

      <div>
        <label className="mb-2 block text-sm text-muted-foreground">
          {t('management.audioWorkstation.orpheusEmotionTags')}
        </label>
        <div className="flex flex-wrap gap-2">
          {EMOTION_TAGS.map((tag) => (
            <button
              key={tag}
              type="button"
              onClick={() => insertTag(tag)}
              className="rounded bg-[rgba(255,255,255,0.06)] px-2 py-1 font-mono text-xs text-muted-foreground transition-colors hover:text-primary"
            >
              {tag}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Field label={t('management.audioWorkstation.orpheusVoice')}>
          <input
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
            placeholder={t('management.audioWorkstation.orpheusVoicePlaceholder')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
        </Field>
        <div className="flex items-end gap-2 pb-1">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input
              type="checkbox"
              checked={stream}
              onChange={(e) => setStream(e.target.checked)}
              className="h-4 w-4 accent-primary"
            />
            {t('management.audioWorkstation.orpheusStream')}
          </label>
        </div>
      </div>
      <p className="text-xs text-muted-foreground/70">{t('management.audioWorkstation.orpheusStreamHelp')}</p>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void handleSynthesize()}
          disabled={synthesizing || !text.trim()}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
        >
          {synthesizing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {synthesizing
            ? stream
              ? t('management.audioWorkstation.orpheusStreaming')
              : t('management.audioWorkstation.orpheusSynthesizing')
            : t('management.audioWorkstation.orpheusSynthesize')}
        </button>
        {synthesizing && stream && receivedBytes > 0 && (
          <span className="text-xs text-muted-foreground">
            {t('management.audioWorkstation.orpheusReceived', { kb: Math.round(receivedBytes / 1024) })}
          </span>
        )}
      </div>

      {failed && <p className="text-xs text-red-400">{t('management.audioWorkstation.orpheusFailed')}</p>}

      {audioUrl && (
        <div className="space-y-2">
          <p className="text-sm text-muted-foreground">{t('management.audioWorkstation.orpheusPlay')}</p>
          <audio controls autoPlay className="w-full" src={audioUrl} />
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
