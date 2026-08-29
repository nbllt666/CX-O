/**
 * 直播控制台页（SubTask 8.1，管理窗内路由 live-console）
 *
 * 功能口径对齐 CX-O-Frontend LivePage 的直播状态侧 + 本工程管理窗风格：
 * - 直播状态总览：Live WS 连接态（useLiveWebSocket）、后端健康（healthApi.getHealth）、
 *   直播客户端（healthApi.getLiveClientStatus，含 client_id）
 * - 推流信息：推流服务器地址（默认后端地址）+ 可编辑的推流密钥（localStorage 持久化），
 *   供 OBS 自定义推流使用；真实推流启停由编码器/后端完成，归 Task 10 实测
 * - 弹幕速率/统计：累计弹幕数 + 最近 60s 滚动窗口速率（消费 Live WS danmaku 事件）
 * - 控制操作：连接/断开（Live WS）、弹幕开关、清屏、断开直播客户端
 *
 * 优雅降级：healthApi 任一查询失败均以「状态查询失败」展示，不阻断页面其余功能。
 */
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  Eraser,
  MessageSquare,
  Play,
  Radio,
  RefreshCw,
  Square,
  Unplug,
} from 'lucide-react';
import { useLiveWebSocket } from '@/hooks/useLiveWebSocket';
import { healthApi } from '@/api/clients/health';
import { getApiBaseUrl } from '@/api/base';
import {
  danmakuFeedReducer,
  initialDanmakuFeedState,
  toDanmakuItem,
} from '@/components/danmaku/danmakuFeed';
import { cn } from '@/lib/utils';

/** 推流密钥 localStorage 持久化键 */
const STREAM_KEY_STORAGE = 'cxo-push-stream-key';
/** 弹幕速率滚动窗口（ms） */
const RATE_WINDOW_MS = 60_000;

interface LiveClientInfo {
  connected: boolean;
  clientId?: string;
}

