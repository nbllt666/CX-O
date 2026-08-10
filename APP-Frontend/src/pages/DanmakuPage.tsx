/**
 * 弹幕窗页面（路由 /danmaku）：直播弹幕实时流。
 *
 * 组成：
 * - DanmakuToolbar：连接状态 + 暂停/清屏/置顶/背景不透明度/鼠标穿透/隐藏
 * - DanmakuList：弹幕滚动列表（danmakuFeed 状态机支撑暂停缓存、恢复补齐）
 *
 * 数据源：useLiveWebSocket 订阅 danmaku 事件；传输层自带指数退避重连，
 * 后端不可达时状态灯显示「未连接/重连中」，列表保留已有内容，不崩溃。
 *
 * 状态记忆（danmakuStore persist）：
 * - 置顶/背景不透明度/暂停滚动：本页挂载时直接应用持久化值；
 * - 显隐：窗口被创建即上报 visible=true，用户点「隐藏」置 false。
 *   重启后由主进程读取持久化 visible 决定是否创建弹幕窗——
 *   【IPC/主进程缺口】现有 window:toggle-danmaku 仅支持切换，主进程
 *   尚无启动时读取 cxo-pet-danmaku 存储并恢复窗口的逻辑，需主线程补充。
 *
 * 鼠标穿透：
 * - 会话内状态，刻意不持久化（重启默认关闭，防无恢复入口时窗口永久锁死）；
 * - 开启后窗口不可交互，恢复入口需主进程托盘菜单/全局快捷键支持（缺口同上）。
 *
 * 全局快捷键（Ctrl+Shift+D 唤起/隐藏弹幕窗）：
 * - globalShortcut 须在主进程注册，属 electron/ 改动，本任务不触碰，
 *   列为 IPC/主进程缺口，由主线程补上。
 */
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import DanmakuList from '@/components/danmaku/DanmakuList';
import DanmakuToolbar from '@/components/danmaku/DanmakuToolbar';
import type { DanmakuConnectionStatus } from '@/components/danmaku/DanmakuToolbar';
import {
  danmakuFeedReducer,
  initialDanmakuFeedState,
  toDanmakuItem,
} from '@/components/danmaku/danmakuFeed';
import { useLiveWebSocket } from '@/hooks/useLiveWebSocket';
import { useDanmakuStore } from '@/store/danmakuStore';

export default function DanmakuPage() {
  const paused = useDanmakuStore((s) => s.paused);
  const setPaused = useDanmakuStore((s) => s.setPaused);
  const alwaysOnTop = useDanmakuStore((s) => s.alwaysOnTop);
  const setAlwaysOnTop = useDanmakuStore((s) => s.setAlwaysOnTop);
  const backgroundOpacity = useDanmakuStore((s) => s.backgroundOpacity);
  const setBackgroundOpacity = useDanmakuStore((s) => s.setBackgroundOpacity);
  const setVisible = useDanmakuStore((s) => s.setVisible);

  const [feed, dispatch] = useReducer(danmakuFeedReducer, initialDanmakuFeedState);
  const [status, setStatus] = useState<DanmakuConnectionStatus>('connecting');
  // 鼠标穿透：会话内状态，不持久化（见文件头注释）
  const [clickThrough, setClickThrough] = useState(false);
  // 区分「未连接」与「重连中」：曾连接成功后断开才算重连
  const hasConnectedRef = useRef(false);
  // 弹幕 id 兜底序号（同毫秒防碰撞）
  const seqRef = useRef(0);

  // 窗口被创建/显示即视为用户希望其可见：上报记忆供重启恢复
  useEffect(() => {
    setVisible(true);
  }, [setVisible]);

  // 置顶：挂载时应用持久化值，后续切换即时同步主进程
  useEffect(() => {
    void window.electronAPI?.setAlwaysOnTop(alwaysOnTop);
  }, [alwaysOnTop]);

  // 鼠标穿透：ignore=true 完全穿透（主进程语义）；恢复时主进程带 forward 保留 hover 转发
  useEffect(() => {
    void window.electronAPI?.setIgnoreMouseEvents(clickThrough);
  }, [clickThrough]);

  useLiveWebSocket({
    onDanmaku: (data) => {
      const item = toDanmakuItem(data, Date.now(), seqRef.current++);
      if (!item) return;
      // 暂停时新弹幕进缓存不滚动；恢复后 flush 补齐。读 getState 保证取到最新值
      dispatch({ type: useDanmakuStore.getState().paused ? 'buffer' : 'append', item });
    },
    onConnect: () => {
      hasConnectedRef.current = true;
      setStatus('connected');
    },
    onDisconnect: () => {
      setStatus(hasConnectedRef.current ? 'reconnecting' : 'connecting');
    },
    onError: () => {
      setStatus(hasConnectedRef.current ? 'reconnecting' : 'connecting');
    },
  });

  const handleTogglePaused = useCallback(() => {
    const next = !paused;
    setPaused(next);
    // 恢复滚动：把暂停期缓存的弹幕一次性并入渲染队列
    if (!next) {
      dispatch({ type: 'flush' });
    }
  }, [paused, setPaused]);

  const handleClear = useCallback(() => {
    dispatch({ type: 'clear' });
  }, []);

  const handleToggleAlwaysOnTop = useCallback(() => {
    setAlwaysOnTop(!alwaysOnTop);
  }, [alwaysOnTop, setAlwaysOnTop]);

  const handleToggleClickThrough = useCallback(() => {
    setClickThrough((prev) => !prev);
  }, []);

  const handleHideWindow = useCallback(() => {
    // 用户主动隐藏：显隐记忆置 false，再经 IPC 切换窗口显隐
    setVisible(false);
    void window.electronAPI?.toggleDanmakuWindow();
  }, [setVisible]);

  return (
    <div className="flex h-full flex-col gap-2 bg-transparent p-2">
      <DanmakuToolbar
        status={status}
        paused={paused}
        alwaysOnTop={alwaysOnTop}
        clickThrough={clickThrough}
        backgroundOpacity={backgroundOpacity}
        onTogglePaused={handleTogglePaused}
        onClear={handleClear}
        onToggleAlwaysOnTop={handleToggleAlwaysOnTop}
        onToggleClickThrough={handleToggleClickThrough}
        onOpacityChange={setBackgroundOpacity}
        onHideWindow={handleHideWindow}
      />
      <DanmakuList
        items={feed.items}
        pendingCount={feed.pending.length}
        paused={paused}
        backgroundOpacity={backgroundOpacity}
      />
    </div>
  );
}
