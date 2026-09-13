/**
 * 控制面 HTTP 服务器（独立适配器进程）
 * ============================================================================
 * 职责：为 CX-O 前端 / CLI / Electron before-quit 提供本机控制 API：
 *   - 运行时状态查询与启停（/health /status /start /stop /restart）
 *   - 配置读写（GET/PUT /config，PUT 前做键与类型校验）
 *   - 日志（GET /logs/recent 一次性拉取；GET /logs/stream SSE 实时推送）
 *
 * 结构：可单测的纯路由函数 handleControlRoute（ctx 注入依赖，无真实 IO）+
 * 薄 HTTP 层 startControlServer（真实接线），与 toolBridgeCore/toolBridge
 * 的分层风格一致。仅绑定 127.0.0.1，不对局域网暴露。
 * ============================================================================
 */
import {
  createServer as createHttpServer,
  type IncomingMessage,
  type Server as HttpServer,
  type ServerResponse,
} from 'node:http';
import type { AddressInfo } from 'node:net';
import { messageOf } from '../shared/errors';
import { getAll, getConfig, setConfig, type AdapterConfig } from '../shared/config';
import {
  startNekoRuntime,
  stopNekoRuntime,
  restartNekoFull,
  getNekoStatus,
  setNekoLogSink,
} from '../launcher/launcher';
import { getNekoToolBridgeStatus } from '../bridge/toolBridge';
import { getRuntimeLogLines } from '../launcher/logBuffer';
import { jsonPayload, type JsonBody } from '../bridge/toolBridgeCore';

// ---------------------------------------------------------------------------
// 上下文契约（纯路由与 HTTP 层之间的依赖注入边界）
// ---------------------------------------------------------------------------

/** /status 返回的聚合快照：launcher 状态 + 工具桥状态 */
export interface ControlStatusSnapshot {
  running: boolean;
  /** running 时为插件服务器端口，未运行时为 null */
  port: number | null;
  config: unknown;
  bridge: {
    registrarRunning: boolean;
    bridgeRunning: boolean;
    bridgePort: number | null;
    tools: number;
    cxfcRegistered: boolean;
  };
}

/** 控制面依赖上下文：默认实现接线 launcher/toolBridge/config/logBuffer，测试可整体注入 mock */
export interface ControlContext {
  /** 实际控制面监听端口（/health 返回用；startControlServer listen 成功后回填） */
  controlPort: number;
  startRuntime(): Promise<{ port: number; bridge: boolean }>;
  stopRuntime(): Promise<void>;
  restartRuntime(): Promise<{ port: number; bridge: boolean }>;
  getStatus(): ControlStatusSnapshot;
  getConfig(): unknown;
  /** 校验已由路由层完成，此处只负责持久化并返回更新后的全量配置 */
  setConfig(partial: Record<string, unknown>): unknown;
  /** 环形缓冲现有日志（正序）；limit 为undefined时返回全部 */
  logRecent(limit?: number): string[];
  /** 订阅实时日志行，返回取消订阅函数（SSE 断开时必须调用防泄漏） */
  logSubscribe(listener: (line: string) => void): () => void;
}

/** 纯路由函数的返回结果：HTTP 层据此写响应 */
export interface ControlRouteResult {
  status: number;
  payload: unknown;
  /** 额外响应头（如 405 的 Allow） */
  headers?: Record<string, string>;
}

// ---------------------------------------------------------------------------
// 纯路由函数（无 IO，可单测）
// ---------------------------------------------------------------------------

/** 已知路径 → 允许的方法；不在表内 → 404，方法不符 → 405 */
const CONTROL_ROUTES: Record<string, readonly string[]> = {
  '/health': ['GET'],
  '/status': ['GET'],
  '/start': ['POST'],
  '/stop': ['POST'],
  '/restart': ['POST'],
  '/config': ['GET', 'PUT'],
  '/logs/recent': ['GET'],
  // GET /logs/stream 由 HTTP 层先行分流到 SSE；保留在表内以便 POST 等方法得到 405
  '/logs/stream': ['GET'],
};

/** /logs/recent 的 limit 上限（与环形缓冲容量一致） */
const LOG_LIMIT_MAX = 1000;

/** PUT /config 允许的字符串键 */
const CONFIG_STRING_KEYS: readonly string[] = ['python', 'sourceDir', 'backendUrl'];
/** PUT /config 允许的数字键（number ≥ 0） */
const CONFIG_NUMBER_KEYS: readonly string[] = ['port', 'controlPort'];

