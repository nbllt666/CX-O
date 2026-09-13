/**
 * 控制面 HTTP API 测试
 * ============================================================================
 * 覆盖：
 *  - handleControlRoute 纯路由：全部端点 / 校验失败 / 幂等 / 404 / 405
 *  - streamRuntimeLogs SSE：真实 http server 起临时端口，验证补发 recent、
 *    实时推送、心跳、客户端断开后的订阅清理（防泄漏）
 *  - startControlServer 集成：真实 config 接线（数据目录经
 *    CXO_NEKO_ADAPTER_DATA_DIR 环境变量隔离到临时目录），PUT /config 持久化
 *
 * 注意：paths.ts 在模块加载时固化 dataDir，因此业务模块统一在设置环境变量后
 * 动态 import，避免污染真实 data/ 目录（vi.mock 不适用于动态固化常量）。
 * ============================================================================
 */
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import * as fs from 'node:fs';
import * as http from 'node:http';
import * as net from 'node:net';
import * as os from 'node:os';
import * as path from 'node:path';
import type { ControlContext } from '../src/control/server';

// ── 动态加载被测模块（在 env 设置之后） ──
type ServerModule = typeof import('../src/control/server');
let server: ServerModule;
let tmpDataDir: string;

beforeAll(async () => {
  tmpDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cxo-neko-control-test-'));
  process.env.CXO_NEKO_ADAPTER_DATA_DIR = tmpDataDir;
  server = await import('../src/control/server');
});

afterAll(async () => {
  delete process.env.CXO_NEKO_ADAPTER_DATA_DIR;
  fs.rmSync(tmpDataDir, { recursive: true, force: true });
});

// ── mock ctx 构造 ──

const MOCK_CONFIG = {
  python: 'python',
  sourceDir: 'C:\\N.E.K.O-main',
  port: 48916,
  backendUrl: 'http://127.0.0.1:8000',
  controlPort: 48920,
  autoStart: false,
};

const MOCK_BRIDGE = { registrarRunning: false, bridgeRunning: false, bridgePort: null, tools: 0, cxfcRegistered: false };

interface MockCalls {
  start: number;
  stop: number;
  restart: number;
  setConfig: unknown[];
}

/** 构造 mock ctx（不 spawn 真 python），calls 记录各方法调用次数便于断言 */
function makeCtx(overrides: Partial<ControlContext> = {}): { ctx: ControlContext; calls: MockCalls } {
  const calls: MockCalls = { start: 0, stop: 0, restart: 0, setConfig: [] };
  const ctx: ControlContext = {
    controlPort: 48920,
    startRuntime: async () => {
      calls.start++;
      return { port: 48916, bridge: true };
    },
    stopRuntime: async () => {
      calls.stop++;
    },
    restartRuntime: async () => {
      calls.restart++;
      return { port: 48917, bridge: false };
    },
    getStatus: () => ({ running: false, port: null, config: { ...MOCK_CONFIG, autoStart: undefined }, bridge: { ...MOCK_BRIDGE } }),
    getConfig: () => ({ ...MOCK_CONFIG }),
    setConfig: (partial) => {
      calls.setConfig.push(partial);
      return { ...MOCK_CONFIG, ...partial };
    },
    logRecent: (limit) => (limit === undefined ? ['l1', 'l2', 'l3'] : ['l1', 'l2', 'l3'].slice(-limit)),
    logSubscribe: () => () => undefined,
    ...overrides,
  };
  return { ctx, calls };
}

// ── HTTP 辅助（用于真实 server 集成用例） ──

interface HttpResult {
  status: number;
  body: Record<string, unknown>;
  headers: http.IncomingHttpHeaders;
}

function httpRequestJson(port: number, method: string, reqPath: string, body: unknown): Promise<HttpResult> {
  return new Promise((resolve, reject) => {
    const data = body === null || body === undefined ? null : JSON.stringify(body);
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        method,
        path: reqPath,
        headers: data ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {},
      },
      (res) => {
        let raw = '';
        res.setEncoding('utf-8');
        res.on('data', (c) => (raw += c));
        res.on('end', () => {
          try {
            resolve({ status: res.statusCode ?? 0, body: JSON.parse(raw) as Record<string, unknown>, headers: res.headers });
          } catch (e) {
            reject(e);
          }
        });
      },
    );
    req.on('error', reject);
    if (data) req.write(data);
    req.end();
  });
}

