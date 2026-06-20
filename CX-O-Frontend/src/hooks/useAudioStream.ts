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

/**
 * 双流式会话标识：一次双流式对话的上下文锚点。
 * 后端用 session_id 维护流水线状态，request_id 用于追踪单轮请求。
 */
export interface DualStreamSession {
  sessionId: string;
  agentId: string;
  requestId: string;
}

/**
 * 双流式启动选项：控制 TTS 引擎与音色选择。
 * - engine: "f5-tts"（默认）或 "orpheus"，未传时后端使用 f5-tts（向后兼容）
 * - voice: Orpheus 音色名（tara/leah/jess/leo/dan/mia/zac/zoe），仅 orpheus 引擎需要
 */
export interface DualStreamStartOptions {
  engine?: string;
  voice?: string;
}

/**
 * 后端推送的 voice.* 消息统一结构。
 * 注意：voice.tts_chunk 实际通过 create_stream 发送，type 为 "stream"，
 * 但这里统一为 voice 消息视图，由 useWebSocket 路由后传入 handleVoiceMessage。
 */
export interface VoiceMessage {
  type: 'voice.partial' | 'voice.tts_chunk' | 'voice.prefill_started';
  data?: {
    text?: string;
    partial_text?: string;
    audio_data?: string;
    text_segment?: string;
    is_final?: boolean;
    session_id?: string;
    chunk_index?: number;
  };
  is_final?: boolean;
  chunk_index?: number;
  request_id?: string;
}

export interface UseAudioStreamOptions {
  wsSend: (data: object) => void;
  onVADStatus?: (status: 'speech_start' | 'speech_end', duration: number) => void;
  onVADFrame?: (frame: VADFrame) => void;
  onASRResult?: (result: ASRResult) => void;
  onInterrupt?: (result: InterruptResult) => void;
  config?: AudioStreamConfig;
  chunkInterval?: number;
  /** 双流式：ASR Partial 实时识别文本回调（interim subtitle） */
  onPartial?: (text: string, sessionId?: string) => void;
  /** 双流式：TTS 流式音频块回调（边收边播） */
  onTTSChunk?: (audioBase64: string, isFinal: boolean, textSegment?: string, sessionId?: string) => void;
  /** 双流式：LLM Prefill 已启动回调（可显示"正在思考"） */
  onPrefillStarted?: (text: string, sessionId?: string) => void;
}

export interface UseAudioStreamReturn {
  isStreaming: boolean;
  isSpeaking: boolean;
  startStreaming: () => Promise<void>;
  stopStreaming: () => void;
  resetStream: () => void;
  /** 双流式模式是否激活 */
  isDualStreaming: boolean;
  /**
   * 启动双流式会话：发送 init，持续推送音频流（不等 VAD on_end）。
   * options.engine/voice 可选：未传时后端默认使用 f5-tts（向后兼容）。
   */
  startDualStream: (
    sessionId: string,
    agentId: string,
    requestId: string,
    options?: DualStreamStartOptions,
  ) => Promise<void>;
  /** 结束双流式会话：发送 end，停止音频采集 */
  stopDualStream: () => void;
  /** 分发后端 voice.* 消息到对应回调（由 useWebSocket onMessage 调用） */
  handleVoiceMessage: (message: VoiceMessage) => void;
}

