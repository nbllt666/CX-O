/**
 * 聊天主 WebSocket 钩子（/ws）。
 *
 * 行为口径对齐 CX-O-Frontend useWebSocket：
 * - 连接打开后发送 config（agent_id + timeout），30s ping 心跳
 * - 消息路由：stream / voice.partial / voice.tts_chunk / voice.prefill_started /
 *   voice.speaker / response / error / content / done / cancelled / vad_status /
 *   cluster_event / autonomy_cost_alert（toast）/ skill_triggered 等（eventsStore）
 * - TTS 流式播放：首包优先、back-to-back 衔接、全双工打断
 * - fixed 2s 自动重连（覆盖 HMR 与网络抖动）
 * - 带图消息返回 false，由 caller 回退 HTTP /api/chat/stream
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { getWsBaseUrl, STORAGE_KEYS } from '../api/base';
import { VoiceActions } from '../constants/actions';
import { useToastStore } from '../store/toastStore';
import { useEventsStore } from '../store/eventsStore';
import { useWSTransport } from './ws/transport';
import { createDefaultRelayDeps, handleCxfcRelayCall, type CxfcRelayCallMessage } from './ws/cxfcRelay';

/** D9：cluster_event 中需要弹 toast 的主题（切换/故障类）；心跳/拓扑加入类不弹防刷屏 */
const CLUSTER_TOAST_TOPICS = new Set([
  'cluster.failover_started',
  'cluster.failover_completed',
  'cluster.node_left',
  'cluster.role_changed',
]);

export interface WebSocketMessage {
  type: string;
  content?: string;
  message?: string;
  done?: boolean;
  error?: string | { code: string; message: string };
  session_id?: string;
  tool_call?: Record<string, unknown>;
  tool_name?: string;
  result?: unknown;
  triggered_at?: string;
  request_id?: string;
  // CXFC relay（前端转接）推送字段（P2-T2）
  plugin_id?: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  token?: string;
  action?: string;
  status?: string;
  data?: {
    content?: string;
    /** 声纹：注册说话人标识（=注册名，Task 7.1 仅注册命中带） */
    speaker_id?: string;
    /** 声纹：注册说话人名（未注册/伪名 spk_N 不带） */
    speaker_name?: string;
    [key: string]: unknown;
  };
  is_final?: boolean;
  chunk_index?: number;
  is_speaking?: boolean;
  speech_probability?: number;
  speech_duration_ms?: number;
  silence_duration_ms?: number;
  should_reply?: boolean;
  reply_content?: string;
  event?: string;
}