// ═══════════════════════════════════════════════════════════
// 纯路由：handleControlRoute
// ═══════════════════════════════════════════════════════════

describe('handleControlRoute', () => {
  it('GET /health 返回 200 与服务标识、实际控制面端口', async () => {
    const { ctx } = makeCtx({ controlPort: 48921 });
    const r = await server.handleControlRoute(ctx, 'GET', '/health', null);
    expect(r.status).toBe(200);
    expect(r.payload).toEqual({ ok: true, status: 'ok', service: 'cxo-neko-adapter', port: 48921 });
  });

  it('GET /status 返回 launcher 聚合快照', async () => {
    const { ctx } = makeCtx();
    const r = await server.handleControlRoute(ctx, 'GET', '/status', null);
    expect(r.status).toBe(200);
    expect(r.payload).toMatchObject({ running: false, port: null, bridge: MOCK_BRIDGE });
  });

  it('POST /start 成功返回 port/bridge；失败映射 500', async () => {
    const { ctx, calls } = makeCtx();
    const ok = await server.handleControlRoute(ctx, 'POST', '/start', null);
    expect(ok.status).toBe(200);
    expect(ok.payload).toEqual({ ok: true, port: 48916, bridge: true });
    expect(calls.start).toBe(1);

    const failCtx = makeCtx({ startRuntime: async () => { throw new Error('python 不存在'); } }).ctx;
    const bad = await server.handleControlRoute(failCtx, 'POST', '/start', null);
    expect(bad.status).toBe(500);
    expect(bad.payload).toEqual({ ok: false, error: 'python 不存在' });
  });

  it('POST /stop 幂等成功（未运行也返回 200）；异常映射 500', async () => {
    const { ctx, calls } = makeCtx();
    const r1 = await server.handleControlRoute(ctx, 'POST', '/stop', null);
    const r2 = await server.handleControlRoute(ctx, 'POST', '/stop', null);
    expect(r1.status).toBe(200);
    expect(r1.payload).toEqual({ ok: true });
    expect(r2.status).toBe(200);
    expect(calls.stop).toBe(2);

    const failCtx = makeCtx({ stopRuntime: async () => { throw new Error('kill failed'); } }).ctx;
    const bad = await server.handleControlRoute(failCtx, 'POST', '/stop', null);
    expect(bad.status).toBe(500);
    expect(bad.payload).toEqual({ ok: false, error: 'kill failed' });
  });

  it('POST /restart 成功返回 port/bridge；失败映射 500', async () => {
    const { ctx, calls } = makeCtx();
    const ok = await server.handleControlRoute(ctx, 'POST', '/restart', null);
    expect(ok.status).toBe(200);
    expect(ok.payload).toEqual({ ok: true, port: 48917, bridge: false });
    expect(calls.restart).toBe(1);

    const failCtx = makeCtx({ restartRuntime: async () => { throw new Error('重启失败'); } }).ctx;
    const bad = await server.handleControlRoute(failCtx, 'POST', '/restart', null);
    expect(bad.status).toBe(500);
  });

  it('GET /config 返回全量配置', async () => {
    const { ctx } = makeCtx();
    const r = await server.handleControlRoute(ctx, 'GET', '/config', null);
    expect(r.status).toBe(200);
    expect(r.payload).toEqual(MOCK_CONFIG);
  });

  it('PUT /config 合法 patch 调用 setConfig 并返回更新后全量配置', async () => {
    const { ctx, calls } = makeCtx();
    const r = await server.handleControlRoute(ctx, 'PUT', '/config', { port: 48999, backendUrl: 'http://127.0.0.1:9000' });
    expect(r.status).toBe(200);
    expect(r.payload).toEqual({ ...MOCK_CONFIG, port: 48999, backendUrl: 'http://127.0.0.1:9000' });
    expect(calls.setConfig[0]).toEqual({ port: 48999, backendUrl: 'http://127.0.0.1:9000' });
  });

  it('PUT /config 校验失败：非法键 / 类型错 / 负数端口 / 非对象体 → 400', async () => {
    const { ctx, calls } = makeCtx();
    const cases: Array<[Record<string, unknown> | null, string]> = [
      [{ hacker: 1 }, '非法配置键'],
      [{ python: 123 }, 'python 必须为字符串'],
      [{ sourceDir: null }, 'sourceDir 必须为字符串'],
      [{ backendUrl: [] }, 'backendUrl 必须为字符串'],
      [{ port: -1 }, 'port 必须为不小于 0 的数字'],
      [{ port: '48916' }, 'port 必须为不小于 0 的数字'],
      [{ controlPort: Number.POSITIVE_INFINITY }, 'controlPort 必须为不小于 0 的数字'],
      [{ autoStart: 'yes' }, 'autoStart 必须为布尔值'],
    ];
    for (const [body, keyword] of cases) {
      const r = await server.handleControlRoute(ctx, 'PUT', '/config', body as never);
      expect(r.status, `body=${JSON.stringify(body)}`).toBe(400);
      expect((r.payload as { error: string }).error).toContain(keyword);
    }
    // 非对象体（null）同样 400
    const nullBody = await server.handleControlRoute(ctx, 'PUT', '/config', null);
    expect(nullBody.status).toBe(400);
    // 校验失败不得触达 setConfig
    expect(calls.setConfig).toHaveLength(0);
  });

  it('GET /logs/recent 返回全部行；?limit=N 取最近 N 行；limit 截断 1000', async () => {
    const { ctx } = makeCtx({ logRecent: (limit) => (limit === undefined ? ['l1', 'l2', 'l3'] : ['l1', 'l2', 'l3'].slice(-limit)) });
    const all = await server.handleControlRoute(ctx, 'GET', '/logs/recent', null);
    expect(all.status).toBe(200);
    expect(all.payload).toEqual({ lines: ['l1', 'l2', 'l3'] });

    const limited = await server.handleControlRoute(ctx, 'GET', '/logs/recent', null, new URLSearchParams('limit=2'));
    expect(limited.payload).toEqual({ lines: ['l2', 'l3'] });

    // limit 超上限被截到 1000（以收到的 limit 值断言）
    let received: number | undefined = undefined;
    const spyCtx = makeCtx({
      logRecent: (limit) => {
        received = limit;
        return [];
      },
    }).ctx;
    await server.handleControlRoute(spyCtx, 'GET', '/logs/recent', null, new URLSearchParams('limit=5000'));
    expect(received).toBe(1000);
    // 非法 limit 回落全部
    await server.handleControlRoute(spyCtx, 'GET', '/logs/recent', null, new URLSearchParams('limit=abc'));
    expect(received).toBeUndefined();
  });

  it('方法不符 → 405（带 Allow 头）；未知路径 → 404', async () => {
    const { ctx } = makeCtx();
    const getStart = await server.handleControlRoute(ctx, 'GET', '/start', null);
    expect(getStart.status).toBe(405);
    expect(getStart.headers?.Allow).toBe('POST');

    const postHealth = await server.handleControlRoute(ctx, 'POST', '/health', null);
    expect(postHealth.status).toBe(405);

    const delConfig = await server.handleControlRoute(ctx, 'DELETE', '/config', null);
    expect(delConfig.status).toBe(405);
    expect(delConfig.headers?.Allow).toBe('GET, PUT');

    const postStream = await server.handleControlRoute(ctx, 'POST', '/logs/stream', null);
    expect(postStream.status).toBe(405);

    const notFound = await server.handleControlRoute(ctx, 'GET', '/nope', null);
    expect(notFound.status).toBe(404);
  });
});

