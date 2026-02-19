import { useEffect, useRef, useCallback, useState } from 'react';

const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8100/ws';

// Gateway Protocol Types
export type WSMessageType = 'request' | 'response' | 'stream' | 'error' | 'ping' | 'pong';

export interface WSMessage {
  type: WSMessageType;
  request_id: string;
  action?: string;
  data?: Record<string, unknown>;
  status?: string;
  error?: { code: string; message: string };
  chunk_index?: number;
  is_final?: boolean;
  timestamp?: number;
}

export interface WebSocketMessage {
  type: string;
  content?: string;
  message?: string;
  done?: boolean;
  error?: string;
  session_id?: string;
  tool_call?: Record<string, unknown>;
  tool_name?: string;
  result?: unknown;
  triggered_at?: string;
  // Gateway protocol fields
  request_id?: string;
  action?: string;
  data?: Record<string, unknown>;
  status?: string;
  chunk_index?: number;
  is_final?: boolean;
  timestamp?: number;
}

export interface WebSocketOptions {
  agentId?: string;
  timeout?: number;
  onMessage?: (data: WebSocketMessage) => void;
  onAlarm?: (message: string, triggeredAt: string) => void;
  onError?: (error: string) => void;
  onConnect?: () => void;
  onDisconnect?: () => void;
  // Gateway protocol callbacks
  onResponse?: (message: WSMessage) => void;
  onStream?: (message: WSMessage) => void;
  onGatewayError?: (message: WSMessage) => void;
}

export interface UseWebSocketReturn {
  isConnected: boolean;
  isGenerating: boolean;
  sendMessage: (message: string, images?: string[]) => void;
  cancelGeneration: () => void;
  disconnect: () => void;
  reconnect: () => void;
  // Gateway protocol methods
  sendRequest: (action: string, data?: Record<string, unknown>) => string;
  sendPing: () => void;
  sendPong: () => void;
}