export interface WebSocketOptions {
  agentId: string;
  timeout?: number;
  onMessage?: (data: WebSocketMessage) => void;
  onAlarm?: (message: string, triggeredAt: string) => void;
  onExternalEvent?: (eventData: Record<string, unknown>) => void;
  onError?: (error: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  /** 双流式：ASR Partial 实时识别文本（用户正在说什么）；speakerName 为注册说话人名（未命中为空串） */
  onPartial?: (text: string, sessionId?: string, speakerName?: string) => void;
  /** 双流式：TTS 流式音频块（边收边播，同时由内部队列自动播放） */
  onTTSChunk?: (audioBase64: string, isFinal: boolean, textSegment?: string, sessionId?: string) => void;
  /** 双流式：LLM Prefill 已启动（可显示"正在思考"） */
  onPrefillStarted?: (text: string, sessionId?: string) => void;
  /** 双流式：TTS 播放状态变化（用于口型同步/打断反馈） */
  onTTSPlayingChange?: (playing: boolean) => void;
  /** 音画同步：累计的原始含标签文本段拼接结果（供外部增量定位/字幕对齐） */
  onTextProgress?: (cumulativeRaw: string) => void;
  /** D6：voice.speaker 事件——当前说话人识别结果（spk 补充消息，speaker_name 仅注册命中非空） */
  onSpeaker?: (speaker: {
    speakerId: string;
    speakerName: string;
    speakerRegistered: boolean;
    speakerConf: number;
  }) => void;
}

export interface DualStreamPayload {
  type: 'init' | 'audio' | 'end';
  audio?: string;
  session_id: string;
  agent_id: string;
  request_id: string;
}

export interface UseWebSocketReturn {
  isConnected: boolean;
  isGenerating: boolean;
  isTTSPlaying: boolean;
  sendMessage: (message: string, images?: string[]) => boolean;
  cancelGeneration: () => void;
  disconnect: () => void;
  reconnect: () => void;
  /** 发送双流式会话消息（init/audio/end 复用 voice.dual_stream action） */
  sendDualStream: (payload: DualStreamPayload) => void;
  /** 全双工打断：立即停止 TTS 播放并清空音频队列 */
  interruptTTS: () => void;
  /** 通用原始消息发送（供 useAudioStream 等 hook 复用同一 WebSocket 连接） */
  sendRaw: (data: object) => void;
  /**
   * 口型同步分接：TTS 播放链上的 AnalyserNode（懒创建，首次播放前返回 null）。
   * 调用方用 RAF 周期读取频谱（getByteFrequencyData），只读不影响播放。
   */
  getTTSAnalyser: () => AnalyserNode | null;
  /** TTS 播放音量 0~1（audioStore.ttsVolume）；播放器懒创建前调用会暂存，创建时应用 */
  setTTSVolume: (volume: number) => void;
}

export function useWebSocket(options: WebSocketOptions): UseWebSocketReturn {
  const agentId = options.agentId;
  const propTimeout = options.timeout;

  const getStoredTimeout = useCallback(() => {
    const stored = localStorage.getItem(STORAGE_KEYS.offlineTimeout);
    if (!stored) return 60;
    // parseInt 坏串返回 NaN → 回退默认 60，避免 JSON.stringify(NaN) 下发 timeout:null
    const parsed = parseInt(stored, 10);
    return Number.isFinite(parsed) ? parsed : 60;
  }, []);

  const [timeout, setTimeoutState] = useState(propTimeout || getStoredTimeout());

  const pingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const agentIdRef = useRef(agentId);
  const timeoutRef = useRef(timeout);

  const onMessageRef = useRef(options.onMessage);
  const onAlarmRef = useRef(options.onAlarm);
  const onErrorRef = useRef(options.onError);
  const onConnectRef = useRef(options.onConnect);
  const onDisconnectRef = useRef(options.onDisconnect);
  const onExternalEventRef = useRef(options.onExternalEvent);
  const onPartialRef = useRef(options.onPartial);
  const onTTSChunkRef = useRef(options.onTTSChunk);
  const onPrefillStartedRef = useRef(options.onPrefillStarted);
  const onTTSPlayingChangeRef = useRef(options.onTTSPlayingChange);
  const onTextProgressRef = useRef(options.onTextProgress);
  const onSpeakerRef = useRef(options.onSpeaker);
  // 跨 tts_chunk 累计的原始含标签文本段拼接结果；会话间需重置防污染
  const textProgressRef = useRef('');

  useEffect(() => {
    onMessageRef.current = options.onMessage;
    onAlarmRef.current = options.onAlarm;
    onErrorRef.current = options.onError;
    onConnectRef.current = options.onConnect;
    onDisconnectRef.current = options.onDisconnect;
    onExternalEventRef.current = options.onExternalEvent;
    onPartialRef.current = options.onPartial;
    onTTSChunkRef.current = options.onTTSChunk;
    onPrefillStartedRef.current = options.onPrefillStarted;
    onTTSPlayingChangeRef.current = options.onTTSPlayingChange;
    onTextProgressRef.current = options.onTextProgress;
    onSpeakerRef.current = options.onSpeaker;
  });

  // TTS 流式播放器：收到第一个 tts_chunk 立即播放，不等整句合成完成。
  // 用 ref 持有，跨渲染保持单例；播放状态变化通过 setIsTTSPlaying 同步到 React。
  const ttsPlayerRef = useRef<TTSStreamPlayer | null>(null);
  // getter ref：打破"connect（含 ws.onmessage）定义在 getTTSPlayer 之前"的循环依赖
  const getTTSPlayerRef = useRef<(() => TTSStreamPlayer) | null>(null);
  const [isTTSPlaying, setIsTTSPlaying] = useState(false);

  useEffect(() => {
    timeoutRef.current = timeout;
  }, [timeout]);

  // ── 生成态客户端超时兜底：服务端异常静默（未发任何终结/流数据）时自动复位，
  //    避免 isGenerating 永久卡死（PetPage 依赖它）。任何流数据/终结事件到达即续期或清除。
  const GENERATION_TIMEOUT_MS = 60000;
  const generatingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 镜像 isGenerating，供消息路由（handleMessage）快速判断是否处于生成态
  const isGeneratingRef = useRef(false);

  const clearGeneratingTimer = useCallback(() => {
    if (generatingTimerRef.current) {
      clearTimeout(generatingTimerRef.current);
      generatingTimerRef.current = null;
    }
  }, []);

  const resetIsGenerating = useCallback(() => {
    isGeneratingRef.current = false;
    clearGeneratingTimer();
    setIsGenerating(false);
  }, [clearGeneratingTimer]);

  const startGeneratingTimer = useCallback(() => {
    clearGeneratingTimer();
    generatingTimerRef.current = setTimeout(() => {
      isGeneratingRef.current = false;
      setIsGenerating(false);
      // F7: 超时静默结束后清空累计文本，避免残留到下一会话
      textProgressRef.current = '';
    }, GENERATION_TIMEOUT_MS);
  }, [clearGeneratingTimer]);

  const clearPingInterval = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
  }, []);

  const startPingInterval = useCallback(
    (ws: WebSocket) => {
      clearPingInterval();
      pingIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 30000);
    },
    [clearPingInterval],
  );

  // 卸载时清理心跳定时器，避免跨多次挂载累积残留心跳 interval（泄漏）
  useEffect(() => clearPingInterval, [clearPingInterval]);

  // 消息路由：transport 不解析 JSON，caller 负责解析 + 路由。
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data: WebSocketMessage = JSON.parse(event.data);

      switch (data.type) {
        case 'pong':
          break;
        case 'alarm':
          onAlarmRef.current?.(data.message || '', data.triggered_at || '');
          break;
        case 'stream': {
          // 双流式 TTS 音频块：type 为 "stream"、action 为 "voice.tts_chunk"，
          // 需与普通聊天 content 流区分。
          if (data.action === VoiceActions.TTS_CHUNK) {
            const audioBase64 = (data.data?.audio_data as string) || '';
            const textSegment = (data.data?.text_segment as string) || '';
            const sessionId = data.data?.session_id as string | undefined;
            const isFinal = data.is_final ?? false;
            // 首包优先：立即入队播放，不等整句合成完成
            getTTSPlayerRef.current?.().enqueue(audioBase64, isFinal);
            onTTSChunkRef.current?.(audioBase64, isFinal, textSegment, sessionId);
            // 音画同步：非空文本段累计拼接并回传（顺序在 onTTSChunk 之后，参数/行为不回退）
            if (textSegment) {
              textProgressRef.current += textSegment;
              onTextProgressRef.current?.(textProgressRef.current);
            }
            break;
          }
          if (data.is_final) {
            resetIsGenerating();
            onMessageRef.current?.({ type: 'done' });
          } else if (data.data?.content) {
            // 续期客户端生成超时：长 TTS/长文本生成期间会持续收到非 final 内容块，
            // 每个内容块到达都重新起算 60s，防止生成 >60s 时在 done 前误复位 isGenerating。
            startGeneratingTimer();
            onMessageRef.current?.({ type: 'content', content: data.data.content });
          }
          break;
        }
        case VoiceActions.PARTIAL: {
          // ASR Partial 实时识别文本：用户正在说什么（interim subtitle）
          const text = (data.data?.text as string) || '';
          const sessionId = data.data?.session_id as string | undefined;
          const speakerName = (data.data?.speaker_name as string) || '';
          onPartialRef.current?.(text, sessionId, speakerName);
          break;
        }
        case VoiceActions.PREFILL_STARTED: {
          // LLM Prefill 已启动：后端字段为 partial_text，兼容 text
          const text = (data.data?.partial_text as string) || (data.data?.text as string) || '';
          const sessionId = data.data?.session_id as string | undefined;
          onPrefillStartedRef.current?.(text, sessionId);
          break;
        }
        case 'response':
          if (data.status === 'error') {
            resetIsGenerating();
            const errorMsg = typeof data.error === 'object' ? data.error?.message : data.error;
            onErrorRef.current?.(errorMsg || 'Unknown error');
          }
          break;
        case 'error': {
          resetIsGenerating();
          const errMsg = typeof data.error === 'object' ? data.error?.message : data.error;
          onErrorRef.current?.(errMsg || 'Unknown error');
          break;
        }
        case 'content':
        case 'chat_chunk':
          onMessageRef.current?.({ type: 'content', content: data.content });
          break;
        case 'done':
        case 'chat_done':
          // B6：统一走 resetIsGenerating（isGeneratingRef 复位 + 计时器清理 + setState），
          // 与 cancelled/error 分支语义一致，避免镜像 ref 与状态不一致
          resetIsGenerating();
          // 会话结束：清空累计文本段，避免跨会话污染
          textProgressRef.current = '';
          onMessageRef.current?.({ type: 'done' });
          break;
        case 'chat_response':
          resetIsGenerating();
          if (data.content) {
            onMessageRef.current?.({ type: 'content', content: data.content });
          }
          onMessageRef.current?.({ type: 'done' });
          break;
        case 'cancelled':
          resetIsGenerating();
          onMessageRef.current?.(data);
          break;
        case 'thinking':
        case 'vad_status':
        case 'vad_frame':
        case 'agent_interrupt_user':
        case 'agent_reply':
          onMessageRef.current?.(data);
          break;
        case 'voice.speaker': {
          // D6：声纹 spk 补充消息（text 空的识别帧）——解析当前说话人并经回调交使用方记录；
          // speaker_name 仅注册命中非空，未注册时 speakerId 为伪名（spk_N）
          const speakerData = (data.data || {}) as Record<string, unknown>;
          onSpeakerRef.current?.({
            speakerId: String(speakerData.speaker_id || ''),
            speakerName: String(speakerData.speaker_name || ''),
            speakerRegistered: Boolean(speakerData.speaker_registered),
            speakerConf: Number(speakerData.speaker_conf || 0),
          });
          onMessageRef.current?.(data);
          break;
        }
        case 'cluster_event': {
          // D9：集群广播事件——仅切换/故障类主题弹轻量 toast（心跳/拓扑类不弹防刷屏）
          const clusterEvent = (data.data || {}) as Record<string, unknown>;
          const topic = String(clusterEvent.topic || '');
          if (CLUSTER_TOAST_TOPICS.has(topic)) {
            useToastStore.getState().push({ kind: 'cluster', topic, data: clusterEvent });
          }
          onMessageRef.current?.(data);
          break;
        }
        case 'autonomy_cost_alert': {
          // D9：自主系统成本告警——直接弹轻量 toast（data: usage_ratio/daily_used/limit/date）
          useToastStore.getState().push({
            kind: 'cost',
            data: (data.data || {}) as Record<string, unknown>,
          });
          onMessageRef.current?.(data);
          break;
        }
        case 'skill_triggered':
        case 'plugin_status_changed':
        case 'system.wake': {
          // D9：广播事件入有界事件存档（不做 UI，供后续功能查询）
          useEventsStore.getState().push(data.type, data.data);
          onMessageRef.current?.(data);
          break;
        }
        case 'external_event':
          if (onExternalEventRef.current && data.data) {
            onExternalEventRef.current(data.data as Record<string, unknown>);
          }
          onMessageRef.current?.(data);
          break;
        case 'cxfc_relay_call': {
          // CXFC relay（前端转接）：收到后端推送的工具调用，本地执行电脑控制工具并回报结果（P2-T2）
          void handleCxfcRelayCall(data as CxfcRelayCallMessage, createDefaultRelayDeps());
          break;
        }
        default:
          onMessageRef.current?.(data);
      }
    } catch (e: unknown) {
      console.error('Failed to parse WebSocket message:', e);
    }
  }, [startGeneratingTimer, clearGeneratingTimer, resetIsGenerating]);

  // Transport：URL 构造 + 实例化 + 生命周期；业务逻辑经回调注入。
  // enabled: !!agentId 保留空 agentId 不连接的守卫。
  const {
    wsRef,
    isConnected,
    disconnect: transportDisconnect,
    reconnect: transportReconnect,
  } = useWSTransport({
    urlBuilder: () => `${getWsBaseUrl()}/ws`,
    enabled: !!agentId,
    // fixed 2s 重连覆盖开发态 HMR 与运行态网络抖动两类场景
    reconnect: { strategy: 'fixed', delay: 2000 },
    onOpen: (ws) => {
      startPingInterval(ws);
      // 同步最新的 agentId 和 timeout 到服务端
      ws.send(
        JSON.stringify({
          type: 'config',
          agent_id: agentIdRef.current,
          timeout: timeoutRef.current,
        }),
      );
      onConnectRef.current?.();
    },
    onClose: () => {
      // 服务端主动关闭时清理（手动 disconnect 走 wrapper 的 cleanup）
      resetIsGenerating();
      clearPingInterval();
      // 断开时清空累计文本段，重连后不残留上一会话内容
      textProgressRef.current = '';
      onDisconnectRef.current?.();
    },
    onError: (error) => {
      console.error('WebSocket error:', error);
      onErrorRef.current?.(error);
    },
    onMessage: handleMessage,
  });

  // 手动 disconnect：transport 会 null 化 onclose（防止自动重连），
  // 所以 onClose 回调不会触发，需在此显式清理业务状态。
  const disconnect = useCallback(() => {
    transportDisconnect();
    resetIsGenerating();
    clearPingInterval();
    onDisconnectRef.current?.();
  }, [transportDisconnect, clearPingInterval, resetIsGenerating]);

  const reconnect = useCallback(() => {
    transportReconnect();
  }, [transportReconnect]);

  const sendMessage = useCallback(
    (message: string, images?: string[]): boolean => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        // 不调 onError：让 caller 根据返回值决定 fallback 或显示错误
        return false;
      }

      // 带图片消息：WS 后端 chat_stream 不支持 images，返回 false 让 caller 回退 HTTP。
      // 必须在 setIsGenerating(true) 之前返回，否则 isGenerating 状态永久卡住。
      if (images && images.length > 0) {
        return false;
      }

      isGeneratingRef.current = true;
      setIsGenerating(true);
      startGeneratingTimer();
      // 后端协议：平铺格式，handler 直接读 message 顶层字段。
      // session_id 固定为 agent-{agentId}，与 ChatPage 历史读取键（getChatHistory）
      // 保持一致，确保 WS 消息写入与前端历史读取落在同一会话。
      wsRef.current.send(
        JSON.stringify({
          type: 'chat_stream',
          message,
          agent_id: agentIdRef.current,
          session_id: `agent-${agentIdRef.current}`,
        }),
      );
      return true;
    },
    [wsRef, startGeneratingTimer],
  );

  const cancelGeneration = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }
    wsRef.current.send(JSON.stringify({ type: 'cancel' }));
  }, [wsRef]);

  // TTS 音量：ref 暂存最新值，播放器未创建时先记账、创建时应用（见 getTTSPlayer）
  const ttsVolumeRef = useRef(1);
  const setTTSVolume = useCallback((volume: number) => {
    const clamped = Number.isFinite(volume) ? Math.min(1, Math.max(0, volume)) : 1;
    ttsVolumeRef.current = clamped;
    ttsPlayerRef.current?.setVolume(clamped);
  }, []);

  // 懒加载 TTS 流式播放器：首次收到 tts_chunk 时才创建 AudioContext。
  // 延迟创建避免无语音交互时占用音频资源，也符合浏览器自动播放策略（需用户手势）。
  const getTTSPlayer = useCallback((): TTSStreamPlayer => {
    if (!ttsPlayerRef.current) {
      ttsPlayerRef.current = new TTSStreamPlayer((playing) => {
        setIsTTSPlaying(playing);
        onTTSPlayingChangeRef.current?.(playing);
      });
      // 应用创建前暂存的音量设置（audioStore.ttsVolume）
      ttsPlayerRef.current.setVolume(ttsVolumeRef.current);
    }
    return ttsPlayerRef.current;
  }, []);
  // 注入到 ref，供 handleMessage（定义在 getTTSPlayer 之前）调用
  useEffect(() => {
    getTTSPlayerRef.current = getTTSPlayer;
  }, [getTTSPlayer]);

  const sendDualStream = useCallback(
    (payload: DualStreamPayload) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        onErrorRef.current?.('WebSocket is not connected');
        return;
      }
      // 复用 voice.dual_stream action，通过 payload.type 字段区分 init/audio/end
      wsRef.current.send(
        JSON.stringify({
          action: VoiceActions.DUAL_STREAM,
          data: payload,
        }),
      );
    },
    [wsRef],
  );

  const interruptTTS = useCallback(() => {
    // 全双工打断：立即停止 TTS 播放、清空音频队列
    ttsPlayerRef.current?.interrupt();
  }, []);

  // 口型同步分接：TTS 播放器懒创建，未播放过时返回 null（调用方逐帧重试）
  const getTTSAnalyser = useCallback((): AnalyserNode | null => {
    return ttsPlayerRef.current?.getAnalyser() ?? null;
  }, []);

  const sendRaw = useCallback(
    (data: object) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        return;
      }
      wsRef.current.send(JSON.stringify(data));
    },
    [wsRef],
  );

  // 组件卸载时释放 TTS 播放器音频资源
  useEffect(() => {
    return () => {
      ttsPlayerRef.current?.dispose();
      ttsPlayerRef.current = null;
    };
  }, []);

  // agentId 变更处理：
  // - 两个非空 agentId 之间切换 → transportReconnect()（发新 config）
  // - agentId 变为空 → transportDisconnect()（停止连接）
  // - 空→非空 → 由 transport 的 enabled-transition effect 自动 connect()，此处不干预避免双连
  useEffect(() => {
    const prevAgentId = agentIdRef.current;
    agentIdRef.current = agentId;

    if (prevAgentId !== agentId) {
      if (prevAgentId && agentId) {
        transportReconnect();
      } else if (!agentId) {
        transportDisconnect();
      }
    }
  }, [agentId, transportReconnect, transportDisconnect]);

  // offline-timeout 自定义事件监听
  useEffect(() => {
    const handleTimeoutChange = (e: Event) => {
      const customEvent = e as CustomEvent<string>;
      const newTimeout = parseInt(customEvent.detail, 10);
      if (!isNaN(newTimeout)) {
        setTimeoutState(newTimeout);
      }
    };

    window.addEventListener('offline-timeout-change', handleTimeoutChange);
    return () => {
      window.removeEventListener('offline-timeout-change', handleTimeoutChange);
    };
  }, []);

  // timeout 变更时同步 config 到服务端
  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'config',
          agent_id: agentIdRef.current,
          timeout,
        }),
      );
    }
  }, [timeout, wsRef]);

  return {
    isConnected,
    isGenerating,
    isTTSPlaying,
    sendMessage,
    cancelGeneration,
    disconnect,
    reconnect,
    sendDualStream,
    interruptTTS,
    sendRaw,
    getTTSAnalyser,
    setTTSVolume,
  };
}