/** 解析 ?limit=N：非法/缺失返回 undefined（取全部），上限 1000 */
function parseLimit(query?: URLSearchParams): number | undefined {
  const raw = query?.get('limit');
  if (raw === null || raw === '') return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) return undefined;
  return Math.min(Math.floor(n), LOG_LIMIT_MAX);
}

/** PUT /config 请求体校验：非法键或类型错均拒绝，返回可写入的 patch */
function validateConfigPatch(
  body: JsonBody | null,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return { ok: false, error: '请求体必须为 JSON 对象' };
  }
  const patch: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(body)) {
    if (CONFIG_STRING_KEYS.includes(key)) {
      if (typeof value !== 'string') return { ok: false, error: `配置项 ${key} 必须为字符串` };
      patch[key] = value;
    } else if (CONFIG_NUMBER_KEYS.includes(key)) {
      if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
        return { ok: false, error: `配置项 ${key} 必须为不小于 0 的数字` };
      }
      patch[key] = value;
    } else if (key === 'autoStart') {
      if (typeof value !== 'boolean') return { ok: false, error: '配置项 autoStart 必须为布尔值' };
      patch.autoStart = value;
    } else {
      return { ok: false, error: `非法配置键: ${key}` };
    }
  }
  return { ok: true, value: patch };
}

/** 取尾部 N 行（limit 语义：最近 N 条） */
function tailLines(all: string[], limit?: number): string[] {
  if (limit === undefined) return all;
  return all.slice(Math.max(0, all.length - limit));
}

/**
 * 控制面纯路由处理：返回 {status, payload} 交由 HTTP 层写回。
 * start/stop/restart 的业务异常在此映射为 500 {ok:false,error}，
 * 其余意外异常由 HTTP 层整体 try/catch 兜底。
 */
export async function handleControlRoute(
  ctx: ControlContext,
  method: string,
  pathname: string,
  body: JsonBody | null,
  query?: URLSearchParams,
): Promise<ControlRouteResult> {
  const allowed = CONTROL_ROUTES[pathname];
  if (!allowed) {
    return { status: 404, payload: { ok: false, error: `未知路径: ${pathname}` } };
  }
  if (!allowed.includes(method)) {
    return {
      status: 405,
      payload: { ok: false, error: `方法 ${method} 不被 ${pathname} 支持` },
      headers: { Allow: allowed.join(', ') },
    };
  }

  switch (pathname) {
    case '/health':
      return { status: 200, payload: { ok: true, status: 'ok', service: 'cxo-neko-adapter', port: ctx.controlPort } };

    case '/status':
      return { status: 200, payload: ctx.getStatus() };

    case '/start':
      try {
        const r = await ctx.startRuntime();
        return { status: 200, payload: { ok: true, port: r.port, bridge: r.bridge } };
      } catch (err) {
        return { status: 500, payload: { ok: false, error: messageOf(err) } };
      }

    case '/stop':
      // 未运行时 ctx.stopRuntime 也正常返回（幂等，与 stopNekoRuntime 语义一致）
      try {
        await ctx.stopRuntime();
        return { status: 200, payload: { ok: true } };
      } catch (err) {
        return { status: 500, payload: { ok: false, error: messageOf(err) } };
      }

    case '/restart':
      try {
        const r = await ctx.restartRuntime();
        return { status: 200, payload: { ok: true, port: r.port, bridge: r.bridge } };
      } catch (err) {
        return { status: 500, payload: { ok: false, error: messageOf(err) } };
      }

    case '/config': {
      if (method === 'GET') return { status: 200, payload: ctx.getConfig() };
      const patch = validateConfigPatch(body);
      if (!patch.ok) return { status: 400, payload: { ok: false, error: patch.error } };
      return { status: 200, payload: ctx.setConfig(patch.value) };
    }

    case '/logs/recent': {
      const lines = ctx.logRecent(parseLimit(query));
      return { status: 200, payload: { lines } };
    }

    default:
      // GET /logs/stream 不会到达此处（HTTP 层分流）；其余已在上方 405/404 拦截
      return { status: 404, payload: { ok: false, error: `未知路径: ${pathname}` } };
  }
}

// ---------------------------------------------------------------------------
// SSE 日志流
// ---------------------------------------------------------------------------

export interface LogStreamOptions {
  /** 心跳间隔毫秒，默认 15000；测试可调小便于验证 */
  heartbeatMs?: number;
}