const DEFAULT_CONFIG: AudioStreamConfig = {
  sampleRate: 16000,
  channelCount: 1,
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

const MAX_AUDIO_BUFFER_LENGTH = 50;

export function useAudioStream(options: UseAudioStreamOptions): UseAudioStreamReturn {
  const {
    wsSend,
    onVADStatus,
    onVADFrame,
    onASRResult,
    onInterrupt,
    config = DEFAULT_CONFIG,
    chunkInterval = 100,
    onPartial,
    onTTSChunk,
    onPrefillStarted,
  } = options;

  const onVADStatusRef = useRef(onVADStatus);
  const onVADFrameRef = useRef(onVADFrame);
  const onASRResultRef = useRef(onASRResult);
  const onInterruptRef = useRef(onInterrupt);
  const onPartialRef = useRef(onPartial);
  const onTTSChunkRef = useRef(onTTSChunk);
  const onPrefillStartedRef = useRef(onPrefillStarted);

  useEffect(() => {
    onVADStatusRef.current = onVADStatus;
    onVADFrameRef.current = onVADFrame;
    onASRResultRef.current = onASRResult;
    onInterruptRef.current = onInterrupt;
    onPartialRef.current = onPartial;
    onTTSChunkRef.current = onTTSChunk;
    onPrefillStartedRef.current = onPrefillStarted;
  }, [onVADStatus, onVADFrame, onASRResult, onInterrupt, onPartial, onTTSChunk, onPrefillStarted]);

  const [isStreaming, setIsStreaming] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isDualStreaming, setIsDualStreaming] = useState(false);

  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const chunkIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const audioBufferRef = useRef<Int16Array[]>([]);

  // 双流式模式标志：决定 processAudioChunk 走 voice.dual_stream 还是 asr_stream
  // 用 ref 而非 state，避免闭包捕获过期值，且不触发额外渲染
  const dualStreamModeRef = useRef(false);
  const dualStreamSessionRef = useRef<DualStreamSession | null>(null);

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

    if (dualStreamModeRef.current && dualStreamSessionRef.current) {
      // 双流式：持续推送音频流，不等 VAD on_end 的静默判定。
      // 半双工需等用户说完（VAD on_end ~500ms 静默）才发音频，
      // 双流式边说边推，省下这 ~500ms 端到端延迟。
      const s = dualStreamSessionRef.current;
      wsSend({
        action: 'voice.dual_stream',
        data: {
          type: 'audio',
          audio: base64,
          session_id: s.sessionId,
          agent_id: s.agentId,
          request_id: s.requestId,
        },
      });
    } else {
      // 半双工（向后兼容）：沿用原 asr_stream action
      wsSend({
        action: 'asr_stream',
        data: {
          audio: base64,
        },
      });
    }
  }, [wsSend]);

  // 共享的麦克风采集初始化：半双工与双流式复用同一套采集管线
  const setupAudioCapture = useCallback(async () => {
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
      if (audioBufferRef.current.length >= MAX_AUDIO_BUFFER_LENGTH) {
        audioBufferRef.current.shift();
      }
      audioBufferRef.current.push(int16Data);
    };

    const mediaStreamDestination = audioContext.createMediaStreamDestination();

    source.connect(analyser);
    analyser.connect(scriptProcessor);
    scriptProcessor.connect(mediaStreamDestination);
  }, [config]);

  const startStreaming = useCallback(async () => {
    try {
      await setupAudioCapture();
      dualStreamModeRef.current = false;
      setIsStreaming(true);
      chunkIntervalRef.current = setInterval(processAudioChunk, chunkInterval);
    } catch (error) {
      console.error('Failed to start audio stream:', error);
      throw error;
    }
  }, [setupAudioCapture, chunkInterval, processAudioChunk]);

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

  // ========== 双流式模式 ==========

  const startDualStream = useCallback(async (
    sessionId: string,
    agentId: string,
    requestId: string,
    options?: DualStreamStartOptions,
  ) => {
    try {
      await setupAudioCapture();
      dualStreamModeRef.current = true;
      dualStreamSessionRef.current = { sessionId, agentId, requestId };

      const { engine, voice } = options || {};
      // 发送 init：通知后端建立双流式会话，后端据此创建流水线状态。
      // 后端协议要求 data.init === true 触发初始化分支。
      // engine/voice 仅在传入时携带：未传 engine 时后端默认使用 f5-tts（向后兼容）。
      wsSend({
        action: 'voice.dual_stream',
        data: {
          init: true,
          session_id: sessionId,
          agent_id: agentId,
          request_id: requestId,
          ...(engine && { engine }),
          ...(voice && { voice }),
        },
      });

      setIsDualStreaming(true);
      // 持续推送音频流：双流式核心——边说边推，不等 VAD on_end
      chunkIntervalRef.current = setInterval(processAudioChunk, chunkInterval);
    } catch (error) {
      console.error('Failed to start dual stream:', error);
      throw error;
    }
  }, [setupAudioCapture, wsSend, chunkInterval, processAudioChunk]);

  const stopDualStream = useCallback(() => {
    // 先发送 end：通知后端结束会话并清理流水线（即使前端还在清理音频资源）
    // 后端协议要求 data.end === true 触发结束分支。
    if (dualStreamSessionRef.current) {
      const s = dualStreamSessionRef.current;
      wsSend({
        action: 'voice.dual_stream',
        data: {
          end: true,
          session_id: s.sessionId,
          agent_id: s.agentId,
          request_id: s.requestId,
        },
      });
    }

    if (chunkIntervalRef.current) {
      clearInterval(chunkIntervalRef.current);
      chunkIntervalRef.current = null;
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
    dualStreamModeRef.current = false;
    dualStreamSessionRef.current = null;
    setIsDualStreaming(false);
  }, [wsSend]);

  /**
   * 分发后端 voice.* 消息到对应回调。
   * 由 ChatPage 在 useWebSocket onMessage 中调用，统一双流式消息入口。
   */
  const handleVoiceMessage = useCallback((message: VoiceMessage) => {
    if (!message || !message.type) return;
    const data = message.data || {};
    const sessionId = data.session_id;

    switch (message.type) {
      case 'voice.partial':
        // ASR Partial 实时识别文本：用户正在说什么（interim subtitle）
        onPartialRef.current?.(data.text || '', sessionId);
        break;
      case 'voice.prefill_started':
        // LLM Prefill 已启动：后端字段为 partial_text，兼容 text
        onPrefillStartedRef.current?.(data.partial_text || data.text || '', sessionId);
        break;
      case 'voice.tts_chunk':
        // TTS 流式音频块：边收边播，is_final 标记整句结束
        onTTSChunkRef.current?.(
          data.audio_data || '',
          message.is_final ?? data.is_final ?? false,
          data.text_segment,
          sessionId,
        );
        break;
    }
  }, []);

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
    isDualStreaming,
    startDualStream,
    stopDualStream,
    handleVoiceMessage,
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
