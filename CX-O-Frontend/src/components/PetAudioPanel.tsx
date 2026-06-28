import { useState, useCallback } from 'react';
import { useLiveWebSocket } from '../hooks/useLiveWebSocket';
import type { TTSSyncData, TTSTickData } from '../hooks/useLiveWebSocket';
import { useAudioAnalyzer } from '../hooks/useAudioAnalyzer';
import { useMicrophone } from '../hooks/useMicrophone';

interface PetAudioPanelProps {
  onMouthOpenYChange: (value: number) => void;
}

export function PetAudioPanel({ onMouthOpenYChange }: PetAudioPanelProps) {
  const [ttsAudioElement, setTtsAudioElement] = useState<HTMLAudioElement | null>(null);
  const [isTTSPlaying, setIsTTSPlaying] = useState(false);

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

  const {
    isEnabled: micEnabled,
    currentLevel,
    toggle: toggleMicrophone,
  } = useMicrophone({
    onDataAvailable: (buf) => {
      if (sendAudio) sendAudio(buf);
    },
  });

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
