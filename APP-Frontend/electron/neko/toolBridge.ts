/**
 * Neko 插件 LLM 工具 → CXFC 桥（Electron 主进程）
 * ============================================================================
 * 组合层：把纯逻辑（toolBridgeCore）接到真实 socket 与 CX-O 后端：
 *   1. 注册接收器（loopback HTTP，主服务器端口 48911）——模拟 neko 主服务器
 *      /api/tools/*，完整捕获插件 POST 来的工具定义。
 *   2. CXFC HTTPS 桥（/health /tools /skills /call）——按 CXFC 协议鉴权/防重放，
 *      /call 转发到插件服务器 /api/llm-tools/callback/{plugin}/{tool}。
 *   3. 用 CxfcClient 把桥注册到 CX-O 后端并维持心跳（复用电脑控制那套）。
 *
 * 生命周期：registrar 须先于插件服务器启动；桥 + CXFC 注册须在插件服务器
 * 就绪（插件已加载、工具已上报）后启动。由 launcher 的 startNekoRuntime 编排。
 * ============================================================================
 */
import { app } from 'electron';
import { createServer as createHttpServer, type Server as HttpServer } from 'node:http';
import { createServer as createHttpsServer, type Server as HttpsServer } from 'node:https';
import type { IncomingMessage, ServerResponse } from 'node:http';
import * as path from 'node:path';
import { randomBytes } from 'node:crypto';
import { Authenticator } from '../plugins/computerControl/auth';
import { ensureCertificate } from '../plugins/computerControl/tls';
import { HTTP_STATUS, messageOf, type ErrorCode } from '../plugins/computerControl/errors';
import { createCxfcClient, type CxfcClient, type PluginRuntimeInfo } from '../cxfc/client';
import { getConfig } from '../config';
import {
  handleRegistrarRoute,
  executeNekoToolCall,
  readJsonBody,
  jsonPayload,
  ToolRegistrarStore,
} from './toolBridgeCore';

export const NEKO_MAIN_SERVER_REGISTER_PORT = 48911;
const BRIDGE_BASE_PORT = 28443;
const MAX_BRIDGE_ATTEMPTS = 10;
const SETTLE_AFTER_PLUGIN_BOOT_MS = 2000;

// ── 模块级单例状态 ──
let registrarServer: HttpServer | null = null;
let bridgeServer: HttpsServer | null = null;
let bridgePort = 0;
let cxfcClient: CxfcClient | null = null;
let authenticator: Authenticator | null = null;
let token = '';
let tls: { cert: string; key: string; fingerprint: string } | null = null;
let pluginPort: number | null = null;

const store = new ToolRegistrarStore();

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

function writeJson(res: ServerResponse, status: number, payload: unknown): void {
  const data = JSON.stringify(payload);
  res.writeHead(status, jsonPayload(data, status).headers);
  res.end(data);
}

/** 读取并解析 JSON 请求体；超限/非法返回 null */
async function readJson(res: IncomingMessage): Promise<Record<string, unknown> | null> {
  return readJsonBody(res);
}

function bearerOf(header: string | undefined): string | undefined {
  if (!header) return undefined;
  const m = /^Bearer\s+(.+)$/i.exec(header.trim());
  return m ? m[1] : undefined;
}

// ---------------------------------------------------------------------------
// 1. 注册接收器（模拟 neko 主服务器 /api/tools/*）
// ---------------------------------------------------------------------------

async function startRegistrar(): Promise<void> {
  if (registrarServer) return;
  const server = createHttpServer((req, res) => {
    void (async () => {
      let url: URL;
      try {
        url = new URL(req.url ?? '/', `http://127.0.0.1:${NEKO_MAIN_SERVER_REGISTER_PORT}`);
      } catch {
        return writeJson(res, 400, { ok: false, error: '非法路径' });
      }
      const body = req.method === 'POST' ? await readJson(req) : null;
      const result = handleRegistrarRoute(store, req.method ?? 'GET', url.pathname, body);
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    })();
  });
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(NEKO_MAIN_SERVER_REGISTER_PORT, '127.0.0.1', () => {
      server.removeListener('error', reject);
      registrarServer = server;
      resolve();
    });
  });
}

// ---------------------------------------------------------------------------
// 2. CXFC HTTPS 桥
// ---------------------------------------------------------------------------

function buildBridgeInfo(): PluginRuntimeInfo {
  if (!tls || !bridgePort) {
    throw new Error('桥未就绪');
  }
  return {
    host: '127.0.0.1',
    port: bridgePort,
    name: 'APP-Frontend Neko 插件工具桥',
    version: '1.0.0',
    capabilities: ['plugin_tools'],
    tools: store.listSchemas(),
    skills: [],
    token,
    tls_cert_fingerprint: tls.fingerprint,
    tls_cert_pem: tls.cert,
  };
}

async function handleBridgeCall(req: IncomingMessage, res: ServerResponse): Promise<void> {
  const auth = authenticator?.verifyAuth(bearerOf(req.headers.authorization));
  if (!auth || !auth.ok) return writeJson(res, 401, { ok: false, error: { code: 'UNAUTHORIZED', message: '认证失败' } });

  const body = await readJson(req);
  if (body === null) return writeJson(res, 400, { ok: false, error: { code: 'INVALID_ARGUMENT', message: '请求体必须为 JSON 对象' } });

  const replay = authenticator?.verifyReplay(body.request_id);
  if (replay && !replay.ok) {
    const code = replay.code as ErrorCode;
    return writeJson(res, HTTP_STATUS[code] ?? 409, { ok: false, error: { code, message: '防重放拒绝' } });
  }

  const result = await executeNekoToolCall(
    store,
    { tool: body.tool as string | undefined, arguments: (body.arguments as Record<string, unknown> | undefined) ?? {}, request_id: body.request_id as string | undefined },
    {
      pluginPort: pluginPort ?? 0,
    },
  );

  if (result.ok) {
    return writeJson(res, 200, { ok: true, result: result.result });
  }
  const code = result.code as ErrorCode;
  return writeJson(res, HTTP_STATUS[code] ?? 500, { ok: false, error: { code, message: result.message } });
}