/**
 * GET /logs/stream 的 SSE 处理：
 *  1) 先补发环形缓冲现有日志（data 帧用 JSON 编码整行，规避日志行内换行破坏 SSE 帧）；
 *  2) 再订阅实时推送；
 *  3) 周期写 ": heartbeat" 注释帧防半死连接；
 *  4) 客户端断开（res close）时清理订阅与心跳定时器，防泄漏。
 */
export function streamRuntimeLogs(ctx: ControlContext, res: ServerResponse, options?: LogStreamOptions): void {
  const heartbeatMs = options?.heartbeatMs ?? 15_000;
  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-store',
    Connection: 'keep-alive',
  });
  // 1) 补发 recent（按任务语义：先补发，后订阅）
  for (const line of ctx.logRecent()) {
    res.write(`data: ${JSON.stringify(line)}\n\n`);
  }
  // 2) 实时订阅
  const unsubscribe = ctx.logSubscribe((line) => {
    try {
      res.write(`data: ${JSON.stringify(line)}\n\n`);
    } catch {
      /* 连接已断，由 close 回调统一清理 */
    }
  });
  // 3) 心跳
  const heartbeat = setInterval(() => {
    try {
      res.write(': heartbeat\n\n');
    } catch {
      /* ignore */
    }
  }, heartbeatMs);
  // 4) 断开清理
  res.on('close', () => {
    clearInterval(heartbeat);
    unsubscribe();
  });
}

// ---------------------------------------------------------------------------
// 默认上下文（真实接线）
// ---------------------------------------------------------------------------

/** 日志订阅分发器：setNekoLogSink 为单槽，控制面用分发器把每行投递给全部 SSE 订阅者 */
const logListeners = new Set<(line: string) => void>();
let logSinkInstalled = false;

function dispatchLogLine(line: string): void {
  // 快照迭代 + 单订阅者隔离：任一 SSE 写失败不影响其他订阅者与运行时日志链
  for (const fn of [...logListeners]) {
    try {
      fn(line);
    } catch {
      /* 单个订阅者异常忽略 */
    }
  }
}

function logSubscribe(listener: (line: string) => void): () => void {
  logListeners.add(listener);
  if (!logSinkInstalled) {
    logSinkInstalled = true;
    setNekoLogSink(dispatchLogLine);
  }
  return () => {
    logListeners.delete(listener);
  };
}

function logUninstall(): void {
  if (logSinkInstalled) {
    logSinkInstalled = false;
    setNekoLogSink(null);
  }
}

/** 默认 ctx：聚合 launcher 状态 + 工具桥状态，配置/日志直连 shared 模块 */
function buildDefaultContext(): ControlContext {
  return {
    controlPort: 0,
    startRuntime: () => startNekoRuntime(),
    stopRuntime: () => stopNekoRuntime(),
    restartRuntime: () => restartNekoFull(),
    getStatus: (): ControlStatusSnapshot => {
      const s = getNekoStatus();
      return { running: s.running, port: s.port, config: s.config, bridge: getNekoToolBridgeStatus() };
    },
    getConfig: () => getAll(),
    setConfig: (partial) => setConfig(partial as Partial<AdapterConfig>),
    logRecent: (limit) => tailLines(getRuntimeLogLines(), limit),
    logSubscribe,
  };
}

// ---------------------------------------------------------------------------
// 薄 HTTP 层
// ---------------------------------------------------------------------------

const CONTROL_PORT_MAX_RETRY = 50; // EADDRINUSE 时递增重试最多 +50
const MAX_BODY_BYTES = 1024 * 1024;

/** 请求体读取结果：空体 / 非法 JSON / 合法对象 三态区分 */
const EMPTY_BODY = Symbol('empty-body');
const BAD_BODY = Symbol('bad-body');
type BodyParseResult = JsonBody | typeof EMPTY_BODY | typeof BAD_BODY;

async function readBodyJson(req: IncomingMessage): Promise<BodyParseResult> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    const b = chunk as Buffer;
    size += b.length;
    if (size > MAX_BODY_BYTES) return BAD_BODY;
    chunks.push(b);
  }
  if (chunks.length === 0) return EMPTY_BODY;
  try {
    const parsed: unknown = JSON.parse(Buffer.concat(chunks).toString('utf-8'));
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return BAD_BODY;
    return parsed as JsonBody;
  } catch {
    return BAD_BODY;
  }
}

