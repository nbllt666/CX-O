/**
 * 直播分屏页（SubTask 8.2，管理窗内路由 live-overlay + 顶层 OBS 路由 /source/live-overlay）
 *
 * 分屏布局预览/组装：头像区（左 55%）+ 弹幕区（右）+ 字幕区（底部）+ 音频源状态区（左下）。
 * 复用既有渲染链路：PetAvatar（头像）、danmakuFeed + DanmakuList（弹幕）、
 * SubtitleDisplay（字幕）、audioStore（音频状态）。
 *
 * 双形态：
 * - 管理窗内（/live-overlay）：作为内容页预览，提供「预览背景 / 透明」切换；
 * - OBS 顶层路由（/source/live-overlay）：自包含、透明背景、1920×1080，无管理布局依赖，
 *   隐藏控制条以保持采集画面干净。
 */
import { useEffect, useReducer, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, Layers, MonitorPlay } from 'lucide-react';
import { PetAvatar } from '@/components/pet/PetAvatar';
import DanmakuList from '@/components/danmaku/DanmakuList';
import {
  danmakuFeedReducer,
  initialDanmakuFeedState,
  toDanmakuItem,
} from '@/components/danmaku/danmakuFeed';
import SubtitleDisplay from '@/components/live/SubtitleDisplay';
import { useLiveWebSocket } from '@/hooks/useLiveWebSocket';
import { useAudioStore } from '@/store/audioStore';
import { cn } from '@/lib/utils';

const CANVAS_W = 1920;
const CANVAS_H = 1080;
const DARK_PREVIEW_BG = '#14142b';

export default function LiveOverlayPage() {
  const { t } = useTranslation();
  // OBS 独立加载时隐藏管理控制条；由 URL hash 判定（/source/live-overlay）
  const standalone = typeof window !== 'undefined' && window.location.hash.startsWith('#/source/');
  const [previewBg, setPreviewBg] = useState(!standalone);

  const [feed, dispatch] = useReducer(danmakuFeedReducer, initialDanmakuFeedState);
  const [subtitleText, setSubtitleText] = useState('');
  const seqRef = useRef(0);

  const ttsVolume = useAudioStore((s) => s.ttsVolume);
  const micEnabled = useAudioStore((s) => s.micEnabled);

  // OBS 独立加载：根与 body 透明
  useEffect(() => {
    if (!standalone) return;
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, [standalone]);

  useLiveWebSocket({
    onDanmaku: (data) => {
      const item = toDanmakuItem(data, Date.now(), seqRef.current++);
      if (item) dispatch({ type: 'append', item });
    },
    onStreamContent: (content) => setSubtitleText(content),
  });

  return (
    <div
      className="relative overflow-hidden"
      style={{
        backgroundColor: previewBg ? DARK_PREVIEW_BG : 'transparent',
        width: CANVAS_W,
        height: CANVAS_H,
      }}
    >
      {/* 顶部控制条（管理窗预览时显示；OBS 独立加载隐藏） */}
      {!standalone && (
        <div className="absolute left-3 top-3 z-30 flex items-center gap-2">
          <span className="glass-panel flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground">
            <MonitorPlay className="h-3.5 w-3.5 text-primary" />
            {t('management.liveOverlay.title')}
          </span>
          <button
            type="button"
            onClick={() => setPreviewBg((v) => !v)}
            className="glass-panel flex items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            {previewBg ? <Eye className="h-3.5 w-3.5" /> : <Layers className="h-3.5 w-3.5" />}
            {previewBg
              ? t('management.liveOverlay.bgPreview')
              : t('management.liveOverlay.bgTransparent')}
          </button>
        </div>
      )}

      {/* 主体：左头像 + 右弹幕 */}
      <div className="absolute inset-0 flex">
        {/* 头像区（左 55%） */}
        <div className="relative" style={{ width: '55%', height: '100%' }}>
          <PetAvatar />
          <span className="pointer-events-none absolute left-3 top-3 rounded-md bg-black/25 px-2 py-0.5 text-[10px] text-white/60">
            {t('management.liveOverlay.avatarZone')}
          </span>
        </div>

        {/* 弹幕区（右 45%） */}
        <div className="relative flex flex-col p-4" style={{ width: '45%', height: '100%' }}>
          <span className="pointer-events-none absolute right-3 top-2 rounded-md bg-black/25 px-2 py-0.5 text-[10px] text-white/60">
            {t('management.liveOverlay.danmakuZone')}
          </span>
          <div className="mt-4 min-h-0 flex-1">
            <DanmakuList
              items={feed.items}
              pendingCount={feed.pending.length}
              paused={false}
              backgroundOpacity={1}
            />
          </div>
        </div>
      </div>

      {/* 音频源状态区（左下角） */}
      <div className="absolute bottom-4 left-4 z-20 rounded-xl border border-[var(--glass-border)] bg-black/35 px-4 py-2.5 backdrop-blur-md">
        <p className="mb-1 text-[10px] text-white/50">{t('management.liveOverlay.audioZone')}</p>
        <div className="flex items-center gap-3 text-xs text-white/85">
          <span className="flex items-center gap-1.5">
            <span
              className={cn('h-2 w-2 rounded-full', micEnabled ? 'bg-emerald-400' : 'bg-white/25')}
            />
            {micEnabled ? t('management.audioSource.micOn') : t('management.audioSource.micOff')}
          </span>
          <span>{t('management.audioSource.ttsVolume')}: {Math.round(ttsVolume * 100)}%</span>
        </div>
      </div>

      {/* 字幕区（底部居中） */}
      <SubtitleDisplay
        text={subtitleText}
        position="bottom"
        maxLines={2}
        fontSize={30}
        background="rgba(0,0,0,0.55)"
        typingSpeed={40}
      />

      {/* OBS 独立加载：底部来源提示 */}
      {standalone && (
        <div className="pointer-events-none absolute bottom-3 right-4 z-20 rounded-md bg-black/30 px-2 py-0.5 text-[10px] text-white/50">
          {t('management.liveOverlay.obsHint')} · 1920×1080
        </div>
      )}
    </div>
  );
}