export default function LiveConsolePage() {
  const { t } = useTranslation();

  // ── Live WS 连接态 + 弹幕事件 ──
  const [feed, dispatch] = useReducer(danmakuFeedReducer, initialDanmakuFeedState);
  const [danmakuOn, setDanmakuOn] = useState(true);
  // 供 WS 回调读取最新开关（避免 stale closure）
  const danmakuOnRef = useRef(danmakuOn);
  // 弹幕速率滚动窗口：记录最近弹幕接收时间戳
  const rateTimestampsRef = useRef<number[]>([]);
  const [rate, setRate] = useState(0);
  const seqRef = useRef(0);
  // 最近一次速率刷新
  const refreshRate = useCallback(() => {
    const now = Date.now();
    const windowStart = now - RATE_WINDOW_MS;
    const kept = rateTimestampsRef.current.filter((ts) => ts >= windowStart);
    rateTimestampsRef.current = kept;
    setRate(kept.length);
  }, []);

  useEffect(() => {
    const id = window.setInterval(refreshRate, 5000);
    return () => window.clearInterval(id);
  }, [refreshRate]);

  const { isConnected, disconnect, reconnect } = useLiveWebSocket({
    onDanmaku: (data) => {
      // 弹幕开关关闭时仍计数速率，但不入渲染队列（与弹幕窗语义一致）
      rateTimestampsRef.current.push(Date.now());
      if (!danmakuOnRef.current) return;
      const item = toDanmakuItem(data, Date.now(), seqRef.current++);
      if (item) dispatch({ type: 'append', item });
    },
  });

  useEffect(() => {
    danmakuOnRef.current = danmakuOn;
  }, [danmakuOn]);

  // ── Live WS 连接时长：就绪态以外的补充信息（每秒刷新，未连接显示 "--"）──
  const [connectedSince, setConnectedSince] = useState<number | null>(null);
  const [elapsedLabel, setElapsedLabel] = useState('--');
  useEffect(() => {
    if (isConnected) {
      // 建连时刻只在断开→连接的沿上记录，重渲染不重置
      setConnectedSince((prev) => prev ?? Date.now());
    } else {
      setConnectedSince(null);
      setElapsedLabel('--');
    }
  }, [isConnected]);
  useEffect(() => {
    if (connectedSince === null) return;
    const pad = (n: number) => String(n).padStart(2, '0');
    const tick = () => {
      const sec = Math.max(0, Math.floor((Date.now() - connectedSince) / 1000));
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      setElapsedLabel(h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`);
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [connectedSince]);

  // ── 后端健康 / 直播客户端状态 ──
  const [health, setHealth] = useState<{ status?: string; database?: string } | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [client, setClient] = useState<LiveClientInfo | null>(null);
  const [clientFailed, setClientFailed] = useState(false);
  const [disconnectFailed, setDisconnectFailed] = useState(false);

  const refreshBackend = useCallback(async () => {
    setHealthFailed(false);
    setClientFailed(false);
    try {
      const h = await healthApi.getHealth();
      setHealth({
        status: h.status,
        database: h.database?.status,
      });
    } catch {
      setHealthFailed(true);
      setHealth(null);
    }
    try {
      const raw = (await healthApi.getLiveClientStatus()) as unknown as {
        status?: string;
        connected?: boolean;
        client_id?: string;
      };
      setClient({
        connected: raw.connected ?? raw.status === 'connected',
        clientId: raw.client_id,
      });
    } catch {
      setClientFailed(true);
      setClient(null);
    }
  }, []);

  useEffect(() => {
    void refreshBackend();
  }, [refreshBackend]);

  // ── 推流信息（本地持久化密钥） ──
  const [streamKey, setStreamKey] = useState(() =>
    typeof window !== 'undefined' ? window.localStorage.getItem(STREAM_KEY_STORAGE) ?? '' : '',
  );
  const handleStreamKeyChange = (value: string) => {
    setStreamKey(value);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(STREAM_KEY_STORAGE, value);
    }
  };

  const handleClear = useCallback(() => {
    dispatch({ type: 'clear' });
    rateTimestampsRef.current = [];
    setRate(0);
  }, []);

  const handleDisconnectClient = useCallback(async () => {
    if (!client?.clientId) return;
    setDisconnectFailed(false);
    try {
      await healthApi.disconnectLiveClient(client.clientId);
      await refreshBackend();
    } catch {
      setDisconnectFailed(true);
    }
  }, [client, refreshBackend]);

  const statCard = (label: string, value: string, accent?: string) => (
    <div className="rounded-xl border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn('mt-1 text-2xl font-bold', accent)}>{value}</p>
    </div>
  );

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-5 overflow-y-auto p-1">
      {/* 页头 */}
      <div className="shrink-0">
        <h2 className="bg-gradient-to-r from-primary to-secondary bg-clip-text text-xl font-bold text-transparent">
          {t('management.liveConsole.title')}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t('management.liveConsole.subtitle')}
        </p>
      </div>

      {/* 直播状态总览 */}
      <section className="glass-panel shrink-0 space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Radio className="h-4 w-4 text-primary" />
          {t('management.liveConsole.overviewTitle')}
        </h3>

        {/* Live WS 连接态 */}
        <div className="flex flex-wrap gap-3">
          {statCard(
            t('management.liveConsole.liveWs'),
            isConnected
              ? t('management.liveConsole.wsConnected')
              : t('management.liveConsole.wsDisconnected'),
            isConnected ? 'text-emerald-400' : 'text-red-400',
          )}
          {/* 连接时长卡片：后端 /api/live/client/status 无在线数字段（仅 connected/client_id），
              原先与 Live WS 卡片逐字重复，改为展示本页 Live WS 的连接时长 */}
          {statCard(
            t('management.liveConsole.connectionDuration'),
            elapsedLabel,
            isConnected ? 'text-emerald-400' : 'text-muted-foreground',
          )}
          {statCard(
            t('management.liveConsole.backendHealth'),
            healthFailed
              ? t('management.liveConsole.loadFailed')
              : health?.status === 'ok'
                ? t('management.liveConsole.backendOk')
                : health?.status || t('management.liveConsole.loadFailed'),
            !healthFailed && health?.status === 'ok' ? 'text-emerald-400' : 'text-amber-400',
          )}
        </div>

        {/* 直播客户端状态 */}
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.04)] px-3 py-2">
          <span className="text-sm text-muted-foreground">
            {t('management.liveConsole.liveClient')}
          </span>
          {clientFailed ? (
            <span className="text-xs text-red-400">
              {t('management.liveConsole.loadFailed')}
            </span>
          ) : (
            <span
              className={cn(
                'flex items-center gap-1.5 text-xs font-medium',
                client?.connected ? 'text-emerald-400' : 'text-muted-foreground',
              )}
            >
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  client?.connected ? 'bg-emerald-400' : 'bg-[rgba(255,255,255,0.3)]',
                )}
              />
              {client?.connected
                ? t('management.liveConsole.liveClientConnected')
                : t('management.liveConsole.liveClientDisconnected')}
            </span>
          )}
          {client?.connected && client.clientId && (
            <>
              <span className="text-xs text-muted-foreground">
                {t('management.liveConsole.clientId')}: {client.clientId}
              </span>
              <button
                type="button"
                onClick={() => void handleDisconnectClient()}
                className="ml-auto flex items-center gap-1 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs text-red-400 transition-opacity hover:opacity-85"
              >
                <Unplug className="h-3 w-3" />
                {t('management.liveConsole.disconnectClient')}
              </button>
            </>
          )}
          {disconnectFailed && (
            <span className="text-xs text-red-400">
              {t('management.liveConsole.disconnectClientFailed')}
            </span>
          )}
        </div>
      </section>

      {/* 推流信息 */}
      <section className="glass-panel shrink-0 space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <Activity className="h-4 w-4 text-primary" />
          {t('management.liveConsole.pushInfoTitle')}
        </h3>
        <div className="space-y-3">
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">
              {t('management.liveConsole.pushServer')}
            </label>
            <input
              readOnly
              value={getApiBaseUrl()}
              aria-label={t('management.liveConsole.pushServer')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 font-mono text-xs backdrop-blur-sm"
            />
            <p className="text-xs text-muted-foreground/70">
              {t('management.liveConsole.pushServerHint')}
            </p>
          </div>
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">
              {t('management.liveConsole.streamKey')}
            </label>
            <input
              value={streamKey}
              onChange={(e) => handleStreamKeyChange(e.target.value)}
              placeholder="rtmp://stream.example.com/live / 密钥"
              aria-label={t('management.liveConsole.streamKey')}
              className="w-full rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-2 font-mono text-xs backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
            />
            <p className="text-xs text-muted-foreground/70">
              {t('management.liveConsole.streamKeyHint')}
            </p>
          </div>
        </div>
      </section>

      {/* 弹幕统计 */}
      <section className="glass-panel shrink-0 space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <MessageSquare className="h-4 w-4 text-secondary" />
          {t('management.liveConsole.statsTitle')}
        </h3>
        <div className="flex flex-wrap gap-3">
          {statCard(t('management.liveConsole.totalDanmaku'), String(feed.items.length), 'text-primary')}
          {statCard(t('management.liveConsole.ratePerMinute'), `${rate} /min`, 'text-secondary')}
        </div>
      </section>

      {/* 控制操作 */}
      <section className="glass-panel shrink-0 space-y-4 p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold">
          <RefreshCw className="h-4 w-4 text-accent" />
          {t('management.liveConsole.controlsTitle')}
        </h3>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => (isConnected ? disconnect() : reconnect())}
            className={cn(
              'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-opacity hover:opacity-90',
              isConnected
                ? 'bg-red-500/85 text-white'
                : 'bg-emerald-500/85 text-white',
            )}
          >
            {isConnected ? <Square className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            {isConnected
              ? t('management.liveConsole.disconnect')
              : t('management.liveConsole.connect')}
          </button>

          <button
            type="button"
            onClick={() => setDanmakuOn((v) => !v)}
            aria-pressed={danmakuOn}
            className={cn(
              'flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-opacity hover:opacity-90',
              danmakuOn ? 'bg-primary text-primary-foreground' : 'bg-[rgba(255,255,255,0.12)] text-muted-foreground',
            )}
          >
            {danmakuOn
              ? t('management.liveConsole.danmakuOn')
              : t('management.liveConsole.danmakuOff')}
          </button>

          <button
            type="button"
            onClick={handleClear}
            className="flex items-center gap-2 rounded-lg bg-[rgba(255,255,255,0.12)] px-4 py-2 text-sm font-medium text-muted-foreground transition-opacity hover:opacity-90"
          >
            <Eraser className="h-4 w-4" />
            {t('management.liveConsole.clear')}
          </button>
        </div>
      </section>
    </div>
  );
}
