/**
 * H4 拆分：双流式实时语音状态栏。
 *
 * Presentational 组件 — 仅接收 props，不持有状态。
 */
export interface DualStreamStatusBarProps {
  isDualStreamMode: boolean;
  dualThinking: boolean;
  isTTSPlaying: boolean;
  partialSubtitle: string;
}

export function DualStreamStatusBar({ isDualStreamMode, dualThinking, isTTSPlaying, partialSubtitle }: DualStreamStatusBarProps) {
  if (!isDualStreamMode) return null;

  return (
    <div className="mb-3 rounded-xl border border-[var(--color-accent)] bg-[var(--color-accent-light)] px-4 py-2.5">
      <div className="flex items-center gap-2 mb-1">
        <span className="flex items-center gap-1.5 text-xs font-medium text-[var(--color-accent)]">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--color-accent)] opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-[var(--color-accent)]" />
          </span>
          双流式实时语音
        </span>
        {dualThinking && (
          <span className="text-xs text-[var(--color-text-secondary)] animate-pulse">正在思考…</span>
        )}
        {isTTSPlaying && !dualThinking && (
          <span className="text-xs text-[var(--color-text-secondary)]">正在播报…</span>
        )}
      </div>
      {partialSubtitle ? (
        <p className="text-sm text-[var(--color-text-primary)]">
          <span className="text-[var(--color-text-tertiary)] mr-1">你：</span>
          {partialSubtitle}
        </p>
      ) : (
        !dualThinking && !isTTSPlaying && (
          <p className="text-xs text-[var(--color-text-tertiary)]">请开口说话…</p>
        )
      )}
    </div>
  );
}
