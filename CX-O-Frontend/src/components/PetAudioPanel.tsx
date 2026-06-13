import { useState, useRef, useCallback, useEffect } from 'react';
import { useLiveWebSocket } from '../hooks/useLiveWebSocket';
import type { TTSSyncData, TTSTickData } from '../hooks/useLiveWebSocket';
import { useAudioAnalyzer } from '../hooks/useAudioAnalyzer';

interface PetAudioPanelProps {
  onMouthOpenYChange: (value: number) => void;
}

export function PetAudioPanel({ onMouthOpenYChange }: PetAudioPanelProps) {
  const [micEnabled, setMicEnabled] = useState(false);
  const [currentLevel, setCurrentLevel] = useState(0);
  const [ttsAudioElement, setTtsAudioElement] = useState<HTMLAudioElement | null>(null);
  const [isTTSPlaying, setIsTTSPlaying] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number>(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);

  // Audio analyzer for TTS lip sync
  useAudioAnalyzer({
    audioElement: ttsAudioElement,
    isPlaying: isTTSPlaying,
    enabled: true,
  });

  const { isConnected, sendAudio } = useLiveWebSocket({
    onVadStatus: (data) => {
      if (data.status === 'speech_start' && data.speech_probability !== undefined) {
        onMouthOpenYChange(Math.min(data.speech_probability * 1.5, 1));
      } else if (data.status === 'speech_end') {
        onMouthOpenYChange(0);
      }
    },
    onTTSSync: (data: TTSSyncData) => {
      handleTTSSync(data);
    },
    onTTSTick: (_data: TTSTickData) => {
      // TTS tick for sync alignment
    },
    onTTSEnd: () => {
      handleTTSEnd();
    },
  });

  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      cleanupAudio();
    };
  }, []);

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
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      const ctx = new AudioContext({ latencyHint: 'interactive' });
      audioContextRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      analyserRef.current = analyser;

      const dest = ctx.createMediaStreamDestination();
      source.connect(analyser);
      source.connect(dest);

      const processor = new MediaRecorder(dest.stream, { mimeType: 'audio/webm;codecs=opus' });
      mediaRecorderRef.current = processor;
      processor.ondataavailable = (e) => {
        if (e.data.size > 0 && sendAudio) {
          try {
            e.data.arrayBuffer().then((buf) => sendAudio(buf));
          } catch (err) {
            console.error('[PetAudioPanel] Failed to process audio data:', err);
          }
        }
      };
      processor.start(100);

      startMonitoring();
      setMicEnabled(true);
    } catch (e) {
      console.error('[PetAudioPanel] Failed to start microphone:', e);
      setMicEnabled(false);
    }
  }, [micEnabled, cleanupAudio, startMonitoring, sendAudio]);

  const handleTTSSync = useCallback((data: TTSSyncData) => {
    // Create audio element for TTS playback with lip sync
    if (data.text) {
      // The TTS audio will be played via the main chat flow
      // Here we just track the sync for mouth movement
      onMouthOpenYChange(0.6);
    }
  }, [onMouthOpenYChange]);

  const handleTTSEnd = useCallback(() => {
    onMouthOpenYChange(0);
    setIsTTSPlaying(false);
    setTtsAudioElement(null);
  }, [onMouthOpenYChange]);

  return (
    <div className="flex items-center gap-2 px-2 py-1" style={{ pointerEvents: 'auto' }}>
      {/* Mic toggle */}
      <button
        onClick={toggleMicrophone}
        className={`p-1.5 rounded-lg transition-colors ${
          micEnabled
            ? 'bg-red-500/30 text-red-400 hover:bg-red-500/40'
            : 'bg-[var(--color-bg-secondary)]/60 text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]/60'
        } backdrop-blur-sm`}
        title={micEnabled ? '关闭麦克风' : '开启麦克风'}
      >
        {micEnabled ? (
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
          </svg>
        ) : (
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
          </svg>
        )}
      </button>

      {/* Volume indicator */}
      {micEnabled && (
        <div className="flex-1 h-1.5 rounded-full bg-[var(--color-bg-tertiary)]/50 overflow-hidden backdrop-blur-sm">
          <div
            className="h-full rounded-full transition-all duration-75"
            style={{
              width: `${currentLevel * 100}%`,
              background: currentLevel > 0.7 ? '#ef4444' : currentLevel > 0.3 ? '#f59e0b' : '#22c55e',
            }}
          />
        </div>
      )}

      {/* Connection indicator */}
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ backgroundColor: isConnected ? '#4ade80' : '#f87171' }}
      />
    </div>
  );
}
