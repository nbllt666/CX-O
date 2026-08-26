/**
 * WebSocket 传输层公共工厂。
 *
 * useWebSocket / useLiveWebSocket 的共同传输逻辑：
 * - URL 构造 + WebSocket 实例化
 * - connect/disconnect/reconnect 生命周期
 * - ref 同步 caller-provided 回调（避免 stale closure）
 * - 可选自动重连：none / fixed / exponential backoff
 * - send 返回 boolean 让 caller 决定如何处理未连接场景
 *
 * 不负责：
 * - 消息路由（caller 在 onMessage 里自行 switch/case）
 * - 心跳 ping（caller 在 onOpen 里启动自己的 ping interval）
 * - 业务初始化消息（caller 在 onOpen 里发自己的 init/config）
 * - connectionCount 等业务状态（caller 自行维护）
 *
 * 手动 disconnect 时 null 化 onclose 用于防止自动重连钩子——
 * 原生 ws.close() 不会同步触发 onclose（浏览器在下一个事件循环才触发），
 * 因此 manual disconnect 不会触发 onClose 回调，这是预期行为。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { MutableRefObject } from 'react';

export type WsUrlBuilder = () => string;

export type ReconnectStrategy =
  | { strategy: 'none' }
  | { strategy: 'fixed'; delay: number }
  | { strategy: 'exponential'; delays: number[] };

export interface UseWSTransportOptions {
  urlBuilder: WsUrlBuilder;
  binaryType?: 'arraybuffer' | 'blob';
  reconnect?: ReconnectStrategy;
  /** false 时 transport 不在 mount 时自动连接；之后翻转为 true 才连接。默认 true */
  enabled?: boolean;
  onOpen?: (ws: WebSocket) => void;
  onClose?: () => void;
  onError?: (error: string) => void;
  onMessage?: (event: MessageEvent) => void;
}

export interface UseWSTransportReturn {
  wsRef: MutableRefObject<WebSocket | null>;
  isConnected: boolean;
  connect: () => void;
  disconnect: () => void;
  reconnect: () => void;
  send: (data: string | ArrayBuffer) => boolean;
}

export function useWSTransport(options: UseWSTransportOptions): UseWSTransportReturn {
  const {
    urlBuilder,
    binaryType = 'arraybuffer',
    reconnect: reconnectStrategy = { strategy: 'none' },
    enabled = true,
    onOpen,
    onClose,
    onError,
    onMessage,
  } = options;

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const isUnmountedRef = useRef(false);
  const [isConnected, setIsConnected] = useState(false);

  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);
  const onMessageRef = useRef(onMessage);

  useEffect(() => {
    onOpenRef.current = onOpen;
    onCloseRef.current = onClose;
    onErrorRef.current = onError;
    onMessageRef.current = onMessage;
  });

  const urlBuilderRef = useRef(urlBuilder);
  const binaryTypeRef = useRef(binaryType);
  const reconnectRef = useRef(reconnectStrategy);
  const enabledRef = useRef(enabled);

  useEffect(() => {
    urlBuilderRef.current = urlBuilder;
    binaryTypeRef.current = binaryType;
    reconnectRef.current = reconnectStrategy;
    enabledRef.current = enabled;
  });

  const getReconnectDelay = useCallback((): number | null => {
    const r = reconnectRef.current;
    if (r.strategy === 'none') return null;
    if (r.strategy === 'fixed') return r.delay;
    // 防御空数组：r.delays[-1] 会返回 undefined（undefined!==null → ~0ms 重连风暴），回退安全默认
    if (r.delays.length === 0) return 1000;
    const idx = Math.min(reconnectAttemptsRef.current, r.delays.length - 1);
    return r.delays[idx];
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      // null 化 onclose 防止 manual disconnect 触发自动重连
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current !== null && wsRef.current.readyState === WebSocket.OPEN) return;

    const url = urlBuilderRef.current();
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.binaryType = binaryTypeRef.current;

      ws.onopen = () => {
        if (isUnmountedRef.current) return;
        setIsConnected(true);
        reconnectAttemptsRef.current = 0;
        onOpenRef.current?.(ws);
      };

      ws.onclose = () => {
        if (isUnmountedRef.current) return;
        setIsConnected(false);
        onCloseRef.current?.();

        const delay = getReconnectDelay();
        if (delay !== null) {
          reconnectAttemptsRef.current++;
          reconnectTimeoutRef.current = window.setTimeout(connect, delay);
        }
      };

      ws.onerror = () => {
        if (isUnmountedRef.current) return;
        onErrorRef.current?.('WebSocket connection error');
      };

      ws.onmessage = (event) => {
        if (isUnmountedRef.current) return;
        onMessageRef.current?.(event);
      };
    } catch (e) {
      console.error('[WSTransport] Failed to create WebSocket:', e);
      onErrorRef.current?.('Failed to create WebSocket connection');
    }
  }, [getReconnectDelay]);

  const reconnect = useCallback(() => {
    disconnect();
    reconnectAttemptsRef.current = 0;
    // 不复位 isUnmountedRef：卸载后不得再重连（复位会破坏卸载防护，卸载后仍触发连接）
    reconnectTimeoutRef.current = window.setTimeout(connect, 50);
  }, [disconnect, connect]);

  const send = useCallback((data: string | ArrayBuffer): boolean => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
      return true;
    }
    return false;
  }, []);

  // Mount/unmount：enabled 时自动连接；卸载时总是断开。
  // enabledRef.current 作为初始连接闸门——caller 可传 `enabled: !!agentId`
  // 避免空 agentId 时连接。
  useEffect(() => {
    isUnmountedRef.current = false;
    if (enabledRef.current) {
      connect();
    }
    return () => {
      isUnmountedRef.current = true;
      disconnect();
    };
  }, [connect, disconnect]);

  // enabled false→true 转换：未连接时连接。
  //（true→false 不自动断开；caller 显式控制 disconnect。）
  useEffect(() => {
    if (enabled && wsRef.current === null && !isUnmountedRef.current) {
      connect();
    }
  }, [enabled, connect]);

  return {
    wsRef,
    isConnected,
    connect,
    disconnect,
    reconnect,
    send,
  };
}
