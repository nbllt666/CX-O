import { useEffect, useRef, useCallback, useState } from 'react';

const WS_BASE_URL =
  import.meta.env.VITE_WS_URL ||
  (import.meta.env.VITE_API_URL || 'http://localhost:8100')
    .replace('http', 'ws')
    .replace(/\/ws$/, '')
    .replace(/\/$/, '');

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
  action?: string;
  status?: string;
  data?: {
    content?: string;
    [key: string]: unknown;
  };
  is_final?: boolean;
  chunk_index?: number;
}

export interface WebSocketOptions {
  agentId: string;
  timeout?: number;
  onMessage?: (data: WebSocketMessage) => void;
  onAlarm?: (message: string, triggeredAt: string) => void;
  onError?: (error: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
}

export interface UseWebSocketReturn {
  isConnected: boolean;
  isGenerating: boolean;
  sendMessage: (message: string, images?: string[]) => void;
  cancelGeneration: () => void;
  disconnect: () => void;
  reconnect: () => void;
}

export function useWebSocket(options: WebSocketOptions): UseWebSocketReturn {
  const agentId = options.agentId;
  const propTimeout = options.timeout;

  const getStoredTimeout = useCallback(() => {
    const stored = localStorage.getItem('cxhms-offline-timeout');
    return stored ? parseInt(stored, 10) : 60;
  }, []);

  const [timeout, setTimeoutState] = useState(propTimeout || getStoredTimeout());

  const wsRef = useRef<WebSocket | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const agentIdRef = useRef(agentId);
  const timeoutRef = useRef(timeout);

  const onMessageRef = useRef(options.onMessage);
  const onAlarmRef = useRef(options.onAlarm);
  const onErrorRef = useRef(options.onError);
  const onConnectRef = useRef(options.onConnect);
  const onDisconnectRef = useRef(options.onDisconnect);

  useEffect(() => {
    onMessageRef.current = options.onMessage;
    onAlarmRef.current = options.onAlarm;
    onErrorRef.current = options.onError;
    onConnectRef.current = options.onConnect;
    onDisconnectRef.current = options.onDisconnect;
  });

  useEffect(() => {
    timeoutRef.current = timeout;
  }, [timeout]);

  const clearPingInterval = useCallback(() => {
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current);
      pingIntervalRef.current = null;
    }
  }, []);

  const startPingInterval = useCallback(() => {
    clearPingInterval();
    pingIntervalRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
  }, [clearPingInterval]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    clearPingInterval();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, [clearPingInterval]);

  const connect = useCallback(() => {
    if (!agentIdRef.current) {
      return;
    }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const wsUrl = `${WS_BASE_URL}/ws`;
  console.log('[WebSocket] Connecting to:', wsUrl, 'with agent:', agentIdRef.current);
  const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setIsConnected(true);
      startPingInterval();
      onConnectRef.current?.();
    };

    ws.onclose = () => {
      setIsConnected(false);
      setIsGenerating(false);
      clearPingInterval();
      onDisconnectRef.current?.();
    };

    ws.onerror = (event) => {
      console.error('WebSocket error:', event);
      onErrorRef.current?.('WebSocket connection error');
    };

    ws.onmessage = (event) => {
      try {
        const data: WebSocketMessage = JSON.parse(event.data);

        switch (data.type) {
          case 'pong':
            break;
          case 'alarm':
            onAlarmRef.current?.(data.message || '', data.triggered_at || '');
            break;
          case 'stream':
            if (data.is_final) {
              setIsGenerating(false);
              onMessageRef.current?.({ type: 'done' });
            } else if (data.data?.content) {
              onMessageRef.current?.({ type: 'content', content: data.data.content });
            }
            break;
          case 'response':
            if (data.status === 'error') {
              setIsGenerating(false);
              onErrorRef.current?.(data.error?.message || 'Unknown error');
            }
            break;
          case 'error':
            setIsGenerating(false);
            onErrorRef.current?.(data.error?.message || data.error || 'Unknown error');
            break;
          case 'content':
          case 'tool_call':
          case 'tool_result':
            onMessageRef.current?.(data);
            break;
          case 'done':
            setIsGenerating(false);
            onMessageRef.current?.(data);
            break;
          case 'cancelled':
            setIsGenerating(false);
            onMessageRef.current?.(data);
            break;
          case 'thinking':
            onMessageRef.current?.(data);
            break;
          case 'tool_start':
            onMessageRef.current?.(data);
            break;
          default:
            onMessageRef.current?.(data);
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    wsRef.current = ws;
  }, [startPingInterval, clearPingInterval]);

  const reconnect = useCallback(() => {
    disconnect();
    window.setTimeout(connect, 100);
  }, [connect, disconnect]);

  const sendMessage = useCallback(
    (message: string, images?: string[]) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        onErrorRef.current?.('WebSocket is not connected');
        return;
      }

      setIsGenerating(true);
      const requestId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
      wsRef.current.send(
        JSON.stringify({
          action: 'chat.stream',
          request_id: requestId,
          data: {
            text: message,
            agent_id: agentIdRef.current,
            images: images && images.length > 0 ? images : undefined,
          },
        })
      );
    },
    []
  );

  const cancelGeneration = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    wsRef.current.send(JSON.stringify({ type: 'cancel' }));
  }, []);

  useEffect(() => {
    const prevAgentId = agentIdRef.current;
    agentIdRef.current = agentId;

    if (prevAgentId !== agentId) {
      if (wsRef.current) {
        disconnect();
      }
      if (agentId) {
        connect();
      }
    }
  }, [agentId, disconnect, connect]);

  useEffect(() => {
    connect();

    const handleTimeoutChange = (e: CustomEvent) => {
      const newTimeout = parseInt(e.detail, 10);
      if (!isNaN(newTimeout)) {
        setTimeoutState(newTimeout);
      }
    };

    window.addEventListener('offline-timeout-change', handleTimeoutChange as EventListener);

    return () => {
      disconnect();
      window.removeEventListener('offline-timeout-change', handleTimeoutChange as EventListener);
    };
  }, [connect, disconnect]);

  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'config',
          timeout,
        })
      );
    }
  }, [timeout]);

  return {
    isConnected,
    isGenerating,
    sendMessage,
    cancelGeneration,
    disconnect,
    reconnect,
  };
}

export default useWebSocket;
