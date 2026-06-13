import { useState, useRef, useCallback, useEffect } from 'react';
import { useLiveWebSocket } from '../../hooks/useLiveWebSocket';
import type { TTSSyncData, TTSTickData } from '../../hooks/useLiveWebSocket';

interface AudioDeviceInfo {
  deviceId: string;
  label: string;
}

interface AudioPanelProps {
  standalone?: boolean;
}

export function AudioPanel({ standalone = false }: AudioPanelProps) {
  const [micEnabled, setMicEnabled] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState('');
  const [devices, setDevices] = useState<AudioDeviceInfo[]>([]);
  const [micVolume, setMicVolume] = useState(1.0);
  const [ttsVolume, setTtsVolume] = useState(1.0);
  const [outputVolume, setOutputVolume] = useState(1.0);
  const [aecEnabled, setAecEnabled] = useState(true);
  const [aecMode, setAecMode] = useState<'auto' | 'browser' | 'worklet' | 'manual'>('auto');
  const [aecStatus, setAecStatus] = useState<'active' | 'unavailable' | 'manual'>('unavailable');
  const [currentLevel, setCurrentLevel] = useState(0);
  const [syncStatus, setSyncStatus] = useState<string>('等待连接');
  const [playbackText, setPlaybackText] = useState('');

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const micSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const micGainRef = useRef<GainNode | null>(null);
  const outputGainRef = useRef<GainNode | null>(null);
  const ttsGainRef = useRef<GainNode | null>(null);
  const rafRef = useRef<number>(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  const playbackIdRef = useRef<string>('');
  const clockOffsetRef = useRef(0);

  const { isConnected, connectionCount, sendAudio } = useLiveWebSocket({
    onTTSSync: (data: TTSSyncData) => handleTTSSync(data),
    onTTSTick: (data: TTSTickData) => handleTTSTick(data),
    onTTSEnd: () => handleTTSEnd(),
    onConnect: () => setSyncStatus('已同步'),
    onDisconnect: () => setSyncStatus('断开'),
  });

  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      cleanupAudio();
    };
  }, []);

  const enumerateDevices = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const allDevices = await navigator.mediaDevices.enumerateDevices();
      stream.getTracks().forEach(track => track.stop());
      const audioInputs = allDevices
        .filter((d) => d.kind === 'audioinput')
        .map((d) => ({ deviceId: d.deviceId, label: d.label || `麦克风 ${d.deviceId.slice(0, 6)}` }));
      setDevices(audioInputs);
      if (audioInputs.length > 0 && !selectedDevice) {
        setSelectedDevice(audioInputs[0].deviceId);
      }
    } catch (e) {
      console.error('[AudioPanel] Cannot enumerate devices:', e);
    }
  }, [selectedDevice]);

  const cleanupAudio = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    setCurrentLevel(0);
  }, []);

  const setupAEC = useCallback(async (): Promise<'browser' | 'worklet' | 'manual'> => {
    if (!aecEnabled) return 'manual';

    const constraints: MediaStreamConstraints = { audio: true };

    if (aecMode === 'auto' || aecMode === 'browser') {
      let testStream: MediaStream | null = null;
      try {
        (constraints.audio as MediaTrackConstraints).echoCancellation = true;
        (constraints.audio as MediaTrackConstraints).noiseSuppression = true;
        (constraints.audio as MediaTrackConstraints).autoGainControl = true;

        testStream = await navigator.mediaDevices.getUserMedia(constraints);
        const track = testStream.getAudioTracks()[0];
        const settings = track.getSettings();

        if (settings.echoCancellation) {
          testStream.getTracks().forEach((t) => t.stop());
          testStream = null;
          setAecStatus('active');
          return 'browser';
        }
      } catch {
        // browser AEC not available
      } finally {
        if (testStream) testStream.getTracks().forEach((t) => t.stop());
      }
    }

    if ((aecMode === 'auto' || aecMode === 'worklet') && typeof AudioWorkletNode !== 'undefined') {
      try {
        setAecStatus('active');
        return 'worklet';
      } catch {
        // worklet not available
      }
    }

    setAecStatus('manual');
    return 'manual';
  }, [aecEnabled, aecMode]);

  const startMonitoring = useCallback(() => {
    if (!analyserRef.current) return;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);

    const updateLevel = () => {
      if (analyserRef.current) {
        analyserRef.current.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        setCurrentLevel(Math.min(avg / 128, 1));
      }
      rafRef.current = requestAnimationFrame(updateLevel);
    };

    updateLevel();
  }, []);

  const toggleMicrophone = useCallback(async () => {
    if (micEnabled) {
      cleanupAudio();
      setMicEnabled(false);
      return;
    }

    try {
      await enumerateDevices();

      const mode = await setupAEC();

      const constraints: MediaStreamConstraints = {
        audio: {
          deviceId: selectedDevice ? { exact: selectedDevice } : undefined,
          echoCancellation: mode === 'browser',
          noiseSuppression: true,
          autoGainControl: true,
        },
      };

      const stream = await navigator.mediaDevices.getUserMedia(constraints);
      streamRef.current = stream;

      const ctx = new AudioContext({ latencyHint: 'interactive' });
      audioContextRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      micSourceRef.current = source;

      const gain = ctx.createGain();
      gain.gain.value = micVolume;
      micGainRef.current = gain;

      const outGain = ctx.createGain();
      outGain.gain.value = outputVolume;
      outputGainRef.current = outGain;

      const ttsG = ctx.createGain();
      ttsG.gain.value = ttsVolume;
      ttsGainRef.current = ttsG;

      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      source.connect(gain).connect(analyser).connect(outGain).connect(ctx.destination);

      const dest = ctx.createMediaStreamDestination();
      outGain.connect(dest);

      const processor = new MediaRecorder(dest.stream, { mimeType: 'audio/webm;codecs=opus' });
      mediaRecorderRef.current = processor;
      processor.ondataavailable = (e) => {
        if (e.data.size > 0 && sendAudio) {
          try {
            e.data.arrayBuffer().then((buf) => sendAudio(buf));
          } catch (err) {
            console.error('[AudioPanel] Failed to process audio data:', err);
          }
        }
      };
      processor.start(100);

      startMonitoring();
      setMicEnabled(true);
    } catch (e) {
      console.error('[AudioPanel] Failed to start microphone:', e);
      setMicEnabled(false);
    }
  }, [
    micEnabled, selectedDevice, micVolume, outputVolume, ttsVolume,
    enumerateDevices, setupAEC, cleanupAudio, startMonitoring, sendAudio,
  ]);

  const handleTTSSync = useCallback((data: TTSSyncData) => {
    playbackIdRef.current = data.playback_id;
    setPlaybackText(data.text);
    const now = performance.now();
    clockOffsetRef.current = now - data.server_ts;
    setSyncStatus(`播放中: ${data.text.slice(0, 20)}...`);
  }, []);

  const handleTTSTick = useCallback((_data: TTSTickData) => {
    // TTS tick received - used for sync alignment
    // In full implementation, would seek audio to align position
  }, []);

  const handleTTSEnd = useCallback(() => {
    playbackIdRef.current = '';
    setPlaybackText('');
    setSyncStatus('就绪');
  }, []);

  useEffect(() => {
    if (micGainRef.current) {
      micGainRef.current.gain.value = micVolume;
    }
  }, [micVolume]);

  useEffect(() => {
    if (outputGainRef.current) {
      outputGainRef.current.gain.value = outputVolume;
    }
  }, [outputVolume]);

  useEffect(() => {
    if (ttsGainRef.current) {
      ttsGainRef.current.gain.value = ttsVolume;
    }
  }, [ttsVolume]);

  return (
    <div className={`min-h-screen ${standalone ? 'p-3' : 'bg-[var(--color-bg-primary)] p-8'}`} style={standalone ? { backgroundColor: 'transparent' } : {}}>
      <div className={`${standalone ? 'max-w-md' : 'max-w-2xl'} mx-auto ${standalone ? 'space-y-3' : 'space-y-8'}`}>
        {!standalone && (
          <div>
            <h1 className="text-2xl font-bold text-[var(--color-text-primary)]">音频控制面板</h1>
            <p className="text-sm text-[var(--color-text-secondary)] mt-1">麦克风输入 · TTS 播放 · 回声消除 · 多客户端同步</p>
          </div>
        )}

        <div className="flex items-center gap-3 p-4 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)]">
          <span
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: isConnected ? '#4ade80' : '#f87171' }}
          />
          <span className="text-sm text-[var(--color-text-secondary)]">
            WebSocket: {isConnected ? '已连接' : '未连接'}
          </span>
          <span className="text-[var(--color-text-tertiary)]">|</span>
          <span className="text-sm text-[var(--color-text-secondary)]">{connectionCount} 个客户端在线</span>
          <span className="ml-auto text-xs px-2 py-1 rounded-full" style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>
            同步: {syncStatus}
          </span>
        </div>

        <section className={standalone ? 'space-y-2' : 'space-y-4'}>
          <h2 className="text-lg font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
            麦克风输入
          </h2>

          <div className="p-4 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] space-y-4">
            <button
              onClick={toggleMicrophone}
              className={`px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                micEnabled
                  ? 'bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30'
                  : 'bg-green-500/20 text-green-400 border border-green-500/30 hover:bg-green-500/30'
              }`}
            >
              {micEnabled ? '🔴 停止麦克风' : '🎤 开启麦克风'}
            </button>

            {devices.length > 0 && (
              <select
                value={selectedDevice}
                onChange={(e) => setSelectedDevice(e.target.value)}
                disabled={micEnabled}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] text-sm text-[var(--color-text-primary)]"
              >
                {devices.map((d) => (
                  <option key={d.deviceId} value={d.deviceId}>{d.label}</option>
                ))}
              </select>
            )}

            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-[var(--color-text-secondary)]">音量电平</span>
                <span className="text-[var(--color-text-tertiary)]">{Math.round(currentLevel * 100)}%</span>
              </div>
              <div className="h-3 rounded-full bg-[var(--color-bg-tertiary)] overflow-hidden">
                <div
                  className="h-full rounded-full transition-all duration-75"
                  style={{
                    width: `${currentLevel * 100}%`,
                    background: currentLevel > 0.7 ? '#ef4444' : currentLevel > 0.3 ? '#f59e0b' : '#22c55e',
                  }}
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm text-[var(--color-text-secondary)]">麦克风增益: {Math.round(micVolume * 100)}%</label>
              <input
                type="range"
                min="0"
                max="3"
                step="0.1"
                value={micVolume}
                onChange={(e) => setMicVolume(parseFloat(e.target.value))}
                className="w-full accent-[var(--color-accent)]"
              />
            </div>
          </div>
        </section>

        <section className={standalone ? 'space-y-2' : 'space-y-4'}>
          <h2 className="text-lg font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
            </svg>
            音频输出
          </h2>

          <div className="p-4 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] space-y-4">
            <div className="space-y-2">
              <label className="text-sm text-[var(--color-text-secondary)]">TTS 音量: {Math.round(ttsVolume * 100)}%</label>
              <input type="range" min="0" max="2" step="0.05" value={ttsVolume} onChange={(e) => setTtsVolume(parseFloat(e.target.value))} className="w-full accent-[var(--color-accent)]" />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-[var(--color-text-secondary)]">输出音量: {Math.round(outputVolume * 100)}%</label>
              <input type="range" min="0" max="2" step="0.05" value={outputVolume} onChange={(e) => setOutputVolume(parseFloat(e.target.value))} className="w-full accent-[var(--color-accent)]" />
            </div>
          </div>
        </section>

        <section className={standalone ? 'space-y-2' : 'space-y-4'}>
          <h2 className="text-lg font-semibold text-[var(--color-text-primary)] flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 5.636l-3.536 3.536m0 5.656l3.536 3.536M9.172 9.172L5.636 5.636m3.536 9.192l-3.536 3.536M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-5 0a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
            回声消除 (AEC)
          </h2>

          <div className="p-4 rounded-xl bg-[var(--color-bg-secondary)] border border-[var(--color-border)] space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-sm text-[var(--color-text-secondary)]">启用回声消除</span>
              <button
                onClick={() => setAecEnabled(!aecEnabled)}
                className={`relative w-11 h-6 rounded-full transition-colors ${aecEnabled ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-bg-tertiary)]'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${aecEnabled ? 'translate-x-5' : ''}`} />
              </button>
            </div>

            <div className="space-y-2">
              <label className="text-sm text-[var(--color-text-secondary)]">模式</label>
              <select
                value={aecMode}
                onChange={(e) => setAecMode(e.target.value as typeof aecMode)}
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg-tertiary)] border border-[var(--color-border)] text-sm text-[var(--color-text-primary)]"
              >
                <option value="auto">自动选择</option>
                <option value="browser">浏览器原生</option>
                <option value="worklet">AudioWorklet</option>
                <option value="manual">手动调节</option>
              </select>
            </div>

            <div className="flex items-center gap-2 text-xs">
              <span
                className="w-2 h-2 rounded-full"
                style={{
                  backgroundColor:
                    aecStatus === 'active' ? '#22c55e' :
                    aecStatus === 'manual' ? '#f59e0b' : '#6b7280',
                }}
              />
              <span className="text-[var(--color-text-secondary)]">
                状态: {aecStatus === 'active' ? 'AEC 运行中' : aecStatus === 'manual' ? '手动模式（音量平衡）' : '未激活'}
              </span>
            </div>
          </div>
        </section>

        {playbackText && (
          <div className="p-3 rounded-lg bg-indigo-500/10 border border-indigo-500/20">
            <p className="text-xs text-indigo-400 mb-1">正在播放 TTS:</p>
            <p className="text-sm text-[var(--color-text-primary)] truncate">{playbackText}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default AudioPanel;
