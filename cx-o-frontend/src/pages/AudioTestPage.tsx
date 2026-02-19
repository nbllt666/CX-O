import { useState, useRef } from 'react';
import { api } from '../api/client';
import { PageHeader } from '../components/layout';
import { Button, Card, CardBody } from '../components/ui';

export function AudioTestPage() {
  const [asrResult, setAsrResult] = useState('');
  const [ttsText, setTtsText] = useState('');
  const [ttsAudio, setTtsAudio] = useState<string | null>(null);
  const [asrLoading, setAsrLoading] = useState(false);
  const [ttsLoading, setTtsLoading] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setAsrLoading(true);
    setAsrResult('');

    try {
      const result = await api.speechToText(file);
      setAsrResult(result.text || '');
    } catch (error) {
      console.error('ASR 识别失败:', error);
      alert('语音识别失败，请重试');
    } finally {
      setAsrLoading(false);
    }

    e.target.value = '';
  };

  const handleTTS = async () => {
    if (!ttsText.trim()) return;

    setTtsLoading(true);
    setTtsAudio(null);

    try {
      const audioBlob = await api.textToSpeech(ttsText);
      const url = URL.createObjectURL(audioBlob);
      setTtsAudio(url);
    } catch (error) {
      console.error('TTS 合成失败:', error);
      alert('语音合成失败，请重试');
    } finally {
      setTtsLoading(false);
    }
  };

  const playAudio = () => {
    if (audioRef.current && ttsAudio) {
      audioRef.current.play();
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      <PageHeader
        title="音频测试"
        description="测试语音识别 (ASR) 和语音合成 (TTS) 功能"
      />

      <div className="space-y-6">
        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <svg className="w-5 h-5 text-[var(--color-accent)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
              ASR 语音识别
            </h3>
            <p className="text-sm text-[var(--color-text-secondary)] mb-4">
              上传音频文件进行语音识别，支持 mp3、wav、webm 等格式
            </p>

            <input
              ref={fileInputRef}
              type="file"
              accept="audio/*"
              onChange={handleFileUpload}
              className="hidden"
            />

            <div className="flex items-center gap-4">
              <Button
                variant="secondary"
                onClick={() => fileInputRef.current?.click()}
                disabled={asrLoading}
              >
                <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                上传音频文件
              </Button>
              {asrLoading && (
                <div className="flex items-center gap-2 text-[var(--color-text-secondary)]">
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-[var(--color-accent)] border-t-transparent" />
                  <span>识别中...</span>
                </div>
              )}
            </div>

            {asrResult && (
              <div className="mt-4 p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
                <p className="text-sm font-medium text-[var(--color-text-secondary)] mb-2">识别结果：</p>
                <p className="text-[var(--color-text-primary)]">{asrResult}</p>
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
              <svg className="w-5 h-5 text-[var(--color-accent)]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
              </svg>
              TTS 语音合成
            </h3>
            <p className="text-sm text-[var(--color-text-secondary)] mb-4">
              输入文本进行语音合成
            </p>

            <div className="space-y-4">
              <textarea
                value={ttsText}
                onChange={(e) => setTtsText(e.target.value)}
                placeholder="输入要合成的文本..."
                className="w-full px-4 py-3 bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-[var(--radius-lg)] resize-none focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/50"
                rows={4}
              />

              <div className="flex items-center gap-4">
                <Button onClick={handleTTS} disabled={ttsLoading || !ttsText.trim()}>
                  <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  合成语音
                </Button>
                {ttsLoading && (
                  <div className="flex items-center gap-2 text-[var(--color-text-secondary)]">
                    <div className="animate-spin rounded-full h-4 w-4 border-2 border-[var(--color-accent)] border-t-transparent" />
                    <span>合成中...</span>
                  </div>
                )}
              </div>

              {ttsAudio && (
                <div className="mt-4 p-4 bg-[var(--color-bg-tertiary)] rounded-[var(--radius-lg)]">
                  <p className="text-sm font-medium text-[var(--color-text-secondary)] mb-3">合成结果：</p>
                  <div className="flex items-center gap-4">
                    <Button variant="secondary" onClick={playAudio}>
                      <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      播放
                    </Button>
                    <audio ref={audioRef} src={ttsAudio} className="flex-1" controls />
                  </div>
                </div>
              )}
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardBody>
            <h3 className="text-lg font-semibold mb-4">使用说明</h3>
            <div className="space-y-2 text-sm text-[var(--color-text-secondary)]">
              <p>• <strong>ASR 语音识别</strong>：上传音频文件，系统将自动识别并转换为文本</p>
              <p>• <strong>TTS 语音合成</strong>：输入文本，系统将合成语音并播放</p>
              <p>• 支持的音频格式：mp3、wav、webm、ogg 等</p>
              <p>• 语音合成使用 F5-TTS 模型，需要确保 TTS 服务已启动</p>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
