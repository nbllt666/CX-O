/**
 * 音频测试页（SubTask 7.4）
 *
 * 功能口径对齐 CX-O-Frontend AudioTestPage：
 * - ASR 语音识别：上传音频文件（audioApi.speechToText，multipart），展示识别文本；
 * - TTS 语音合成：输入文本（audioApi.textToSpeech，arraybuffer），ObjectURL 内嵌播放。
 *
 * 数据全部来自 audioApi 客户端（speechToText / textToSpeech），非占位页。
 * 浏览器/桌面模式均可运行；识别/合成失败展示错误态可重试。
 */
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AudioLines, Loader2, Mic, Play, Upload, Volume2 } from 'lucide-react';
import { audioApi } from '@/api/clients/audio';

/** ASR：上传音频 → 识别文本 */
function speechToText(file: File): Promise<{ text: string }> {
  return audioApi.speechToText(file);
}

/** TTS：文本 → 音频 Blob */
function synthesize(text: string): Promise<Blob> {
  return audioApi.textToSpeech(text);
}

export default function AudioTestPage() {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [asrResult, setAsrResult] = useState('');
  const [asrLoading, setAsrLoading] = useState(false);
  const [asrError, setAsrError] = useState(false);
  const [ttsText, setTtsText] = useState('');
  const [ttsAudio, setTtsAudio] = useState<string | null>(null);
  const [ttsLoading, setTtsLoading] = useState(false);
  const [ttsError, setTtsError] = useState(false);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    setAsrLoading(true);
    setAsrResult('');
    setAsrError(false);
    try {
      const result = await speechToText(file);
      setAsrResult(result.text || '');
    } catch (error) {
      console.error('[AudioTestPage] ASR failed:', error);
      setAsrError(true);
    } finally {
      setAsrLoading(false);
    }
  };

  const handleTTS = async () => {
    const text = ttsText.trim();
    if (!text) return;
    setTtsLoading(true);
    setTtsError(false);
    if (ttsAudio) URL.revokeObjectURL(ttsAudio);
    setTtsAudio(null);
    try {
      const blob = await synthesize(text);
      setTtsAudio(URL.createObjectURL(blob));
    } catch (error) {
      console.error('[AudioTestPage] TTS failed:', error);
      setTtsError(true);
    } finally {
      setTtsLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <p className="text-sm text-muted-foreground">{t('management.audioTest.subtitle')}</p>

      {/* ASR 语音识别 */}
      <section className="glass-panel space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Mic className="h-4 w-4 text-primary" />
          {t('management.audioTest.asrTitle')}
        </h3>
        <p className="text-xs text-muted-foreground">{t('management.audioTest.asrDesc')}</p>

        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          onChange={(e) => void handleFileUpload(e)}
          className="hidden"
        />

        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={asrLoading}
            className="flex items-center gap-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-4 py-2 text-sm font-medium transition-colors hover:bg-[rgba(255,255,255,0.1)] disabled:opacity-50"
          >
            <Upload className="h-4 w-4" />
            {t('management.audioTest.asrUpload')}
          </button>
          {asrLoading && (
            <span className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('management.audioTest.asrRecognizing')}
            </span>
          )}
        </div>

        {asrError && (
          <p className="text-xs text-red-400">{t('management.audioTest.asrFailed')}</p>
        )}

        {asrResult && (
          <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4">
            <p className="mb-1 text-xs font-medium text-muted-foreground">
              {t('management.audioTest.asrResult')}
            </p>
            <p className="text-sm">{asrResult}</p>
          </div>
        )}
      </section>

      {/* TTS 语音合成 */}
      <section className="glass-panel space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Volume2 className="h-4 w-4 text-secondary" />
          {t('management.audioTest.ttsTitle')}
        </h3>
        <p className="text-xs text-muted-foreground">{t('management.audioTest.ttsDesc')}</p>

        <textarea
          value={ttsText}
          onChange={(e) => setTtsText(e.target.value)}
          placeholder={t('management.audioTest.ttsPlaceholder')}
          rows={4}
          aria-label={t('management.audioTest.ttsTitle')}
          className="w-full resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />

        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => void handleTTS()}
            disabled={ttsLoading || !ttsText.trim()}
            className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            {t('management.audioTest.ttsSynthesize')}
          </button>
          {ttsLoading && (
            <span className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('management.audioTest.ttsSynthesizing')}
            </span>
          )}
        </div>

        {ttsError && <p className="text-xs text-red-400">{t('management.audioTest.ttsFailed')}</p>}

        {ttsAudio && (
          <div className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4">
            <p className="mb-3 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <AudioLines className="h-3.5 w-3.5" />
              {t('management.audioTest.ttsResult')}
            </p>
            <audio src={ttsAudio} controls className="w-full" style={{ height: 40 }} />
            <p className="mt-2 text-xs text-muted-foreground/70">
              {t('management.audioTest.ttsPlayHint')}
            </p>
          </div>
        )}
      </section>

      {/* 使用说明 */}
      <section className="glass-panel p-5">
        <h3 className="mb-3 text-sm font-semibold">{t('management.audioTest.usageTitle')}</h3>
        <ul className="space-y-1.5 text-xs text-muted-foreground">
          <li>{t('management.audioTest.usageAsr')}</li>
          <li>{t('management.audioTest.usageTts')}</li>
          <li>{t('management.audioTest.usageFormats')}</li>
          <li>{t('management.audioTest.usageEngine')}</li>
        </ul>
      </section>
    </div>
  );
}