// ═══════════════════════════════════════════════════════════
// SSE：streamRuntimeLogs（真实 http server 临时端口）
// ═══════════════════════════════════════════════════════════

describe('streamRuntimeLogs（SSE）', () => {
  it('补发 recent → 实时推送 → 心跳 → 客户端断开后清理订阅', async () => {
    let listener: ((line: string) => void) | null = null;
    let unsubscribed = false;
    const { ctx } = makeCtx({
      logRecent: () => ['old-1', 'old-2'],
      logSubscribe: (l) => {
        listener = l;
        return () => {
          unsubscribed = true;
        };
      },
    });

    const srv = http.createServer((req, res) => server.streamRuntimeLogs(ctx, res, { heartbeatMs: 50 }));
    await new Promise<void>((resolve) => srv.listen(0, '127.0.0.1', () => resolve()));
    const addr = srv.address() as net.AddressInfo;

    const chunks: string[] = [];
    let sseContentType = '';
    const clientReq = http.get(`http://127.0.0.1:${addr.port}/logs/stream`, (res) => {
      sseContentType = String(res.headers['content-type'] ?? '');
      res.setEncoding('utf-8');
      res.on('data', (c) => chunks.push(c));
      res.on('error', () => undefined); // 客户端主动断开时服务端写回会触发读侧错误，忽略
    });

    const waitFor = async (pred: () => boolean, what: string, timeoutMs = 5000): Promise<void> => {
      const started = Date.now();
      while (!pred()) {
        if (Date.now() - started > timeoutMs) {
          throw new Error(`等待超时：${what}，已收帧: ${JSON.stringify(chunks.join(''))}`);
        }
        await new Promise((r) => setTimeout(r, 15));
      }
    };
    const received = () => chunks.join('');

    // 1) 先补发 recent
    await waitFor(() => received().includes('data: "old-1"') && received().includes('data: "old-2"'), 'recent 补发');
    // SSE 头（响应头不在 body 流中，从 headers 检查）
    expect(sseContentType).toContain('text/event-stream');

    // 2) 实时推送
    listener!('new-line');
    await waitFor(() => received().includes('data: "new-line"'), '实时推送');

    // 3) 心跳帧
    await waitFor(() => received().includes(': heartbeat'), '心跳');

    // 4) 客户端断开 → 服务端必须清理订阅（防泄漏）
    clientReq.destroy();
    await waitFor(() => unsubscribed, '断开后清理订阅', 2000);
    expect(unsubscribed).toBe(true);

    await new Promise<void>((resolve) => srv.close(() => resolve()));
    srv.closeAllConnections();
  });
});

