/**
 * 直播 WebSocket 钩子（/ws/live）。
 *
 * 行为口径对齐 CX-O-Frontend useLiveWebSocket：
 * - 连接打开后发送 init（session_id）
 * - 指数退避自动重连（100/200/500/1000/2000ms）
 * - 消息路由：danmaku / stream / response / gift / enter / vad_status /
 *   asr_result / tts_sync / tts_tick / tts_end / external_event
 * - sendAudio 二进制上行（ArrayBuffer）
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { getWsBaseUrl } from '../api/base';
import { useWSTransport } from './ws/transport';

export interface LiveDanmakuData {
  id: string;
  content: string;
  username?: string;
  color?: string;
}

export interface TTSSyncData {
  playback_id: string;
  server_ts: number;
  text: string;
  duration: number;
}

export interface TTSTickData {
  playback_id: string;
  server_ts: number;
  position: number;
}

export interface TTSEndData {
  playback_id: string;
  server_ts: number;
}

export interface LiveMessage {
  type: string;
  data?: {
    content?: string;
    text?: string;
    status?: string;
    is_speaking?: boolean;
    speech_probability?: number;
    speech_duration_ms?: number;
    /** 声纹：注册说话人标识（=注册名，仅注册命中带） */
    speaker_id?: string;
    /** 声纹：注册说话人名（未注册/伪名 spk_N 不带） */
    speaker_name?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface UseLiveWebSocketOptions {
  sessionId?: string;
  onDanmaku?: (data: LiveDanmakuData) => void;
  onStreamContent?: (content: string) => void;
  onGift?: (data: Record<string, unknown>) => void;
  onEnter?: (data: Record<string, unknown>) => void;
  onVadStatus?: (data: {
    status: string;
    speech_duration_ms: number;
    speech_probability?: number;
  }) => void;
  onASRResult?: (data: { text: string; is_final: boolean; speakerName?: string }) => void;
  onTTSSync?: (data: TTSSyncData) => void;
  onTTSTick?: (data: TTSTickData) => void;
  onTTSEnd?: (data: TTSEndData) => void;
  onError?: (error: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onExternalEvent?: (data: { source: string; type: string; title: string; body: string }) => void;
}

export interface UseLiveWebSocketReturn {
  isConnected: boolean;
  sendMessage: (message: Record<string, unknown>) => void;
  sendAudio: (audioData: ArrayBuffer) => void;
  disconnect: () => void;
  reconnect: () => void;
  connectionCount: number;
}

export function useLiveWebSocket(options: UseLiveWebSocketOptions = {}): UseLiveWebSocketReturn {
  const {
    sessionId,
    onDanmaku,
    onStreamContent,
    onGift,
    onEnter,
    onVadStatus,
    onASRResult,
    onTTSSync,
    onTTSTick,
    onTTSEnd,
    onError,
    onConnect,
    onDisconnect,
    onExternalEvent,
  } = options;

  const [connectionCount, setConnectionCount] = useState(0);

  const sessionIdRef = useRef(sessionId);
  const onDanmakuRef = useRef(onDanmaku);
  const onStreamContentRef = useRef(onStreamContent);
  const onGiftRef = useRef(onGift);
  const onEnterRef = useRef(onEnter);
  const onVadStatusRef = useRef(onVadStatus);
  const onASRResultRef = useRef(onASRResult);
  const onTTSSyncRef = useRef(onTTSSync);
  const onTTSTickRef = useRef(onTTSTick);
  const onTTSEndRef = useRef(onTTSEnd);
  const onErrorRef = useRef(onError);
  const onConnectRef = useRef(onConnect);
  const onDisconnectRef = useRef(onDisconnect);
  const onExternalEventRef = useRef(onExternalEvent);

  useEffect(() => {
    sessionIdRef.current = sessionId;
    onDanmakuRef.current = onDanmaku;
    onStreamContentRef.current = onStreamContent;
    onGiftRef.current = onGift;
    onEnterRef.current = onEnter;
    onVadStatusRef.current = onVadStatus;
    onASRResultRef.current = onASRResult;
    onTTSSyncRef.current = onTTSSync;
    onTTSTickRef.current = onTTSTick;
    onTTSEndRef.current = onTTSEnd;
    onErrorRef.current = onError;
    onConnectRef.current = onConnect;
    onDisconnectRef.current = onDisconnect;
    onExternalEventRef.current = onExternalEvent;
  });

  // 消息路由：transport 不解析 JSON，caller 负责解析 + 路由。ArrayBuffer 消息忽略。
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      if (event.data instanceof ArrayBuffer) {
        return;
      }

      const data: LiveMessage = JSON.parse(event.data as string);

      switch (data.type) {
        case 'danmaku':
          if (data.data && onDanmakuRef.current) {
            onDanmakuRef.current(data.data as unknown as LiveDanmakuData);
          }
          break;
        case 'stream':
          if (data.data?.content && onStreamContentRef.current) {
            onStreamContentRef.current(data.data.content);
          }
          break;
        case 'response':
          if (data.data?.content && onStreamContentRef.current) {
            onStreamContentRef.current(data.data.content as string);
          }
          break;
        case 'gift':
          if (data.data && onGiftRef.current) {
            onGiftRef.current(data.data as unknown as Record<string, unknown>);
          }
          break;
        case 'enter':
          if (onEnterRef.current) {
            onEnterRef.current((data.data || {}) as unknown as Record<string, unknown>);
          }
          break;
        case 'vad_status':
          if (data.data && onVadStatusRef.current) {
            onVadStatusRef.current({
              status: String(data.data.status || ''),
              speech_duration_ms: Number(data.data.speech_duration_ms || 0),
              speech_probability: Number(data.data.speech_probability || 0),
            });
          }
          break;
        case 'asr_result':
          if (data.data && onASRResultRef.current) {
            // 终结判定用服务端显式字段（is_final/end），不再用 VAD 说话态（is_speaking）反推；
            // 两者均缺省时按「未终结」（中途结果）处理。
            const explicitFinal =
              typeof data.data.is_final === 'boolean' ? data.data.is_final : data.data.end === true;
            onASRResultRef.current({
              text: String(data.data.text || ''),
              is_final: explicitFinal,
              speakerName: (data.data.speaker_name as string) || '',
            });
          }
          break;
        case 'tts_sync':
          if (data.data && onTTSSyncRef.current) {
            onTTSSyncRef.current(data.data as unknown as TTSSyncData);
          }
          break;
        case 'tts_tick':
          if (data.data && onTTSTickRef.current) {
            onTTSTickRef.current(data.data as unknown as TTSTickData);
          }
          break;
        case 'tts_end':
          if (data.data && onTTSEndRef.current) {
            onTTSEndRef.current(data.data as unknown as TTSEndData);
          }
          break;
        case 'external_event':
          if (onExternalEventRef.current && data.data) {
            onExternalEventRef.current(
              data.data as { source: string; type: string; title: string; body: string },
            );
          }
          break;
        default:
          break;
      }
    } catch (e) {
      console.error('[LiveWS] Failed to parse message:', e);
    }
  }, []);

  // Transport：URL 构造 + 实例化 + 指数退避重连；业务逻辑经回调注入。
  const {
    wsRef,
    isConnected,
    disconnect: transportDisconnect,
    reconnect: transportReconnect,
  } = useWSTransport({
    urlBuilder: () => `${getWsBaseUrl()}/ws/live${sessionId ? `?session_id=${sessionId}` : ''}`,
    binaryType: 'arraybuffer',
    reconnect: { strategy: 'exponential', delays: [100, 200, 500, 1000, 2000] },
    onOpen: (ws) => {
      setConnectionCount((prev) => prev + 1);
      onConnectRef.current?.();
      ws.send(JSON.stringify({ type: 'init', data: { session_id: sessionIdRef.current } }));
    },
    onClose: () => {
      // 服务端主动关闭时清理（手动 disconnect 走 wrapper 的 cleanup）
      setConnectionCount((prev) => Math.max(0, prev - 1));
      onDisconnectRef.current?.();
    },
    onError: (error) => {
      console.error('[LiveWS] Error:', error);
      onErrorRef.current?.(error);
    },
    onMessage: handleMessage,
  });

  // 手动 disconnect：transport 会 null 化 onclose（防止自动重连），
  // 所以 onClose 回调不会触发，需在此显式清理业务状态。
  const disconnect = useCallback(() => {
    transportDisconnect();
  }, [transportDisconnect]);

  const reconnect = useCallback(() => {
    transportReconnect();
  }, [transportReconnect]);

  const sendMessage = useCallback(
    (message: Record<string, unknown>) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(message));
      } else {
        console.warn('[LiveWS] Cannot send: not connected');
      }
    },
    [wsRef],
  );

  const sendAudio = useCallback(
    (audioData: ArrayBuffer) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(audioData);
      }
    },
    [wsRef],
  );

  // sessionId 变更触发断开重连（urlBuilder ref 已由 transport 的 ref sync 更新）
  useEffect(() => {
    if (sessionIdRef.current !== sessionId) {
      sessionIdRef.current = sessionId;
      transportReconnect();
    }
  }, [sessionId, transportReconnect]);

  return {
    isConnected,
    sendMessage,
    sendAudio,
    disconnect,
    reconnect,
    connectionCount,
  };
}

export default useLiveWebSocket;
