import { useRef, useState, useCallback, useEffect } from 'react';

export interface AudioStreamConfig {
  sampleRate?: number;
  channelCount?: number;
  echoCancellation?: boolean;
  noiseSuppression?: boolean;
  autoGainControl?: boolean;
}

export interface VADFrame {
  is_speaking: boolean;
  speech_probability: number;
  speech_duration_ms: number;
}

export interface ASRResult {
  text: string;
  is_final: boolean;
}

export interface InterruptResult {
  should_reply: boolean;
  reply_content: string;
}

export interface UseAudioStreamOptions {
  wsSend: (data: object) => void;
  onVADStatus?: (status: 'speech_start' | 'speech_end', duration: number) => void;
  onVADFrame?: (frame: VADFrame) => void;
  onASRResult?: (result: ASRResult) => void;
  onInterrupt?: (result: InterruptResult) => void;
  config?: AudioStreamConfig;
  chunkInterval?: number;
}

export interface UseAudioStreamReturn {
  isStreaming: boolean;
  isSpeaking: boolean;
  startStreaming: () => Promise<void>;
  stopStreaming: () => void;
  resetStream: () => void;
}

const DEFAULT_CONFIG: AudioStreamConfig = {
  sampleRate: 16000,
  channelCount: 1,
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

export function useAudioStream(options: UseAudioStreamOptions): UseAudioStreamReturn {
  const {
    wsSend,
    onVADStatus: _onVADStatus,
    onVADFrame: _onVADFrame,
    onASRResult: _onASRResult,
    onInterrupt: _onInterrupt,
    config = DEFAULT_CONFIG,
    chunkInterval = 100,
  } = options;

  const [isStreaming, setIsStreaming] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const chunkIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const audioBufferRef = useRef<Int16Array[]>([]);

  const processAudioChunk = useCallback(() => {
    if (!audioBufferRef.current.length) return;

    const totalLength = audioBufferRef.current.reduce((sum, arr) => sum + arr.length, 0);
    const combined = new Int16Array(totalLength);
    let offset = 0;
    for (const chunk of audioBufferRef.current) {
      combined.set(chunk, offset);
      offset += chunk.length;
    }
    audioBufferRef.current = [];

    const base64 = arrayBufferToBase64(combined.buffer);
    wsSend({
      action: 'asr_stream',
      data: {
        audio: base64,
      },
    });
  }, [wsSend]);

  const startStreaming = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: config.sampleRate || 16000,
          channelCount: config.channelCount || 1,
          echoCancellation: config.echoCancellation ?? true,
          noiseSuppression: config.noiseSuppression ?? true,
          autoGainControl: config.autoGainControl ?? true,
        },
      });

      mediaStreamRef.current = stream;

      const audioContext = new AudioContext({
        sampleRate: config.sampleRate || 16000,
      });
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;

      const bufferSize = 4096;
      const scriptProcessor = audioContext.createScriptProcessor(bufferSize, 1, 1);

      scriptProcessor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0);
        const int16Data = float32ToInt16(inputData);
        audioBufferRef.current.push(int16Data);
      };

      source.connect(analyser);
      analyser.connect(scriptProcessor);
      scriptProcessor.connect(audioContext.destination);

      setIsStreaming(true);

      chunkIntervalRef.current = setInterval(processAudioChunk, chunkInterval);

    } catch (error) {
      console.error('Failed to start audio stream:', error);
      throw error;
    }
  }, [config, chunkInterval, processAudioChunk]);

  const stopStreaming = useCallback(() => {
    if (chunkIntervalRef.current) {
      clearInterval(chunkIntervalRef.current);
      chunkIntervalRef.current = null;
    }

    if (audioBufferRef.current.length > 0) {
      processAudioChunk();
    }

    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }

    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }

    analyserRef.current = null;
    audioBufferRef.current = [];
    setIsStreaming(false);
    setIsSpeaking(false);
  }, [processAudioChunk]);

  const resetStream = useCallback(() => {
    wsSend({
      action: 'asr_stream',
      data: { reset: true },
    });
    audioBufferRef.current = [];
  }, [wsSend]);

  useEffect(() => {
    return () => {
      stopStreaming();
    };
  }, [stopStreaming]);

  return {
    isStreaming,
    isSpeaking,
    startStreaming,
    stopStreaming,
    resetStream,
  };
}

function float32ToInt16(float32Array: Float32Array): Int16Array {
  const int16Array = new Int16Array(float32Array.length);
  for (let i = 0; i < float32Array.length; i++) {
    const s = Math.max(-1, Math.min(1, float32Array[i]));
    int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return int16Array;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export default useAudioStream;