// ═══════════════════════════════════════════════════════════
// 集成：startControlServer（真实 config 接线 + 临时 data 目录）
// ═══════════════════════════════════════════════════════════

describe('startControlServer 集成（临时数据目录）', () => {
  it('/health 报告实际端口；PUT /config 持久化到临时目录；非法 PUT 400；404/405 正确', async () => {
    const handle = await server.startControlServer({ port: 0 });
    try {
      // /health
      const health = await httpRequestJson(handle.port, 'GET', '/health', null);
      expect(health.status).toBe(200);
      expect(health.body).toEqual({ ok: true, status: 'ok', service: 'cxo-neko-adapter', port: handle.port });
      expect(health.headers['content-type']).toContain('application/json');

      // /status（未启动运行时，running=false）
      const status = await httpRequestJson(handle.port, 'GET', '/status', null);
      expect(status.status).toBe(200);
      expect(status.body).toMatchObject({ running: false, port: null, bridge: expect.objectContaining({ registrarRunning: false }) });

      // PUT /config 合法 → 200 全量 + 磁盘持久化（写入临时目录）
      const put = await httpRequestJson(handle.port, 'PUT', '/config', { port: 48777 });
      expect(put.status).toBe(200);
      expect(put.body).toMatchObject({ port: 48777, controlPort: 48920 });
      const disk = JSON.parse(fs.readFileSync(path.join(tmpDataDir, 'config.json'), 'utf-8')) as Record<string, unknown>;
      expect(disk.port).toBe(48777);

      // PUT /config 非法 → 400
      const bad = await httpRequestJson(handle.port, 'PUT', '/config', { port: -1 });
      expect(bad.status).toBe(400);
      expect(bad.body).toMatchObject({ ok: false });

      // POST /start 带非法 JSON body → 400（JSON 解析失败）
      const badJson = await new Promise<HttpResult>((resolve, reject) => {
        const req = http.request(
          { host: '127.0.0.1', port: handle.port, method: 'POST', path: '/start', headers: { 'Content-Type': 'application/json' } },
          (res) => {
            let raw = '';
            res.setEncoding('utf-8');
            res.on('data', (c) => (raw += c));
            res.on('end', () => resolve({ status: res.statusCode ?? 0, body: JSON.parse(raw) as Record<string, unknown>, headers: res.headers }));
          },
        );
        req.on('error', reject);
        req.write('{not-json');
        req.end();
      });
      expect(badJson.status).toBe(400);

      // 404 / 405
      const notFound = await httpRequestJson(handle.port, 'GET', '/nope', null);
      expect(notFound.status).toBe(404);
      const notAllowed = await httpRequestJson(handle.port, 'GET', '/start', null);
      expect(notAllowed.status).toBe(405);
      expect(notAllowed.headers.allow).toBe('POST');
    } finally {
      await handle.close();
    }
  });
});