// Generate unique request ID
const generateRequestId = (): string => {
  return `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
};

export function useWebSocket(options: WebSocketOptions): UseWebSocketReturn {
  const {
    agentId,
    timeout: propTimeout,
    onMessage,
    onAlarm,
    onError,
    onConnect,
    onDisconnect,
    onResponse,
    onStream,
    onGatewayError,
  } = options;

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
        sendPing();
      }
    }, 30000);
  }, [clearPingInterval]);

  // Send ping message (Gateway protocol)
  const sendPing = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const pingMessage: WSMessage = {
        type: 'ping',
        request_id: generateRequestId(),
        timestamp: Date.now(),
      };
      wsRef.current.send(JSON.stringify(pingMessage));
    }
  }, []);

  // Send pong message (Gateway protocol)
  const sendPong = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const pongMessage: WSMessage = {
        type: 'pong',
        request_id: generateRequestId(),
        timestamp: Date.now(),
      };
      wsRef.current.send(JSON.stringify(pongMessage));
    }
  }, []);

  // Send request message (Gateway protocol)
  const sendRequest = useCallback(
    (action: string, data?: Record<string, unknown>): string => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        onError?.('WebSocket is not connected');
        return '';
      }

      const requestId = generateRequestId();
      const requestMessage: WSMessage = {
        type: 'request',
        request_id: requestId,
        action,
        data: data || {},
        timestamp: Date.now(),
      };
      wsRef.current.send(JSON.stringify(requestMessage));
      return requestId;
    },
    [onError]
  );

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    // Use Gateway WebSocket URL format
    const wsUrl = agentId
      ? `${WS_BASE_URL}?agent_id=${agentId}&timeout=${timeout}`
      : `${WS_BASE_URL}?timeout=${timeout}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setIsConnected(true);
      startPingInterval();
      onConnect?.();
    };

    ws.onclose = () => {
      setIsConnected(false);
      setIsGenerating(false);
      clearPingInterval();
      onDisconnect?.();
    };

    ws.onerror = (event) => {
      console.error('WebSocket error:', event);
      onError?.('WebSocket connection error');
    };

    ws.onmessage = (event) => {
      try {
        const data: WSMessage = JSON.parse(event.data);

        // Handle Gateway protocol message types
        switch (data.type) {
          case 'pong':
            // Pong received, connection is alive
            break;
          case 'ping':
            // Respond with pong
            sendPong();
            break;
          case 'response':
            onResponse?.(data);
            // Also call onMessage for backward compatibility
            onMessage?.({
              type: data.type,
              request_id: data.request_id,
              action: data.action,
              data: data.data,
              status: data.status,
              timestamp: data.timestamp,
            });
            break;
          case 'stream':
            onStream?.(data);
            // Also call onMessage for backward compatibility
            onMessage?.({
              type: data.type,
              request_id: data.request_id,
              action: data.action,
              data: data.data,
              chunk_index: data.chunk_index,
              is_final: data.is_final,
              timestamp: data.timestamp,
            });
            if (data.is_final) {
              setIsGenerating(false);
            }
            break;
          case 'error':
            onGatewayError?.(data);
            setIsGenerating(false);
            onError?.(data.error?.message || 'Gateway error');
            break;
          // Legacy message types for backward compatibility
          case 'alarm':
            onAlarm?.(data.data?.message as string || '', data.data?.triggered_at as string || '');
            break;
          case 'content':
          case 'tool_call':
          case 'tool_result':
            onMessage?.(data as unknown as WebSocketMessage);
            break;
          case 'done':
            setIsGenerating(false);
            onMessage?.(data as unknown as WebSocketMessage);
            break;
          case 'cancelled':
            setIsGenerating(false);
            onMessage?.(data as unknown as WebSocketMessage);
            break;
          default:
            onMessage?.(data as unknown as WebSocketMessage);
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    wsRef.current = ws;
  }, [
    agentId,
    timeout,
    onMessage,
    onAlarm,
    onError,
    onConnect,
    onDisconnect,
    onResponse,
    onStream,
    onGatewayError,
    startPingInterval,
    clearPingInterval,
    sendPong,
  ]);

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

  const reconnect = useCallback(() => {
    disconnect();
    window.setTimeout(connect, 100);
  }, [connect, disconnect]);

  const sendMessage = useCallback(
    (message: string, images?: string[]) => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        onError?.('WebSocket is not connected');
        return;
      }

      setIsGenerating(true);
      // Use Gateway protocol request format
      const requestId = generateRequestId();
      const requestMessage: WSMessage = {
        type: 'request',
        request_id: requestId,
        action: 'chat.send',
        data: {
          message,
          images: images && images.length > 0 ? images : undefined,
          agent_id: agentId || 'default',
        },
        timestamp: Date.now(),
      };
      wsRef.current.send(JSON.stringify(requestMessage));
    },
    [onError, agentId]
  );

  const cancelGeneration = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    // Use Gateway protocol to cancel
    const requestId = generateRequestId();
    const cancelMessage: WSMessage = {
      type: 'request',
      request_id: requestId,
      action: 'chat.cancel',
      data: {},
      timestamp: Date.now(),
    };
    wsRef.current.send(JSON.stringify(cancelMessage));
  }, []);

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
      // Send config update via Gateway protocol
      const requestId = generateRequestId();
      const configMessage: WSMessage = {
        type: 'request',
        request_id: requestId,
        action: 'config.update',
        data: { timeout },
        timestamp: Date.now(),
      };
      wsRef.current.send(JSON.stringify(configMessage));
    }
  }, [timeout]);

  return {
    isConnected,
    isGenerating,
    sendMessage,
    cancelGeneration,
    disconnect,
    reconnect,
    // Gateway protocol methods
    sendRequest,
    sendPing,
    sendPong,
  };
}

export default useWebSocket;
