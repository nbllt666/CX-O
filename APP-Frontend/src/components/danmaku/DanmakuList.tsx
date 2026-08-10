/**
 * 弹幕滚动列表：时间戳 + 昵称 + 内容，新弹幕自动滚到底。
 *
 * 视觉结构：背景玻璃层（不透明度独立可调）与文字层分离，
 * 避免调节窗口透明度时文字一并变淡。
 *
 * 滚动口径：paused=false 时 items 变化即滚到底；paused=true 时
 * 新弹幕在 reducer 层进缓存（见 danmakuFeed.ts），列表本身不更新，
 * 恢复后由 flush 一次性补齐并触发滚动。
 */
import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import type { DanmakuItem } from './danmakuFeed';

interface DanmakuListProps {
  items: DanmakuItem[];
  /** 暂停期缓存条数（用于角标提示） */
  pendingCount: number;
  paused: boolean;
  /** 背景玻璃层不透明度 0.1~1 */
  backgroundOpacity: number;
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false });
}

export default function DanmakuList({
  items,
  pendingCount,
  paused,
  backgroundOpacity,
}: DanmakuListProps) {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);

  // 新弹幕到达（或恢复滚动 flush）后自动滚到底；暂停期不滚动
  useEffect(() => {
    if (paused) return;
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [items.length, paused]);

  return (
    <div className="relative min-h-0 flex-1">
      {/* 背景玻璃层：opacity 仅作用于本层，文字保持全亮 */}
      <div
        aria-hidden
        className="absolute inset-0 rounded-xl"
        style={{
          background: 'var(--glass-bg-strong)',
          border: '1px solid var(--glass-border)',
          boxShadow: 'var(--glass-shadow)',
          backdropFilter: 'blur(var(--glass-blur)) saturate(1.4)',
          WebkitBackdropFilter: 'blur(var(--glass-blur)) saturate(1.4)',
          opacity: backgroundOpacity,
        }}
      />

      {/* 弹幕文字层 */}
      <div ref={scrollRef} className="absolute inset-0 overflow-y-auto px-3 py-2">
        {items.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
            {t('danmaku.empty')}
          </div>
        ) : (
          items.map((item) => (
            <div key={item.id} className="flex items-baseline gap-2 py-0.5 text-sm leading-5">
              <span className="shrink-0 text-[10px] text-muted-foreground">
                {formatTime(item.ts)}
              </span>
              <span
                className="shrink-0 font-medium"
                style={{ color: item.color || 'var(--color-accent)' }}
              >
                {item.username || t('danmaku.anonymous')}
              </span>
              <span className="min-w-0 break-all text-foreground">{item.content}</span>
            </div>
          ))
        )}
      </div>

      {/* 暂停角标：提示缓存中的弹幕条数 */}
      {paused && (
        <div className="glass-panel absolute bottom-2 right-2 px-2 py-0.5 text-[10px] text-muted-foreground">
          {t('danmaku.pausedBuffer', { count: pendingCount })}
        </div>
      )}
    </div>
  );
}
