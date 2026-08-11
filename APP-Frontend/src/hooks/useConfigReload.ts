/**
 * 配置热更新订阅钩子——连接后端 /ws，监听 `config_changed` 事件并广播到事件总线。
 *
 * 独立于聊天 useWebSocket：管理界面并非始终停留在 ChatPage，需要一条常驻的
 * 轻量连接来接收配置变更通知。fixed 2s 自动重连覆盖网络抖动与后端重启。
 */
import { useEffect, useRef, useState } from 'react';
import { getWsBaseUrl } from '../api/base';
import { emitConfigChanged } from '../lib/configEvents';

interface UseConfigReloadReturn {
  isConnected: boolean;
}

export function useConfigReload(): UseConfigReloadReturn {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;

    const connect = () => {
      if (unmountedRef.current) return;
      let ws: WebSocket;
      try {
        ws = new WebSocket(`${getWsBaseUrl()}/ws`);
      } catch (e) {
        console.error('[configReload] WS 创建失败:', e);
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        if (unmountedRef.current) return;
        setIsConnected(true);
      };

      ws.onmessage = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data as string) as {
            event?: string;
            data?: { section?: string; requires_restart?: boolean };
          };
          if (data.event === 'config_changed' && data.data?.section) {
            emitConfigChanged({
              section: data.data.section,
              requiresRestart: !!data.data.requires_restart,
            });
          }
        } catch {
          // 非 JSON 或非配置事件，忽略
        }
      };

      ws.onclose = () => {
        if (unmountedRef.current) return;
        setIsConnected(false);
        scheduleReconnect();
      };

      ws.onerror = () => {
        // onclose 会触发重连，此处仅记录
      };
    };

    const scheduleReconnect = () => {
      if (unmountedRef.current) return;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = setTimeout(connect, 2000);
    };

    connect();

    return () => {
      unmountedRef.current = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  return { isConnected };
}

export default useConfigReload;