export default useWebSocket;

/**
 * TTS 流式音频队列播放器：收到第一个 tts_chunk 立即播放，不等整句合成完成。
 *
 * 首包优先策略：第一个音频块到达即 schedule 到 currentTime，
 * 后续块严格 back-to-back 衔接（nextStartTime），既无间隙也无重叠。
 *
 * 解码策略：优先 decodeAudioData（可解 WAV/MP3）；
 * 失败则回退为 raw Int16 PCM @24kHz（裸 PCM 兜底）。
 */
class TTSStreamPlayer {
  private audioContext: AudioContext | null = null;
  private pending: { base64: string; isFinal: boolean }[] = [];
  private processing = false;
  private activeSources: AudioBufferSourceNode[] = [];
  private nextStartTime = 0;
  private isPlaying = false;
  // 单调代际号：interrupt()/dispose() 自增。用于让在途 await decode(base64) 的结果
  // 与 addQueue 判定失效——打断/释放后已 shift 的块不再 scheduleBuffer，且新旧
  // processQueue 不会各自消费 pending 造成双播。
  private generation = 0;
  private readonly onPlayingChange: (playing: boolean) => void;
  // TTS 输出采样率兜底值：默认 24000Hz；若后端裸 PCM 采样率不同需调整
  private readonly fallbackSampleRate = 24000;
  // 口型同步分接：source → analyser → gain → destination；AnalyserNode 只读分接不改变可听输出
  private analyser: AnalyserNode | null = null;
  // TTS 音量增益（audioStore.ttsVolume）：位于 analyser 下游，不影响口型频谱分析
  private gainNode: GainNode | null = null;
  private volume = 1;

