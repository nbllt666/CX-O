/**
 * 弹幕源页（SubTask 8.2，管理窗内路由 danmaku-source + 顶层 OBS 路由 /source/danmaku-source）
 *
 * 复用弹幕流链路：danmakuFeedReducer（暂停缓存/清屏）+ DanmakuList 渲染 + useLiveWebSocket
 * 订阅 danmaku 事件。自包含 OBS 浏览器源：透明背景、1920×1080，无管理布局依赖。
 */
import { useEffect, useReducer, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import DanmakuList from '@/components/danmaku/DanmakuList';
import {
  danmakuFeedReducer,
  initialDanmakuFeedState,
  toDanmakuItem,
} from '@/components/danmaku/danmakuFeed';
import { useLiveWebSocket } from '@/hooks/useLiveWebSocket';

export default function DanmakuSourcePage() {
  const { t } = useTranslation();
  const [feed, dispatch] = useReducer(danmakuFeedReducer, initialDanmakuFeedState);
  const seqRef = useRef(0);

  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  useLiveWebSocket({
    onDanmaku: (data) => {
      const item = toDanmakuItem(data, Date.now(), seqRef.current++);
      if (item) dispatch({ type: 'append', item });
    },
  });

  return (
    <div
      className="relative overflow-hidden"
      style={{ backgroundColor: 'transparent', width: 1920, height: 1080 }}
    >
      <div className="absolute inset-0 flex flex-col p-6">
        <DanmakuList
          items={feed.items}
          pendingCount={feed.pending.length}
          paused={false}
          backgroundOpacity={1}
        />
      </div>
      <div className="pointer-events-none absolute bottom-3 right-4 rounded-md bg-black/30 px-2 py-0.5 text-[10px] text-white/50">
        {t('management.danmakuSource.obsHint')} · 1920×1080
      </div>
    </div>
  );
}
