/**
 * 音频面板页（SubTask 7.4）
 *
 * 功能口径对齐 CX-O-Frontend live/AudioPanel：
 * - Live WebSocket 状态行（连接态 / 客户端计数 / TTS 同步状态）
 * - 麦克风输入：启停、设备选择、实时音量电平、增益（增益持久化 audioStore.micGain）
 * - 音频输出：TTS 音量（持久化 audioStore.ttsVolume）、本地监听音量
 * - 回声消除（AEC）：开关 + 模式（自动/浏览器原生/AudioWorklet/手动）+ 状态指示
 * - TTS 播放指示（Live WS tts_sync / tts_end 事件驱动）
 *
 * 采集链路：getUserMedia → AudioContext(16kHz) → Gain(micGain) → Analyser(电平) →
 *   ScriptProcessor(4096) → encodePcm16 → Live WS 二进制上行（与 useMicAsrUplink 同协议）。
 *
 * 与参考前端的差异说明：
 * - 本地监听（麦克风→扬声器）默认静音（outputVolume=0），防止回授啸叫；
 * - AudioWorklet AEC 与参考一致仅做能力探测标记，不加载实际 worklet 处理模块。
 * - 麦克风启停为本页会话级状态（不写 audioStore.micEnabled，避免与桌宠窗上行开关串扰）。
 *
 * 优雅降级：mediaDevices 不可用时显示错误横幅，页面其余功能可用。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Cpu,
  Loader2,
  Mic,
  MicOff,
  Volume2,
  Waves,
} from 'lucide-react';
import { useLiveWebSocket } from '@/hooks/useLiveWebSocket';
import type { TTSSyncData } from '@/hooks/useLiveWebSocket';
import { useAudioPipeline } from '@/hooks/audio/pipeline';
import { encodePcm16 } from '@/hooks/audio/pcm';
import { useAudioStore } from '@/store/audioStore';
import { audioApi } from '@/api/clients/audio';
import { cn } from '@/lib/utils';

interface AudioDeviceInfo {
  deviceId: string;
  label: string;
}

type AecMode = 'auto' | 'browser' | 'worklet' | 'manual';
type AecStatus = 'active' | 'manual' | 'unavailable';
type MicError = 'media-unavailable' | 'mic-start-failed' | null;

/** 电平 RAF 回写间隔：约 12Hz，兼顾平滑与渲染压力 */
const LEVEL_FLUSH_MS = 80;
const SCRIPT_BUFFER_SIZE = 4096;
const LEVEL_NORMALIZATION = 100;