async function startBridgeServer(): Promise<number> {
  if (bridgeServer) return bridgePort;

  const certDir = path.join(app.getPath('userData'), 'neko', 'toolBridge');
  const material = ensureCertificate(certDir);
  tls = { cert: material.cert, key: material.key, fingerprint: material.fingerprint };
  token = randomBytes(32).toString('hex');
  authenticator = new Authenticator({ token });

  const server = createHttpsServer({ key: material.key, cert: material.cert }, (req, res) => {
    void handleBridgeReq(req, res);
  });

  // 端口冲突递增重试
  let lastErr: unknown = null;
  for (let attempt = 0; attempt < MAX_BRIDGE_ATTEMPTS; attempt++) {
    const port = BRIDGE_BASE_PORT + attempt;
    try {
      await new Promise<void>((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, '127.0.0.1', () => {
          server.removeListener('error', reject);
          bridgeServer = server;
          bridgePort = port;
          resolve();
        });
      });
      return bridgePort;
    } catch (err) {
      lastErr = err;
      if ((err as { code?: string }).code !== 'EADDRINUSE') throw err;
    }
  }
  throw new Error(`无法绑定桥端口（最后错误：${messageOf(lastErr)}）`);
}

async function handleBridgeReq(req: IncomingMessage, res: ServerResponse): Promise<void> {
  let url: URL;
  try {
    url = new URL(req.url ?? '/', `https://127.0.0.1:${bridgePort || BRIDGE_BASE_PORT}`);
  } catch {
    return writeJson(res, 400, { ok: false, error: { code: 'INVALID_ARGUMENT', message: '非法请求路径' } });
  }
  const p = url.pathname;
  try {
    if (req.method === 'GET' && p === '/health') {
      return writeJson(res, 200, { ok: true, status: 'ok', service: 'neko-tools', fingerprint: tls?.fingerprint });
    }
    if (req.method === 'GET' && p === '/tools') {
      return writeJson(res, 200, { ok: true, tools: store.list().map((d) => d.name) });
    }
    if (req.method === 'GET' && p === '/skills') {
      return writeJson(res, 200, { ok: true, skills: [] });
    }
    if (req.method === 'POST' && p === '/call') {
      return handleBridgeCall(req, res);
    }
    return writeJson(res, 400, { ok: false, error: { code: 'INVALID_ARGUMENT', message: '未知端点或方法' } });
  } catch (err) {
    return writeJson(res, 500, { ok: false, error: { code: 'SYSTEM_ERROR', message: `内部错误: ${messageOf(err)}` } });
  }
}

// ---------------------------------------------------------------------------
// 3. 对外编排
// ---------------------------------------------------------------------------

/** 启动注册接收器（必须在插件服务器之前调用，纯 HTTP，尽力而为） */
export async function startNekoToolRegistrar(): Promise<boolean> {
  try {
    await startRegistrar();
    return true;
  } catch {
    return false; // 端口被真实 neko 主服务器占用等场景：降级为捕获不到完整定义
  }
}

/** 启动 CXFC 桥并注册到后端。@param pluginPort 插件服务器实际端口 */
export async function startNekoToolBridge(nekoPluginPort: number | null): Promise<{ port: number; tools: number }> {
  pluginPort = nekoPluginPort;
  const p = await startBridgeServer();

  // 等待插件/工具稳定后注册（插件服务器刚起时有加载窗口）
  await new Promise((r) => setTimeout(r, SETTLE_AFTER_PLUGIN_BOOT_MS));

  const backendUrl = getConfig('backendUrl') || 'http://127.0.0.1:8000';
  if (!cxfcClient) {
    cxfcClient = createCxfcClient({
      backendUrl,
      // 每轮注册/心跳前重新读取配置（G5b）：跟随设置页修改后的最新后端地址
      backendUrlResolver: () => getConfig('backendUrl'),
      readPluginInfo: () => buildBridgeInfo(),
      logger: (line) => console.log(`[neko-bridge] ${line}`),
    });
    cxfcClient.start();
  }
  return { port: p, tools: store.size() };
}

/** 停止 CXFC 桥 + 注册接收器 */
export async function stopNekoToolBridge(): Promise<void> {
  if (cxfcClient) {
    try {
      await cxfcClient.stop();
    } catch {
      /* best-effort */
    }
    cxfcClient = null;
  }
  if (bridgeServer) {
    const s = bridgeServer;
    bridgeServer = null;
    await new Promise<void>((resolve) => s.close(() => resolve()));
  }
  if (registrarServer) {
    const s = registrarServer;
    registrarServer = null;
    await new Promise<void>((resolve) => s.close(() => resolve()));
  }
  bridgePort = 0;
  pluginPort = null;
  authenticator = null;
  tls = null;
  token = '';
}

export interface NekoToolBridgeStatus {
  registrarRunning: boolean;
  bridgeRunning: boolean;
  bridgePort: number | null;
  tools: number;
  cxfcRegistered: boolean;
}

/** 当前状态（供 IPC / 管理页展示） */
export function getNekoToolBridgeStatus(): NekoToolBridgeStatus {
  return {
    registrarRunning: !!registrarServer,
    bridgeRunning: !!bridgeServer,
    bridgePort: bridgeServer ? bridgePort : null,
    tools: store.size(),
    cxfcRegistered: cxfcClient?.isRegistered() ?? false,
  };
}
