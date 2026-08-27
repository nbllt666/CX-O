/**
 * IPC 来源校验共享守卫（安全加固）
 * ============================================================================
 * 背景：ipcMain.handle 注册的通道默认对所有渲染进程开放，恶意页面若经任何途径
 * 获得与主进程同源的 ipcRenderer 能力（如被注入 iframe 或未来新增窗口配置失误），
 * 即可无差别调用全部 IPC。此处提供统一来源白名单：
 *   a) file:// 协议          —— 打包产物页面（loadFile 加载 dist/index.html）
 *   b) http://localhost:*    —— Vite dev server（端口任意，当前固定 3100）
 *   c) http://127.0.0.1:*    —— dev server host:true 场景同理由本机回环访问
 * 项目未注册自定义 protocol（vite.config.ts 无 protocol.handle/privileges.scheme），
 * 无需额外 scheme 白名单。
 *
 * 未通过校验的处理策略：log warning（含被拒 URL 截断）并让 handler 返回 undefined，
 * 统一不 throw——渲染层 invoke 方以 `await electronAPI.xxx()` 消费结果且普遍做空值/
 * 对象解构容错，抛错会在主进程产生 unhandled rejection，静默拒绝语义更稳。
 *
 * 关键边界：event.senderFrame 为 null（页面销毁瞬间）一律视为不可信；
 * 仅当事件完全缺失 senderFrame 字段（旧版本事件形态）才回退读 sender 页面 URL。
 * ============================================================================
 */
import { ipcMain } from 'electron';
import type { IpcMainInvokeEvent } from 'electron';

/** dev 场景本机 http Origin/URL 白名单：localhost 与 127.0.0.1 的任意端口。
 *  锚定主机名结尾，拒绝 localhost.evil.com 之类伪装域。 */
const TRUSTED_LOCAL_HTTP_RE = /^http:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?(?:[/?#]|$)/i;

/**
 * 提取发起方页面 URL：优先 event.senderFrame.url（frame 销毁或取值抛错 → null）；
 * 仅当事件不含 senderFrame 字段时回退 event.sender 的当前页 URL。
 */
function extractSenderUrl(event: unknown): string | null {
  if (event === null || typeof event !== 'object') return null;
  const ev = event as {
    senderFrame?: {
      url?: string;
      isDestroyed?: () => boolean;
    } | null;
    sender?: { getURL?: () => string; url?: string };
  };

  if (ev.senderFrame === undefined) {
    // 兼容回退：旧版本事件无 senderFrame 字段 → 读 sender 的页面 URL
    try {
      const sender = ev.sender;
      const url =
        typeof sender?.getURL === 'function' ? sender.getURL() : (sender?.url ?? null);
      return typeof url === 'string' && url.length > 0 ? url : null;
    } catch {
      return null;
    }
  }

  const frame = ev.senderFrame;
  if (!frame) return null; // 明确 null：页面销毁瞬间 → 一律不可信
  try {
    if (typeof frame.isDestroyed === 'function' && frame.isDestroyed()) return null;
    const url = frame.url; // getter 在销毁竞态下可能同步抛错
    return typeof url === 'string' && url.length > 0 ? url : null;
  } catch {
    return null;
  }
}

/** 判定原始 URL 是否属于信任来源（file:// 或本机 http）。非法输入一律不可信。 */
export function isTrustedUrl(rawUrl: unknown): boolean {
  if (typeof rawUrl !== 'string' || rawUrl.length === 0) return false;
  if (/^file:\/\//i.test(rawUrl)) return true;
  return TRUSTED_LOCAL_HTTP_RE.test(rawUrl);
}

/** ipcMain.handle/on 守卫入口：发起方页面不在白名单则拒绝。 */
export function isTrustedSender(event: unknown): boolean {
  return isTrustedUrl(extractSenderUrl(event));
}

/** 日志用 URL 截断（防超长 query 刷屏）。 */
export function truncateForLog(value: unknown, maxLen = 120): string {
  const s = typeof value === 'string' ? value : value == null ? '(null)' : String(value);
  return s.length > maxLen ? `${s.slice(0, maxLen)}…[截断]` : s;
}

/**
 * ipcMain.handle 的来源受控注册封装：非白名单来源调用时 log warning 并返回
 * undefined（invoke 方收到空结果），不进入业务 handler。
 * 各注册点仅把 `ipcMain.handle(ch, h)` 替换为本函数，业务体零改动。
 */
export function registerIpcHandler<Args extends unknown[]>(
  channel: string,
  handler: (event: IpcMainInvokeEvent, ...args: Args) => unknown,
): void {
  ipcMain.handle(channel, async (event: IpcMainInvokeEvent, ...args: unknown[]) => {
    if (!isTrustedSender(event)) {
      console.warn(
        `[security] 已拒绝不可信来源的 IPC 调用: channel=${channel} url=${truncateForLog(extractSenderUrl(event))}`,
      );
      return undefined;
    }
    return await handler(event, ...(args as Args));
  });
}
