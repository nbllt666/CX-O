/**
 * 弹幕窗工具条：连接状态指示 + 窗口/滚动控制。
 *
 * 拖拽：整条工具条为无边框窗口的拖拽区（CSS -webkit-app-region: drag，
 * Electron 原生支持，浏览器开发模式下该属性被忽略无副作用）；
 * 所有可交互控件逐个标记 no-drag。
 *
 * 鼠标穿透说明：开启后窗口完全不可交互（点击穿透到下层窗口），
 * 本窗口内无法自行恢复。恢复入口依赖主进程侧（托盘菜单项或全局快捷键），
 * 当前为 IPC/主进程缺口——见 DanmakuPage 注释与任务汇报。
 */
import type { CSSProperties, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  Eraser,
  MessageSquare,
  MousePointerClick,
  Pause,
  Pin,
  PinOff,
  Play,
  X,
} from 'lucide-react';
import { MIN_BACKGROUND_OPACITY, MAX_BACKGROUND_OPACITY } from '../../store/danmakuStore';

/** 连接状态：未连接（初始/从未连上）/ 已连接 / 重连中（连上后断开，传输层自动退避重连） */
export type DanmakuConnectionStatus = 'connecting' | 'connected' | 'reconnecting';

const STATUS_DOT_CLASS: Record<DanmakuConnectionStatus, string> = {
  connected: 'bg-emerald-400',
  reconnecting: 'bg-amber-400 animate-pulse',
  connecting: 'bg-gray-400',
};

const DRAG_STYLE = { WebkitAppRegion: 'drag' } as CSSProperties;
const NO_DRAG_STYLE = { WebkitAppRegion: 'no-drag' } as CSSProperties;

interface ToolButtonProps {
  title: string;
  active?: boolean;
  onClick: () => void;
  children: ReactNode;
}

function ToolButton({ title, active = false, onClick, children }: ToolButtonProps) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      style={NO_DRAG_STYLE}
      className={clsx(
        'flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors duration-fast',
        active
          ? 'bg-primary/25 text-primary'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground',
      )}
    >
      {children}
    </button>
  );
}

interface DanmakuToolbarProps {
  status: DanmakuConnectionStatus;
  paused: boolean;
  alwaysOnTop: boolean;
  clickThrough: boolean;
  backgroundOpacity: number;
  onTogglePaused: () => void;
  onClear: () => void;
  onToggleAlwaysOnTop: () => void;
  onToggleClickThrough: () => void;
  onOpacityChange: (v: number) => void;
  onHideWindow: () => void;
}

export default function DanmakuToolbar({
  status,
  paused,
  alwaysOnTop,
  clickThrough,
  backgroundOpacity,
  onTogglePaused,
  onClear,
  onToggleAlwaysOnTop,
  onToggleClickThrough,
  onOpacityChange,
  onHideWindow,
}: DanmakuToolbarProps) {
  const { t } = useTranslation();

  return (
    <div className="glass-panel flex shrink-0 items-center gap-1 px-2 py-1.5" style={DRAG_STYLE}>
      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-accent" />
      <span className="shrink-0 text-xs font-bold">{t('danmaku.title')}</span>

      {/* 连接状态指示 */}
      <span className="flex shrink-0 items-center gap-1 pl-1 text-[10px] text-muted-foreground">
        <span className={clsx('h-1.5 w-1.5 rounded-full', STATUS_DOT_CLASS[status])} />
        {t(`danmaku.status.${status}`)}
      </span>

      {/* 弹性间隔（拖拽区） */}
      <div className="min-w-2 flex-1" />

      <ToolButton
        title={paused ? t('danmaku.resume') : t('danmaku.pause')}
        active={paused}
        onClick={onTogglePaused}
      >
        {paused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
      </ToolButton>

      <ToolButton title={t('danmaku.clear')} onClick={onClear}>
        <Eraser className="h-3.5 w-3.5" />
      </ToolButton>

      <ToolButton
        title={t('danmaku.alwaysOnTop')}
        active={alwaysOnTop}
        onClick={onToggleAlwaysOnTop}
      >
        {alwaysOnTop ? <Pin className="h-3.5 w-3.5" /> : <PinOff className="h-3.5 w-3.5" />}
      </ToolButton>

      {/* 背景不透明度滑块（仅作用于玻璃背景层） */}
      <input
        type="range"
        min={MIN_BACKGROUND_OPACITY}
        max={MAX_BACKGROUND_OPACITY}
        step={0.05}
        value={backgroundOpacity}
        onChange={(e) => onOpacityChange(Number(e.target.value))}
        aria-label={t('danmaku.opacity')}
        title={t('danmaku.opacity')}
        style={NO_DRAG_STYLE}
        className="h-1 w-16 shrink-0 cursor-pointer accent-[var(--color-primary)]"
      />

      <ToolButton
        title={`${t('danmaku.clickThrough')} — ${t('danmaku.clickThroughHint')}`}
        active={clickThrough}
        onClick={onToggleClickThrough}
      >
        <MousePointerClick className="h-3.5 w-3.5" />
      </ToolButton>

      <ToolButton title={t('danmaku.hideWindow')} onClick={onHideWindow}>
        <X className="h-3.5 w-3.5" />
      </ToolButton>
    </div>
  );
}
