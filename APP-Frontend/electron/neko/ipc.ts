/**
 * Neko 运行时 IPC（Electron 主进程）——独立适配器客户端版
 * ============================================================================
 * 主进程不再内嵌 Neko 运行时（launcher/toolBridge 已迁至独立适配器项目
 * CXO-NekoAdapter）。本文件把渲染层 IPC 瘦身为适配器控制面客户端：
 *   - 生命周期：neko:get-status / neko:start / neko:stop / neko:restart /
 *     neko:get-config / neko:set-config / neko:get-bridge-status
 *   - HTTP 代理：neko:http —— 经主进程 net.fetch 直连插件服务器（原逻辑保留）
 *   - 日志推送：neko:stdout（适配器 stdout 转发 + SSE 日志流统一走 logSink 广播）
 *
 * 渲染层契约（src/types/electron.d.ts NekoRuntimeConfig 四键）100% 保持：
 * getStatus→{running,port,config:{python,sourceDir,port,autoStart}}；
 * start/stop/restart→{ok,port?,error?}；getConfig/setConfig→NekoRuntimeConfig；
 * http→{ok,status?,body?,error?}；getBridgeStatus→桥状态五字段。
 * ============================================================================
 */
import { BrowserWindow, net } from 'electron';
import type { IpcMainInvokeEvent } from 'electron';
import { getConfig, setConfig } from '../config';
import { registerIpcHandler } from '../security';
import {
  ADAPTER_DEFAULTS,
  createAdapterClient,
  NEKO_ELECTRON_KEYS,
  type AdapterClient,
  type AdapterConfigPatch,
} from './adapterClient';

/** 渲染层可见的运行时配置（对齐 src/types/electron.d.ts NekoRuntimeConfig 四键） */
interface RendererNekoConfig {
  python: string;
  sourceDir: string;
  port: number;
  autoStart: boolean;
}

/** 渲染层可见的 CXFC 工具桥状态（对齐 electron.d.ts getBridgeStatus 返回） */
interface RendererBridgeStatus {
  registrarRunning: boolean;
  bridgeRunning: boolean;
  bridgePort: number | null;
  tools: number;
  cxfcRegistered: boolean;
}

/** 适配器不可用时的空桥状态 */
const EMPTY_BRIDGE_STATUS: RendererBridgeStatus = {
  registrarRunning: false,
  bridgeRunning: false,
  bridgePort: null,
  tools: 0,
  cxfcRegistered: false,
};

interface ProxyRequest {
  method?: string;
  path: string;
  query?: Record<string, string | number | boolean>;
  body?: unknown;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** 日志广播：推送给所有窗口（neko:stdout 事件，渲染层经 onLog 订阅） */
function broadcastNekoLog(line: string): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send('neko:stdout', line);
    }
  }
}

// ---------------------------------------------------------------------------
// 适配器客户端单例（electron 真实依赖注入；main.ts 复用同一实例做生命周期接线）
// ---------------------------------------------------------------------------

let adapterSingleton: AdapterClient | null = null;

export function getNekoAdapter(): AdapterClient {
  if (!adapterSingleton) {
    adapterSingleton = createAdapterClient({
      getConfig,
      setConfig,
      logSink: broadcastNekoLog,
    });
  }
  return adapterSingleton;
}

// ---------------------------------------------------------------------------
// 渲染层映射辅助
// ---------------------------------------------------------------------------

/** 适配器全量配置 → 渲染层四键（多余键剔除，字段缺失回落默认值） */
function pickRendererConfig(full: unknown): RendererNekoConfig {
  const c = (full ?? {}) as Record<string, unknown>;
  return {
    python: typeof c.python === 'string' && c.python ? c.python : ADAPTER_DEFAULTS.python,
    sourceDir: typeof c.sourceDir === 'string' && c.sourceDir ? c.sourceDir : ADAPTER_DEFAULTS.sourceDir,
    port: Number.isFinite(Number(c.port)) && Number(c.port) > 0 ? Math.floor(Number(c.port)) : ADAPTER_DEFAULTS.port,
    autoStart: c.autoStart === true,
  };
}

/** 适配器不可用时的渲染层配置回落：读 electron 存量键（保持旧版 UI 展示语义） */
function fallbackRendererConfig(): RendererNekoConfig {
  return {
    python: getConfig(NEKO_ELECTRON_KEYS.python) || ADAPTER_DEFAULTS.python,
    sourceDir: getConfig(NEKO_ELECTRON_KEYS.sourceDir) || ADAPTER_DEFAULTS.sourceDir,
    port: Number(getConfig(NEKO_ELECTRON_KEYS.port)) || ADAPTER_DEFAULTS.port,
    autoStart: getConfig(NEKO_ELECTRON_KEYS.autoStart) === 'true',
  };
}

/** 适配器桥状态 → 渲染层桥状态（字段缺失逐项回落默认） */
function pickRendererBridge(full: unknown): RendererBridgeStatus {
  const b = (full ?? {}) as Record<string, unknown>;
  return {
    registrarRunning: b.registrarRunning === true,
    bridgeRunning: b.bridgeRunning === true,
    bridgePort: typeof b.bridgePort === 'number' ? b.bridgePort : null,
    tools: Number.isFinite(Number(b.tools)) ? Number(b.tools) : 0,
    cxfcRegistered: b.cxfcRegistered === true,
  };
}

