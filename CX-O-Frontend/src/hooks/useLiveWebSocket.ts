import { useEffect, useRef, useCallback, useState } from 'react';

const WS_BASE_URL =
  import.meta.env.VITE_WS_URL ||
  (import.meta.env.VITE_API_URL || 'http://localhost:8100')
    .replace('http', 'ws')
    .replace(/\/ws$/, '')
    .replace(/\/$/, '');

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
  onVadStatus?: (data: { status: string; speech_duration_ms: number; speech_probability?: number }) => void;
  onASRResult?: (data: { text: string; is_final: boolean }) => void;
  onTTSSync?: (data: TTSSyncData) => void;
  onTTSTick?: (data: TTSTickData) => void;
  onTTSEnd?: (data: TTSEndData) => void;
  onError?: (error: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
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
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionCount, setConnectionCount] = useState(0);

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

  useEffect(() => {
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
  });

  const RECONNECT_DELAYS = [100, 200, 500, 1000, 2000];

  const getReconnectDelay = useCallback(() => {
    const idx = Math.min(reconnectAttemptsRef.current, RECONNECT_DELAYS.length - 1);
    return RECONNECT_DELAYS[idx];
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const url = `${WS_BASE_URL}/ws/live${sessionId ? `?session_id=${sessionId}` : ''}`;
    console.log('[LiveWS] Connecting to:', url);

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        console.log('[LiveWS] Connected');
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        setConnectionCount((prev) => prev + 1);
        onConnectRef.current?.();

        ws.send(JSON.stringify({ type: 'init', data: { session_id: sessionId } }));
      };

      ws.onclose = () => {
        console.log('[LiveWS] Disconnected');
        setIsConnected(false);
        onDisconnectRef.current?.();

        const delay = getReconnectDelay();
        reconnectAttemptsRef.current++;
        console.log(`[LiveWS] Reconnecting in ${delay}ms (attempt ${reconnectAttemptsRef.current})`);
        reconnectTimeoutRef.current = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        console.error('[LiveWS] Error');
        onErrorRef.current?.('WebSocket connection error');
      };

      ws.onmessage = (event) => {
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
                });
              }
              break;
            case 'asr_result':
              if (data.data && onASRResultRef.current) {
                onASRResultRef.current({
                  text: String(data.data.text || ''),
                  is_final: Boolean(!data.data.is_speaking),
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
            default:
              break;
          }
        } catch (e) {
          console.error('[LiveWS] Failed to parse message:', e);
        }
      };
    } catch (e) {
      console.error('[LiveWS] Failed to create WebSocket:', e);
      onErrorRef.current?.('Failed to create WebSocket connection');
    }
  }, [sessionId, getReconnectDelay]);

  const sendMessage = useCallback(
    (message: Record<string, unknown>) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(message));
      } else {
        console.warn('[LiveWS] Cannot send: not connected');
      }
    },
    []
  );

  const sendAudio = useCallback((audioData: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(audioData);
    }
  }, []);

  const reconnect = useCallback(() => {
    disconnect();
    reconnectAttemptsRef.current = 0;
    setTimeout(connect, 50);
  }, [disconnect, connect]);

  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

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