export default function AudioPanelPage() {
  const { t } = useTranslation();
  const micGain = useAudioStore((s) => s.micGain);
  const setMicGain = useAudioStore((s) => s.setMicGain);
  const ttsVolume = useAudioStore((s) => s.ttsVolume);
  const setTtsVolume = useAudioStore((s) => s.setTtsVolume);

  const [devices, setDevices] = useState<AudioDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [micOn, setMicOn] = useState(false);
  const [level, setLevel] = useState(0);
  const [outputVolume, setOutputVolume] = useState(0);
  const [aecEnabled, setAecEnabled] = useState(true);
  const [aecMode, setAecMode] = useState<AecMode>('auto');
  const [aecStatus, setAecStatus] = useState<AecStatus>('unavailable');
  const [syncStatus, setSyncStatus] = useState('');
  const [playbackText, setPlaybackText] = useState('');
  const [micError, setMicError] = useState<MicError>(null);
  const [audioConfig, setAudioConfig] = useState<Record<string, unknown> | null>(null);

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const micGainNodeRef = useRef<GainNode | null>(null);
  const monitorGainNodeRef = useRef<GainNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const rafRef = useRef(0);
  const lastFlushRef = useRef(0);

  const micGainRef = useRef(micGain);
  micGainRef.current = micGain;
  const selectedDeviceRef = useRef(selectedDeviceId);
  selectedDeviceRef.current = selectedDeviceId;

  // ── Live WebSocket：TTS 同步事件 + 连接态 ──
  const handleTTSSync = useCallback((data: TTSSyncData) => {
    setPlaybackText(data.text);
    setSyncStatus('playing');
  }, []);
  const handleTTSEnd = useCallback(() => {
    setPlaybackText('');
    setSyncStatus('ready');
  }, []);

  const { isConnected, sendAudio } = useLiveWebSocket({
    onTTSSync: handleTTSSync,
    onTTSEnd: handleTTSEnd,
  });
  const sendAudioRef = useRef(sendAudio);
  sendAudioRef.current = sendAudio;

  const {
    analyserRef,
    init: initPipeline,
    close: closePipeline,
    createStreamSource,
    createScriptProcessor,
    createStreamDestination,
  } = useAudioPipeline({ audioContextOptions: { sampleRate: 16000 }, fftSize: 256 });

  // ── 设备枚举（需先取一次流以获得设备标签）──
  const enumerateDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const all = await navigator.mediaDevices.enumerateDevices();
      stream.getTracks().forEach((track) => track.stop());
      const inputs = all
        .filter((d) => d.kind === 'audioinput')
        .map((d, idx) => ({
          deviceId: d.deviceId,
          label: d.label || `Microphone ${idx + 1}`,
        }));
      setDevices(inputs);
      if (inputs.length > 0 && !selectedDeviceRef.current) {
        setSelectedDeviceId(inputs[0].deviceId);
      }
    } catch (error) {
      console.error('[AudioPanelPage] enumerate devices failed:', error);
    }
  }, []);

  useEffect(() => {
    void enumerateDevices();
  }, [enumerateDevices]);

  // ── 音频配置（audioApi.getAudioConfig）：只读展示，后端不可达时静默降级 ──
  useEffect(() => {
    audioApi
      .getAudioConfig()
      .then((cfg) => setAudioConfig(cfg && typeof cfg === 'object' ? cfg : null))
      .catch(() => setAudioConfig(null));
  }, []);

  // ── AEC 模式解析：auto 依次尝试 browser → worklet → manual ──
  const resolveAecMode = useCallback(async (): Promise<'browser' | 'worklet' | 'manual'> => {
    if (!aecEnabled) return 'manual';

    if ((aecMode === 'auto' || aecMode === 'browser') && navigator.mediaDevices?.getUserMedia) {
      let testStream: MediaStream | null = null;
      try {
        testStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        const track = testStream.getAudioTracks()[0];
        if (track?.getSettings().echoCancellation) {
          return 'browser';
        }
      } catch {
        // 浏览器 AEC 不可用，继续尝试下一模式
      } finally {
        testStream?.getTracks().forEach((track) => track.stop());
      }
    }

    if ((aecMode === 'auto' || aecMode === 'worklet') && typeof AudioWorkletNode !== 'undefined') {
      return 'worklet';
    }

    return 'manual';
  }, [aecEnabled, aecMode]);

  const stopLevelLoop = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    }
    setLevel(0);
  }, []);

  const startLevelLoop = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    const tick = (now: number) => {
      const a = analyserRef.current;
      if (!a) return;
      a.getByteFrequencyData(dataArray);
      if (now - lastFlushRef.current >= LEVEL_FLUSH_MS) {
        lastFlushRef.current = now;
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        setLevel(Math.min(sum / dataArray.length / LEVEL_NORMALIZATION, 1));
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [analyserRef]);

  const stopMic = useCallback(() => {
    stopLevelLoop();
    if (processorRef.current) {
      processorRef.current.onaudioprocess = null;
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    micGainNodeRef.current = null;
    monitorGainNodeRef.current = null;
    closePipeline();
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    setMicOn(false);
    setAecStatus('unavailable');
  }, [closePipeline, stopLevelLoop]);

  const startMic = useCallback(async () => {
    setMicError(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setMicError('media-unavailable');
      return;
    }
    try {
      const resolvedAec = await resolveAecMode();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          deviceId: selectedDeviceRef.current ? { exact: selectedDeviceRef.current } : undefined,
          echoCancellation: resolvedAec === 'browser',
          noiseSuppression: resolvedAec === 'browser',
          autoGainControl: resolvedAec === 'browser',
        },
      });
      mediaStreamRef.current = stream;

      initPipeline();
      const source = createStreamSource(stream);
      const processor = createScriptProcessor(SCRIPT_BUFFER_SIZE, 1, 1);
      const uplinkDestination = createStreamDestination();
      const analyser = analyserRef.current;
      const ctx = source?.context;
      if (!source || !processor || !uplinkDestination || !analyser || !ctx) {
        throw new Error('audio pipeline init failed');
      }

      // 麦克风增益节点（audioStore.micGain 实时生效）
      const gainNode = ctx.createGain();
      gainNode.gain.value = micGainRef.current;
      micGainNodeRef.current = gainNode;

      // 本地监听节点（默认静音，防止回授）
      const monitorGain = ctx.createGain();
      monitorGain.gain.value = 0;
      monitorGainNodeRef.current = monitorGain;

      processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        const pcm = encodePcm16(input, micGainRef.current);
        sendAudioRef.current(pcm.buffer as ArrayBuffer);
      };

      source.connect(gainNode);
      gainNode.connect(analyser);
      analyser.connect(processor);
      processor.connect(uplinkDestination);
      // 本地监听旁路：analyser → monitorGain → 扬声器
      analyser.connect(monitorGain);
      monitorGain.connect(ctx.destination);

      if (ctx.state === 'suspended' && typeof AudioContext !== 'undefined' && ctx instanceof AudioContext) {
        void ctx.resume();
      }

      sourceRef.current = source;
      processorRef.current = processor;
      setAecStatus(resolvedAec === 'manual' ? 'manual' : 'active');
      startLevelLoop();
      setMicOn(true);
    } catch (error) {
      console.error('[AudioPanelPage] mic start failed:', error);
      stopMic();
      setMicError('mic-start-failed');
    }
  }, [
    resolveAecMode,
    initPipeline,
    createStreamSource,
    createScriptProcessor,
    createStreamDestination,
    analyserRef,
    startLevelLoop,
    stopMic,
  ]);

  // 卸载兜底清理
  useEffect(() => {
    return () => stopMic();
  }, [stopMic]);

  // 增益/监听音量实时生效
  useEffect(() => {
    if (micGainNodeRef.current) micGainNodeRef.current.gain.value = micGain;
  }, [micGain]);
  useEffect(() => {
    if (monitorGainNodeRef.current) monitorGainNodeRef.current.gain.value = outputVolume;
  }, [outputVolume]);

  const syncStatusText = playbackText
    ? t('management.audioPanel.syncPlaying')
    : syncStatus === 'ready'
      ? t('management.audioPanel.syncReady')
      : isConnected
        ? t('management.audioPanel.syncSynced')
        : t('management.audioPanel.syncWaiting');

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-5 overflow-y-auto">
      {/* 页头 */}
      <div className="shrink-0">
        <h2 className="bg-gradient-to-r from-primary to-secondary bg-clip-text text-xl font-bold text-transparent">
          {t('management.audioPanel.title')}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('management.audioPanel.subtitle')}
        </p>
      </div>

      {/* Live WS 状态行 */}
      <div className="glass-panel flex shrink-0 items-center gap-3 px-4 py-3">
        <span
          className={cn(
            'h-2.5 w-2.5 rounded-full',
            isConnected ? 'bg-emerald-400' : 'bg-red-400',
          )}
        />
        <span className="text-sm text-muted-foreground">
          WebSocket: {isConnected
            ? t('management.audioPanel.wsConnected')
            : t('management.audioPanel.wsDisconnected')}
        </span>
        <span className="ml-auto rounded-full bg-primary/10 px-2.5 py-1 text-xs text-primary">
          {t('management.audioPanel.sync', { status: syncStatusText })}
        </span>
      </div>

      {micError && (
        <div className="shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {t(`management.audioPanel.${micError === 'media-unavailable' ? 'micUnavailable' : 'micStartFailed'}`)}
        </div>
      )}

      {/* 音频配置（消费 audioApi.getAudioConfig） */}
      {audioConfig && Object.keys(audioConfig).length > 0 && (
        <section className="glass-panel shrink-0 space-y-2 p-5">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Cpu className="h-4 w-4 text-primary" />
            {t('management.audioPanel.audioConfigTitle')}
          </h3>
          <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
            {Object.entries(audioConfig)
              .filter(([, value]) => value !== null && typeof value !== 'object')
              .map(([key, value]) => (
                <div key={key} className="flex items-center justify-between gap-3 text-sm">
                  <dt className="text-muted-foreground">{key}</dt>
                  <dd className="truncate font-mono text-xs text-foreground">{String(value)}</dd>
                </div>
              ))}
          </dl>
        </section>
      )}

      {/* 麦克风输入 */}
      <section className="glass-panel shrink-0 space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Mic className="h-4 w-4 text-primary" />
          {t('management.audioPanel.micTitle')}
        </h3>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => (micOn ? stopMic() : void startMic())}
            className={cn(
              'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-opacity hover:opacity-90',
              micOn ? 'bg-red-500/85 text-white' : 'bg-emerald-500/85 text-white',
            )}
          >
            {micOn ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
            {micOn ? t('management.audioPanel.micStop') : t('management.audioPanel.micStart')}
          </button>
          {micOn && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>

        {devices.length > 0 && (
          <select
            value={selectedDeviceId}
            onChange={(e) => setSelectedDeviceId(e.target.value)}
            disabled={micOn}
            aria-label={t('management.audioPanel.micTitle')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none disabled:opacity-50"
          >
            {devices.map((d) => (
              <option key={d.deviceId} value={d.deviceId}>
                {d.label}
              </option>
            ))}
          </select>
        )}

        {/* 音量电平 */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">{t('management.audioPanel.micLevel')}</span>
            <span className="text-muted-foreground/70">{Math.round(level * 100)}%</span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
            <div
              className={cn(
                'h-full rounded-full transition-all duration-100',
                level > 0.7 ? 'bg-red-400' : level > 0.3 ? 'bg-amber-400' : 'bg-emerald-400',
              )}
              style={{ width: `${level * 100}%` }}
            />
          </div>
        </div>

        {/* 麦克风增益 */}
        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">
            {t('management.audioPanel.micGain')}: {Math.round(micGain * 100)}%
          </label>
          <input
            type="range"
            min="0"
            max="2"
            step="0.05"
            value={micGain}
            onChange={(e) => setMicGain(Number.parseFloat(e.target.value))}
            aria-label={t('management.audioPanel.micGain')}
            className="w-full accent-primary"
          />
        </div>
      </section>

      {/* 音频输出 */}
      <section className="glass-panel shrink-0 space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Volume2 className="h-4 w-4 text-secondary" />
          {t('management.audioPanel.outputTitle')}
        </h3>

        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">
            {t('management.audioPanel.ttsVolume')}: {Math.round(ttsVolume * 100)}%
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={ttsVolume}
            onChange={(e) => setTtsVolume(Number.parseFloat(e.target.value))}
            aria-label={t('management.audioPanel.ttsVolume')}
            className="w-full accent-primary"
          />
        </div>

        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">
            {t('management.audioPanel.outputVolume')}: {Math.round(outputVolume * 100)}%
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={outputVolume}
            onChange={(e) => setOutputVolume(Number.parseFloat(e.target.value))}
            aria-label={t('management.audioPanel.outputVolume')}
            className="w-full accent-primary"
          />
          <p className="text-xs text-muted-foreground/70">
            {t('management.audioPanel.outputVolumeHint')}
          </p>
        </div>
      </section>

      {/* 回声消除 */}
      <section className="glass-panel shrink-0 space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Waves className="h-4 w-4 text-accent" />
          {t('management.audioPanel.aecTitle')}
        </h3>

        <div className="flex items-center justify-between">
          <span className="text-sm text-muted-foreground">
            {t('management.audioPanel.aecEnable')}
          </span>
          <button
            type="button"
            onClick={() => setAecEnabled((v) => !v)}
            aria-label={t('management.audioPanel.aecEnable')}
            className={cn(
              'relative h-6 w-11 rounded-full transition-colors',
              aecEnabled ? 'bg-primary' : 'bg-[rgba(255,255,255,0.12)]',
            )}
          >
            <span
              className={cn(
                'absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform',
                aecEnabled && 'translate-x-5',
              )}
            />
          </button>
        </div>

        <div className="space-y-1.5">
          <label className="text-sm text-muted-foreground">
            {t('management.audioPanel.aecMode')}
          </label>
          <select
            value={aecMode}
            onChange={(e) => setAecMode(e.target.value as AecMode)}
            disabled={micOn}
            aria-label={t('management.audioPanel.aecMode')}
            className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 text-sm backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none disabled:opacity-50"
          >
            <option value="auto">{t('management.audioPanel.aecAuto')}</option>
            <option value="browser">{t('management.audioPanel.aecBrowser')}</option>
            <option value="worklet">{t('management.audioPanel.aecWorklet')}</option>
            <option value="manual">{t('management.audioPanel.aecManual')}</option>
          </select>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span
            className={cn(
              'h-2 w-2 rounded-full',
              aecStatus === 'active' && 'bg-emerald-400',
              aecStatus === 'manual' && 'bg-amber-400',
              aecStatus === 'unavailable' && 'bg-muted-foreground/50',
            )}
          />
          <span className="text-muted-foreground">
            {t('management.audioPanel.aecStatusLabel')}:{' '}
            {aecStatus === 'active'
              ? t('management.audioPanel.aecStatusActive')
              : aecStatus === 'manual'
                ? t('management.audioPanel.aecStatusManual')
                : t('management.audioPanel.aecStatusInactive')}
          </span>
        </div>
      </section>

      {/* TTS 播放指示 */}
      {playbackText && (
        <div className="shrink-0 rounded-lg border border-primary/20 bg-primary/10 px-4 py-3">
          <p className="mb-1 flex items-center gap-1.5 text-xs text-primary">
            <Activity className="h-3 w-3" />
            {t('management.audioPanel.nowPlaying')}
          </p>
          <p className="truncate text-sm">{playbackText}</p>
        </div>
      )}
    </div>
  );
}