  constructor(onPlayingChange: (playing: boolean) => void) {
    this.onPlayingChange = onPlayingChange;
  }

  private ensureContext(): AudioContext {
    if (!this.audioContext || this.audioContext.state === 'closed') {
      this.audioContext = new AudioContext();
    }
    // 用户手势触发后 context 可能仍处于 suspended，主动 resume 以降低首包延迟
    if (this.audioContext.state === 'suspended') {
      void this.audioContext.resume();
    }
    return this.audioContext;
  }

  private setPlaying(playing: boolean): void {
    if (this.isPlaying !== playing) {
      this.isPlaying = playing;
      this.onPlayingChange(playing);
    }
  }

  /** 解码 base64 音频为 AudioBuffer，保证乱序到达时仍按序播放 */
  private async decode(base64: string): Promise<AudioBuffer | null> {
    if (!base64) return null;
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const ctx = this.ensureContext();
    try {
      // 拷贝到独立 ArrayBuffer：decodeAudioData 会 detach 输入缓冲
      const copy = bytes.buffer.slice(0);
      return await ctx.decodeAudioData(copy);
    } catch {
      // 回退：按 raw 16-bit PCM 单声道处理
      return this.decodeRawInt16(bytes, ctx);
    }
  }

  private decodeRawInt16(bytes: Uint8Array, ctx: AudioContext): AudioBuffer {
    const sampleRate = this.fallbackSampleRate;
    const len = Math.floor(bytes.length / 2);
    const buf = ctx.createBuffer(1, len, sampleRate);
    const channel = buf.getChannelData(0);
    const view = new DataView(bytes.buffer);
    for (let i = 0; i < len; i++) {
      channel[i] = view.getInt16(i * 2, true) / 0x8000;
    }
    return buf;
  }