// ---------------------------------------------------------------------------
// HTTP 代理辅助（原逻辑保留）
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// IPC 注册
// ---------------------------------------------------------------------------

export function registerNekoIpc(): void {
  const adapter = getNekoAdapter();

  // 生命周期/状态/配置
  registerIpcHandler('neko:get-status', async () => {
    try {
      const s = await adapter.getStatus();
      return { running: s.running, port: s.running ? s.port : null, config: pickRendererConfig(s.config) };
    } catch {
      // 适配器进程不可用：running=false，配置以 electron 存量键回落展示
      return { running: false, port: null, config: fallbackRendererConfig() };
    }
  });

  registerIpcHandler('neko:get-config', async () => {
    try {
      return pickRendererConfig(await adapter.getAdapterConfig());
    } catch {
      return fallbackRendererConfig();
    }
  });

  registerIpcHandler('neko:set-config', async (_event, partial: Partial<RendererNekoConfig> | undefined) => {
    const p = partial ?? {};
    // autoStart 仍写 electron 配置（应用启动判断依据）；python/sourceDir/port 写入适配器
    if (p.autoStart !== undefined) {
      setConfig(NEKO_ELECTRON_KEYS.autoStart, String(!!p.autoStart));
    }
    const patch: AdapterConfigPatch = {};
    if (typeof p.python === 'string') patch.python = p.python.trim();
    if (typeof p.sourceDir === 'string') patch.sourceDir = p.sourceDir.trim();
    if (p.port !== undefined) patch.port = Math.max(0, Math.floor(Number(p.port) || 0));
    try {
      return pickRendererConfig(await adapter.putConfig(patch));
    } catch (error) {
      broadcastNekoLog(`[neko] 写入适配器配置失败: ${messageOf(error)}`);
      // 回落：读取适配器当前配置合并本次传入值；仍失败则以默认值合并返回
      try {
        const current = await adapter.getAdapterConfig();
        return pickRendererConfig({ ...(current as Record<string, unknown>), ...patch });
      } catch {
        return {
          python: patch.python ?? ADAPTER_DEFAULTS.python,
          sourceDir: patch.sourceDir ?? ADAPTER_DEFAULTS.sourceDir,
          port: patch.port ?? ADAPTER_DEFAULTS.port,
          autoStart: p.autoStart ?? ADAPTER_DEFAULTS.autoStart,
        };
      }
    }
  });

  registerIpcHandler('neko:start', async () => {
    try {
      await adapter.ensureAdapter(); // 确保适配器进程在（幂等互斥）
      const r = await adapter.start();
      return r.ok ? { ok: true, port: r.port } : { ok: false, error: r.error ?? '启动失败' };
    } catch (error) {
      return { ok: false, error: messageOf(error) };
    }
  });

  registerIpcHandler('neko:stop', async () => {
    try {
      const r = await adapter.stop(); // 仅停运行时，不杀适配器进程；适配器侧幂等
      return r.ok ? { ok: true } : { ok: false, error: r.error ?? '停止失败' };
    } catch (error) {
      return { ok: false, error: messageOf(error) };
    }
  });

  registerIpcHandler('neko:restart', async () => {
    try {
      // 修复语义：适配器进程不在时先拉起，再完整重建运行时
      await adapter.ensureAdapter();
      const r = await adapter.restart();
      return r.ok ? { ok: true, port: r.port } : { ok: false, error: r.error ?? '重启失败' };
    } catch (error) {
      return { ok: false, error: messageOf(error) };
    }
  });

  // CXFC 工具桥状态（仅供管理页展示）
  registerIpcHandler('neko:get-bridge-status', async () => {
    try {
      const s = await adapter.getStatus();
      return pickRendererBridge(s.bridge);
    } catch {
      return { ...EMPTY_BRIDGE_STATUS };
    }
  });

  // HTTP 代理：渲染层把对插件服务器的请求转发过来，主进程 net.fetch 直连
  registerIpcHandler('neko:http', async (_event: IpcMainInvokeEvent, req: ProxyRequest) => {
    let running = false;
    let port: number | null = null;
    try {
      const status = await adapter.getStatus();
      running = status.running;
      port = status.port;
    } catch {
      running = false;
    }
    if (!running || port === null) {
      return { ok: false, error: '插件服务器未运行' };
    }
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
      // F6: 插件服务器挂起时 Promise 永久悬挂会使管理页状态卡 loading；
      // 加 15s 超时兜底（Electron net.fetch 支持 AbortSignal.timeout）。
      const response = await net.fetch(url, {
        method,
        headers,
        body,
        signal: AbortSignal.timeout(15000),
      });
      const text = await response.text();
      return { ok: true, status: response.status, body: text };
    } catch (error) {
      return { ok: false, error: error instanceof Error ? error.message : String(error) };
    }
  });
}
