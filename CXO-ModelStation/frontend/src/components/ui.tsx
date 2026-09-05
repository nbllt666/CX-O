/*
 * 共享 UI 小组件：状态徽章 / 错误条 / 通知条 / 格式化工具。
 * 各页面统一引用，保证状态与提示的展示口径一致。
 */

// ======================== 状态徽章 ========================

const STATUS_LABELS: Record<string, string> = {
  idle: "空闲",
  pending: "待执行",
  running: "进行中",
  busy_starting: "启动中",
  completed: "已完成",
  success: "成功",
  partial: "部分成功",
  failed: "失败",
  error: "错误",
  stopped: "已停止",
};

const STATUS_VARIANTS: Record<string, string> = {
  idle: "badge-pending",
  pending: "badge-pending",
  running: "badge-running",
  busy_starting: "badge-running",
  completed: "badge-success",
  success: "badge-success",
  partial: "badge-warning",
  failed: "badge-error",
  error: "badge-error",
  stopped: "badge-pending",
};

export function StatusBadge({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  const variant = STATUS_VARIANTS[status] ?? "badge-pending";
  return <span className={`badge ${variant}`}>{label}</span>;
}

// ======================== 错误条 ========================

export interface ErrorBarProps {
  message: string | null;
  /** 连续失败已停止轮询时附加提示 */
  stopped?: boolean;
  onRetry?: () => void;
}

export function ErrorBar({ message, stopped, onRetry }: ErrorBarProps) {
  if (!message) {
    return null;
  }
  return (
    <div className="error-bar" role="alert">
      <span>
        {message}
        {stopped ? "（自动刷新已停止，处理后可点击重试）" : ""}
      </span>
      {onRetry ? (
        <button type="button" className="btn btn-ghost btn-small" onClick={onRetry}>
          重试
        </button>
      ) : null}
    </div>
  );
}

// ======================== 通知条 ========================

export function NoticeBar({
  message,
  variant = "info",
}: {
  message: string | null;
  variant?: "info" | "success" | "error";
}) {
  if (!message) {
    return null;
  }
  return (
    <div className={`notice-bar notice-${variant}`} role="status">
      {message}
    </div>
  );
}

// ======================== 格式化工具 ========================

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "-";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = -1;
  do {
    value /= 1024;
    unitIndex += 1;
  } while (value >= 1024 && unitIndex < units.length - 1);
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) {
    return "-";
  }
  return iso.replace("T", " ");
}

export function formatEpochTime(seconds: number): string {
  if (!Number.isFinite(seconds)) {
    return "-";
  }
  const d = new Date(seconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