  /** 口型同步分接：懒创建分析节点（与 useAudioAnalyzer 默认参数同口径） */
  private ensureAnalyser(ctx: AudioContext): AnalyserNode {
    if (!this.analyser) {
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.8;
      this.gainNode = ctx.createGain();
      this.gainNode.gain.value = this.volume;
      this.analyser.connect(this.gainNode);
      this.gainNode.connect(ctx.destination);
    }
    return this.analyser;
  }

  /** 口型同步分接：暴露播放链上的分析节点（未播放过时为 null） */
  getAnalyser(): AnalyserNode | null {
    return this.analyser;
  }

  /** TTS 音量 0~1：增益节点未创建时先记账，创建时应用 */
  setVolume(volume: number): void {
    this.volume = volume;
    if (this.gainNode) {
      this.gainNode.gain.value = volume;
    }
  }

  private scheduleBuffer(buffer: AudioBuffer): void {
    const ctx = this.ensureContext();
    const now = ctx.currentTime;
    // 首包优先：无活跃播放时立即从当前时刻起播，不等后续块
    if (this.nextStartTime <= now && this.activeSources.length === 0) {
      this.nextStartTime = now;
    }
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ensureAnalyser(ctx));
    const startAt = Math.max(this.nextStartTime, now);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
    this.activeSources.push(source);
    this.setPlaying(true);