function writeJson(res: ServerResponse, status: number, payload: unknown, extraHeaders?: Record<string, string>): void {
  const data = JSON.stringify(payload);
  res.writeHead(status, { ...jsonPayload(data, status).headers, ...(extraHeaders ?? {}) });
  res.end(data);
}

/** 监听指定端口，成功后返回实际绑定端口（port=0 时由 OS 分配） */
function listenOn(server: HttpServer, port: number): Promise<number> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', () => {
      server.removeListener('error', reject);
      const addr = server.address() as AddressInfo;
      resolve(addr.port);
    });
  });
}

export interface ControlServerOptions {
  /** 覆盖配置中的 controlPort（CLI --port / 测试）；缺省读 config controlPort */
  port?: number;
  /** 覆盖默认 ctx（测试注入 mock）；缺省接线真实模块 */
  ctx?: ControlContext;
}

export interface ControlServerHandle {
  /** 实际监听端口（EADDRINUSE 递增后） */
  port: number;
  server: HttpServer;
  /** 停止接受新连接并销毁全部连接（含 SSE），触发订阅清理 */
  close(): Promise<void>;
}

/** 启动控制面服务器：仅绑定 127.0.0.1，EADDRINUSE 递增重试最多 +50 */
export async function startControlServer(options?: ControlServerOptions): Promise<ControlServerHandle> {
  const ctx = options?.ctx ?? buildDefaultContext();
  const basePort = options?.port ?? getConfig('controlPort');

  const server = createHttpServer((req, res) => {
    // 整体 try/catch：任何未预期异常都写 500，绝不让它成为 uncaughtException 崩溃进程
    //（对齐 toolBridge.ts 的整体兜底写法）
    void (async () => {
      try {
        let url: URL;
        try {
          url = new URL(req.url ?? '/', `http://127.0.0.1:${ctx.controlPort || basePort}`);
        } catch {
          return writeJson(res, 400, { ok: false, error: '非法请求路径' });
        }
        const method = (req.method ?? 'GET').toUpperCase();

        // SSE 流式端点独立分流（不走 JSON 路由）
        if (method === 'GET' && url.pathname === '/logs/stream') {
          return streamRuntimeLogs(ctx, res);
        }

        let body: JsonBody | null = null;
        if (method === 'POST' || method === 'PUT') {
          const parsed = await readBodyJson(req);
          if (parsed === BAD_BODY) {
            return writeJson(res, 400, { ok: false, error: '请求体不是合法 JSON 对象' });
          }
          body = parsed === EMPTY_BODY ? null : parsed;
        }

        const result = await handleControlRoute(ctx, method, url.pathname, body, url.searchParams);
        writeJson(res, result.status, result.payload, result.headers);
      } catch (err) {
        // 响应头已发出的场景（如客户端半途中断）只销毁连接，不再尝试写 JSON
        if (res.headersSent) {
          res.destroy();
          return;
        }
        try {
          writeJson(res, 500, { ok: false, error: `控制面内部错误: ${messageOf(err)}` });
        } catch {
          /* socket 已断，忽略 */
        }
      }
    })();
  });

  let actualPort = 0;
  let lastErr: unknown = null;
  // port=0 表示交给 OS 分配，只需一次尝试；递增重试仅用于固定基准端口
  const maxAttempt = basePort === 0 ? 0 : CONTROL_PORT_MAX_RETRY;
  for (let attempt = 0; attempt <= maxAttempt; attempt++) {
    const port = basePort + attempt;
    try {
      actualPort = await listenOn(server, port);
      break;
    } catch (err) {
      lastErr = err;
      if ((err as { code?: string }).code !== 'EADDRINUSE') throw err;
    }
  }
  if (!actualPort) {
    throw new Error(
      `控制面端口 ${basePort}..${basePort + CONTROL_PORT_MAX_RETRY} 均被占用（最后错误：${messageOf(lastErr)}）`,
    );
  }

  ctx.controlPort = actualPort;
  // 机器可读就绪行（供脚本/宿主探测）
  console.log(`[adapter] control listening on 127.0.0.1:${actualPort}`);

  return {
    port: actualPort,
    server,
    close: () =>
      new Promise<void>((resolve) => {
        // SSE 长连接会阻止 close 回调，主动销毁全部连接（res close → 订阅清理）
        server.close(() => resolve());
        server.closeAllConnections();
        logUninstall();
      }),
  };
}
