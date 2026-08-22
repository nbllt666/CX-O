/**
 * Neko 运行时 IPC（Electron 主进程）
 * ============================================================================
 * 向渲染层暴露：
 *   - 生命周期：neko:get-status / neko:start / neko:stop / neko:restart / neko:get-config / neko:set-config
 *   - HTTP 代理：neko:http —— 渲染层经主进程 net.fetch 直连插件服务器，
 *     规避生产环境 file:// 下的 CORS 与 Host/Origin 守卫问题。
 *   - 日志推送：neko:stdout（副作用：start 时挂载 logSink，广播给所有窗口）
 * ============================================================================
 */
import { BrowserWindow, ipcMain, net } from 'electron';
import type { IpcMainInvokeEvent } from 'electron';
import {
  getNekoConfig,
  getNekoStatus,
  setNekoConfig,
  setNekoLogSink,
  startNekoRuntime,
  stopNekoRuntime,
  restartNeko,
  type NekoRuntimeConfig,
} from './launcher';
import { getNekoToolBridgeStatus } from './toolBridge';

interface ProxyRequest {
  method?: string;
  path: string;
  query?: Record<string, string | number | boolean>;
  body?: unknown;
}

/** 校验代理目标只能是绑定本机 loopback 的插件服务器端口 */
function validateProxyTarget(port: number, pathValue: string): boolean {
  if (!Number.isInteger(port) || port <= 0 || port > 65535) return false;
  if (typeof pathValue !== 'string' || !pathValue.startsWith('/')) return false;
  if (/[\s|\n]/.test(pathValue)) return false;
  return true;
}

function buildQueryString(query?: Record<string, string | number | boolean>): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

export function registerNekoIpc(): void {
  // 日志广播：start / stop 时把 sidecar stdout/stderr 推送给所有窗口
  setNekoLogSink((line) => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (!win.isDestroyed()) {
        win.webContents.send('neko:stdout', line);
      }
    }
  });

  ipcMain.handle('neko:get-status', () => getNekoStatus());

  ipcMain.handle('neko:get-config', () => getNekoConfig());

  ipcMain.handle('neko:set-config', (_event, partial: Partial<NekoRuntimeConfig>) => {
    return setNekoConfig(partial ?? {});
  });

  ipcMain.handle('neko:start', async () => {
    try {
      return { ok: true, ...(await startNekoRuntime()) };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  });

  ipcMain.handle('neko:stop', async () => {
    try {
      await stopNekoRuntime();
      return { ok: true };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  });

  ipcMain.handle('neko:restart', async () => {
    try {
      return { ok: true, ...(await restartNeko()) };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  });

  // CXFC 工具桥状态（仅供管理页展示）
  ipcMain.handle('neko:get-bridge-status', () => getNekoToolBridgeStatus());

  // HTTP 代理：渲染层把对插件服务器的请求转发过来，主进程 net.fetch 直连
  ipcMain.handle('neko:http', async (_event: IpcMainInvokeEvent, req: ProxyRequest) => {
    const status = getNekoStatus();
    if (!status.running || status.port === null) {
      return { ok: false, error: '插件服务器未运行' };
    }
    const port = status.port;
    const pathValue = req?.path;
    if (!validateProxyTarget(port, pathValue)) {
      return { ok: false, error: '非法代理目标' };
    }

    const method = (req?.method ?? 'GET').toUpperCase();
    const query = buildQueryString(req?.query);
    const url = `http://127.0.0.1:${port}${pathValue}${query}`;
    const headers: Record<string, string> = { Accept: 'application/json' };
    let body: string | undefined;
    if (req?.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
    }

    try {
      const response = await net.fetch(url, { method, headers, body });
      const text = await response.text();
      return { ok: true, status: response.status, body: text };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  });
}