    source.onended = () => {
      this.activeSources = this.activeSources.filter((s) => s !== source);
      // 所有已调度源播放完毕且无待处理块时，标记停止
      if (this.activeSources.length === 0 && this.pending.length === 0 && !this.processing) {
        this.setPlaying(false);
        this.nextStartTime = 0;
      }
    };
  }

  private async processQueue(): Promise<void> {
    // 记录本队列的代际号：decode 是异步耗时操作，期间 interrupt()/dispose() 会自增
    // generation。decode 完成后校验代际，一旦不匹配说明已被打断/释放，丢弃结果不再
    // scheduleBuffer（避免卸载后重建 AudioContext 泄漏，也避免与新队列双双消费 pending）。
    const gen = this.generation;
    while (this.pending.length > 0) {
      const item = this.pending.shift();
      if (!item) break;
      const buffer = await this.decode(item.base64);
      if (gen !== this.generation) return;
      if (buffer) {
        this.scheduleBuffer(buffer);
      }
      // is_final 仅标记整句合成结束，播放由已调度源自然收尾
    }
    this.processing = false;
  }

  /** 入队一个 TTS 音频块：立即触发首包播放，后续块按序衔接 */
  enqueue(base64: string, isFinal: boolean): void {
    this.pending.push({ base64, isFinal });
    if (!this.processing) {
      this.processing = true;
      void this.processQueue();
    }
  }

  /** 全双工打断：立即停止所有播放、清空待处理队列 */
  interrupt(): void {
    // 使在途 decode 结果与新生成的队列全部失效
    this.generation += 1;
    for (const s of this.activeSources) {
      try {
        s.stop();
      } catch {
        // 源可能已自然结束，忽略
      }
    }
    this.activeSources = [];
    this.pending = [];
    this.processing = false;
    this.nextStartTime = 0;
    this.setPlaying(false);
  }

  /** 释放音频上下文资源 */
  dispose(): void {
    this.interrupt();
    if (this.audioContext && this.audioContext.state !== 'closed') {
      void this.audioContext.close();
    }
    this.audioContext = null;
    this.analyser = null;
  }
}
