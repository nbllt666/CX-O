/**
 * 字幕源页（SubTask 8.2，管理窗内路由 subtitle-source + 顶层 OBS 路由 /source/subtitle-source）
 *
 * 复用 SubtitleDisplay 组件：展示 AI 回复流（Live WS stream/response 事件）的逐字字幕。
 * 自包含 OBS 浏览器源：透明背景、1920×1080、字幕置底，无管理布局依赖。
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import SubtitleDisplay from '@/components/live/SubtitleDisplay';
import { useLiveWebSocket } from '@/hooks/useLiveWebSocket';

export default function SubtitleSourcePage() {
  const { t } = useTranslation();
  const [subtitleText, setSubtitleText] = useState('');

  useEffect(() => {
    document.body.style.background = 'transparent';
    document.documentElement.style.background = 'transparent';
    return () => {
      document.body.style.background = '';
      document.documentElement.style.background = '';
    };
  }, []);

  useLiveWebSocket({
    onStreamContent: (content) => setSubtitleText(content),
  });

  return (
    <div
      className="relative"
      style={{ backgroundColor: 'transparent', width: 1920, height: 1080 }}
    >
      {!subtitleText && (
        <div className="pointer-events-none absolute inset-x-0 bottom-40 flex justify-center text-lg text-white/30">
          {t('management.subtitleSource.placeholder')}
        </div>
      )}
      <SubtitleDisplay
        text={subtitleText}
        position="bottom"
        maxLines={3}
        fontSize={32}
        background="rgba(0,0,0,0.55)"
        typingSpeed={40}
      />
      <div className="pointer-events-none absolute bottom-3 right-4 rounded-md bg-black/30 px-2 py-0.5 text-[10px] text-white/50">
        {t('management.subtitleSource.obsHint')} · 1920×1080
      </div>
    </div>
  );
}
