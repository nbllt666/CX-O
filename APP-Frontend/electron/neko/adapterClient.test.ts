// @vitest-environment node
/**
 * CXO-NekoAdapter 适配器客户端单测（Vitest，node 环境）
 * ============================================================================
 * 覆盖：拉起+health 就绪等待、health 超时、进程死亡报错、exit 广播不复拉、
 * 种子同步一次性语义（全默认/非默认逐键/部分失败不标记重试）、调用转发与
 * 错误映射、stop 先 /stop 再杀进程且超时升级 SIGKILL、SSE 馐线广播、
 * SSE 断线重连+recent 补发、并发 ensure 互斥、显式 adapterDir 优先、
 * 默认目录向上探测。依赖全部注入（spawn/fetch/config/logSink），不碰 electron。
 * ============================================================================
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import type { ChildProcess } from 'node:child_process';
import {
  ADAPTER_DEFAULTS,
  createAdapterClient,
  resolveAdapterDirDefault,
  type AdapterClient,
  type AdapterClientOptions,
} from './adapterClient';

// ---------------------------------------------------------------------------
// 测试基建：假子进程 / fetch 路由 / 临时适配器目录 / harness
// ---------------------------------------------------------------------------

/** 假子进程：记录 kill 调用；默认 SIGTERM 即退出，顽固场景由测试覆盖 kill */
class FakeChild {
  pid = 4321;
  exitCode: number | null = null;
  killed = false;
  stdout: null = null;
  stderr: null = null;
  killLog: string[] = [];
  private exitListeners: Array<(code: number | null, signal: NodeJS.Signals | null) => void> = [];
  private errorListeners: Array<(err: Error) => void> = [];

  on(event: string, listener: (...args: never[]) => void): this {
    if (event === 'exit') this.exitListeners.push(listener as (code: number | null, signal: NodeJS.Signals | null) => void);
    if (event === 'error') this.errorListeners.push(listener as (err: Error) => void);
    return this;
  }

  once(event: string, listener: (...args: never[]) => void): this {
    return this.on(event, listener);
  }

  emitExit(code: number | null, signal: NodeJS.Signals | null): void {
    this.exitCode = code;
    for (const l of [...this.exitListeners]) l(code, signal);
  }

  emitError(err: Error): void {
    for (const l of [...this.errorListeners]) l(err);
  }

  kill(signal?: NodeJS.Signals | number): boolean {
    this.killLog.push(String(signal));
    this.killed = true;
    if (signal === 'SIGKILL') this.emitExit(1, 'SIGKILL');
    else this.emitExit(0, typeof signal === 'string' ? signal : 'SIGTERM');
    return true;
  }
}

interface FetchCall {
  url: string;
  init?: RequestInit;
}

type FetchRoute = {
  match: (pathname: string, method: string) => boolean;
  handle: (init?: RequestInit) => Response | Promise<Response>;
};

const jsonResponse = (payload: unknown, status = 200): Response =>
  new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } });

/** 构造 SSE Response；hang=true 时流保持打开（reader 挂起），并暴露 controller 供 abort 联动关闭 */
function sseResponse(frames: string[], opts?: { hang?: boolean }): Response {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
      for (const f of frames) c.enqueue(encoder.encode(f));
      if (!opts?.hang) c.close();
    },
  });
  const resp = new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
  (resp as unknown as { __controller?: ReadableStreamDefaultController<Uint8Array> }).__controller = controller;
  return resp;
}

/** 适配器 /status 默认聚合快照 */
const SNAPSHOT = {
  running: true,
  port: 48999,
  config: {
    python: ADAPTER_DEFAULTS.python,
    sourceDir: ADAPTER_DEFAULTS.sourceDir,
    port: ADAPTER_DEFAULTS.port,
    backendUrl: 'http://127.0.0.1:8000',
    controlPort: 48920,
    autoStart: false,
  },
  bridge: { registrarRunning: true, bridgeRunning: true, bridgePort: 48921, tools: 3, cxfcRegistered: true },
};

/** 临时适配器目录夹具：含 dist/index.js，供 spawnChild 入口存在性检查 */
function makeAdapterDirFixture(): string {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cxo-adapter-fixture-'));
  fs.mkdirSync(path.join(dir, 'dist'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'dist', 'index.js'), '// fixture');
  return dir;
}

interface Harness {
  client: AdapterClient;
  config: Record<string, string>;
  sinkLines: string[];
  spawnCalls: Array<{ cmd: string; args: readonly string[]; opts: unknown }>;
  children: FakeChild[];
  fetchCalls: FetchCall[];
  setRoute: (route: FetchRoute) => void;
  /** fetchCalls 的 pathname+search 快捷读取 */
  pathOf: (call: FetchCall) => string;
}

function makeHarness(opts?: {
  config?: Record<string, string>;
  routes?: FetchRoute[];
  clientOverrides?: Partial<AdapterClientOptions>;
}): Harness {
  const config: Record<string, string> = { ...(opts?.config ?? {}) };
  const sinkLines: string[] = [];
  const spawnCalls: Harness['spawnCalls'] = [];
  const children: FakeChild[] = [];
  const fetchCalls: FetchCall[] = [];
  const routes: FetchRoute[] = [...(opts?.routes ?? [])];
  const fixtures: string[] = [];

  // 默认控制面路由（测试未覆盖的请求落此处，保证 SSE 循环等后台流程可运行）
  const defaultRoutes: FetchRoute[] = [
    {
      match: (p, m) => p === '/health' && m === 'GET',
      handle: () => jsonResponse({ ok: true, status: 'ok', service: 'cxo-neko-adapter', port: 48920 }),
    },
    { match: (p) => p === '/status', handle: () => jsonResponse(SNAPSHOT) },
    { match: (p) => p === '/start', handle: () => jsonResponse({ ok: true, port: SNAPSHOT.port, bridge: true }) },
    { match: (p) => p === '/stop', handle: () => jsonResponse({ ok: true }) },
    { match: (p) => p === '/restart', handle: () => jsonResponse({ ok: true, port: SNAPSHOT.port, bridge: true }) },
    {
      match: (p) => p === '/config',
      handle: (init) =>
        jsonResponse({
          ...SNAPSHOT.config,
          ...(init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {}),
        }),
    },
    { match: (p) => p === '/logs/recent', handle: () => jsonResponse({ lines: [] }) },
    {
      // 默认 SSE：挂起流保持 reader 等待；abort（stop）时关闭流模拟服务端断开
      match: (p) => p === '/logs/stream',
      handle: (init) => {
        const resp = sseResponse([], { hang: true });
        init?.signal?.addEventListener('abort', () => {
          try {
            (resp as unknown as { __controller?: ReadableStreamDefaultController<Uint8Array> }).__controller?.close();
          } catch {
            /* 已关闭忽略 */
          }
        });
        return resp;
      },
    },
  ];

  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit): Promise<Response> => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const parsed = new URL(url);
    const method = (init?.method ?? 'GET').toUpperCase();
    fetchCalls.push({ url, init });
    for (const r of [...routes, ...defaultRoutes]) {
      if (r.match(parsed.pathname, method)) return await r.handle(init);
    }
    return jsonResponse({ ok: false, error: `未mock的请求: ${parsed.pathname}` }, 404);
  }) as unknown as typeof fetch;

  const spawnImpl = ((_cmd: string, args: readonly string[], spawnOpts: unknown) => {
    spawnCalls.push({ cmd: _cmd, args, opts: spawnOpts });
    const child = new FakeChild();
    children.push(child);
    return child as unknown as ChildProcess;
  }) as unknown as typeof import('node:child_process')['spawn'];

  const adapterDirFixture = makeAdapterDirFixture();
  fixtures.push(adapterDirFixture);

  const client = createAdapterClient({
    getConfig: (k) => (k in config ? config[k] : null),
    setConfig: (k, v) => {
      config[k] = v;
    },
    resolveAdapterDir: () => adapterDirFixture,
    spawnImpl,
    fetchImpl,
    logSink: (line) => sinkLines.push(line),
    // 默认收紧各超时，避免测试拖慢
    stopTimeoutMs: 10,
    reconnectBaseMs: 5,
    reconnectMaxMs: 10,
    ...(opts?.clientOverrides ?? {}),
  });

  cleanups.push(async () => {
    try {
      await client.stopAdapterProcess();
    } catch {
      /* ignore */
    }
    for (const dir of fixtures) {
      try {
        fs.rmSync(dir, { recursive: true, force: true });
      } catch {
        /* ignore */
      }
    }
  });

  return {
    client,
    config,
    sinkLines,
    spawnCalls,
    children,
    fetchCalls,
    setRoute: (route) => routes.push(route),
    pathOf: (call) => {
      const u = new URL(call.url);
      return `${u.pathname}${u.search}`;
    },
  };
}

// 全局清理：stop 客户端（终止 SSE 循环/子进程）并删除临时目录
const cleanups: Array<() => Promise<void> | void> = [];
afterEach(async () => {
  for (const fn of [...cleanups].reverse()) {
    await fn();
  }
  cleanups.length = 0;
});

// ---------------------------------------------------------------------------
// 用例
// ---------------------------------------------------------------------------

describe('ensureAdapter：拉起与就绪等待', () => {
  it('spawn 参数正确且 /health 就绪后完成（node + dist/index.js + --port + cwd）', async () => {
    const h = makeHarness();
    await h.client.ensureAdapter();

    expect(h.spawnCalls).toHaveLength(1);
    const call = h.spawnCalls[0];
    expect(call.cmd).toBe('node');
    expect(call.args).toEqual(['dist/index.js', '--port', '48920']);
    const spawnOpts = call.opts as { cwd: string; windowsHide: boolean };
    expect(spawnOpts.windowsHide).toBe(true);
    expect(fs.existsSync(path.join(spawnOpts.cwd, 'dist', 'index.js'))).toBe(true);
    expect(h.client.isAdapterRunning()).toBe(true);
    expect(h.fetchCalls.some((c) => h.pathOf(c) === '/health')).toBe(true);
  });

  it('/health 持续失败时轮询重试直至超时报错', async () => {
    const h = makeHarness({
      routes: [{ match: (p) => p === '/health', handle: () => jsonResponse({ ok: false, error: 'x' }, 500) }],
      clientOverrides: { healthTimeoutMs: 60, pollIntervalMs: 5 },
    });
    await expect(h.client.ensureAdapter()).rejects.toThrow(/未就绪/);
    expect(h.fetchCalls.filter((c) => h.pathOf(c) === '/health').length).toBeGreaterThan(1);
  });

  it('health 轮询期间适配器进程死亡 → 立即报错「未存活」', async () => {
    const h = makeHarness({
      routes: [
        {
          match: (p) => p === '/health',
          handle: () => {
            h.children[0]?.emitExit(1, null); // 模拟启动即退出
            return jsonResponse({ ok: false, error: 'x' }, 500);
          },
        },
      ],
      clientOverrides: { healthTimeoutMs: 5000, pollIntervalMs: 5 },
    });
    await expect(h.client.ensureAdapter()).rejects.toThrow(/未存活/);
  });

  it('适配器进程意外退出 → logSink 广播退出信息且不自动重拉', async () => {
    const h = makeHarness();
    await h.client.ensureAdapter();
    h.children[0].emitExit(3, 'SIGTERM');
    expect(h.sinkLines).toContain('[neko] 适配器进程退出 code=3 signal=SIGTERM');
    expect(h.client.isAdapterRunning()).toBe(false);
    expect(h.spawnCalls).toHaveLength(1);
  });

  it('并发 ensureAdapter 互斥：共享同一 Promise，仅 spawn 一次', async () => {
    const h = makeHarness();
    const [a, b] = await Promise.all([h.client.ensureAdapter(), h.client.ensureAdapter()]);
    expect(a).toBe(b);
    expect(h.spawnCalls).toHaveLength(1);
  });

  it('显式配置 neko.adapterDir 优先于自动探测', async () => {
    const customDir = makeAdapterDirFixture();
    const h = makeHarness({ config: { 'neko.adapterDir': customDir } });
    await h.client.ensureAdapter();
    const spawnOpts = h.spawnCalls[0].opts as { cwd: string };
    expect(spawnOpts.cwd).toBe(customDir);
  });

  it('默认目录解析：从模块位置向上探测命中仓库内 CXO-NekoAdapter', () => {
    const resolved = resolveAdapterDirDefault();
    expect(resolved).toMatch(/[\\/]CXO-NekoAdapter$/);
    expect(fs.existsSync(resolved)).toBe(true);
  });
});

describe('存量配置种子同步（一次性）', () => {
  it('非默认四键逐键 PUT 且成功后标记 seeded', async () => {
    const h = makeHarness({
      config: {
        'neko.python': 'C:\\py\\python.exe',
        'neko.sourceDir': 'D:\\N.E.K.O',
        'neko.port': '48999',
        'neko.autoStart': 'true',
      },
    });
    await h.client.ensureAdapter();

    const putBodies = h.fetchCalls
      .filter((c) => h.pathOf(c) === '/config' && c.init?.method === 'PUT')
      .map((c) => JSON.parse(String(c.init?.body)) as Record<string, unknown>);
    expect(putBodies).toEqual([
      { python: 'C:\\py\\python.exe' },
      { sourceDir: 'D:\\N.E.K.O' },
      { port: 48999 },
      { autoStart: true },
    ]);
    expect(h.config['neko.seeded']).toBe('true');
  });

  it('存量值均为默认时零 PUT 且直接标记 seeded', async () => {
    const h = makeHarness({
      config: {
        'neko.python': ADAPTER_DEFAULTS.python,
        'neko.sourceDir': ADAPTER_DEFAULTS.sourceDir,
        'neko.port': String(ADAPTER_DEFAULTS.port),
        'neko.autoStart': 'false',
      },
    });
    await h.client.ensureAdapter();
    expect(h.fetchCalls.some((c) => c.init?.method === 'PUT')).toBe(false);
    expect(h.config['neko.seeded']).toBe('true');
  });

  it('部分 PUT 失败不标记 seeded，下次 ensure 重试', async () => {
    let failSourceDir = true;
    const h = makeHarness({
      config: { 'neko.python': 'C:\\py\\python.exe', 'neko.sourceDir': 'D:\\N.E.K.O' },
      routes: [
        {
          match: (p) => p === '/config',
          handle: (init) => {
            const body = (init?.body ? JSON.parse(String(init.body)) : {}) as Record<string, unknown>;
            if ('sourceDir' in body && failSourceDir) return jsonResponse({ ok: false, error: '磁盘忙' }, 500);
            return jsonResponse({ ...SNAPSHOT.config, ...body });
          },
        },
      ],
    });
    await h.client.ensureAdapter();
    expect(h.config['neko.seeded']).not.toBe('true'); // 未标记（下次启动重试）
    expect(h.sinkLines.some((l) => l.includes('种子同步配置 sourceDir 失败'))).toBe(true);

    failSourceDir = false; // 故障恢复
    await h.client.ensureAdapter(); // 重试
    expect(h.config['neko.seeded']).toBe('true');
  });
});

describe('控制面调用转发与错误映射', () => {
  it('start/restart/stop 成功转发并映射 port', async () => {
    const h = makeHarness();
    await expect(h.client.start()).resolves.toEqual({ ok: true, port: 48999 });
    await expect(h.client.restart()).resolves.toEqual({ ok: true, port: 48999 });
    await expect(h.client.stop()).resolves.toEqual({ ok: true });
  });

  it('控制面 500 响应提取 body.error 映射为 {ok:false,error}', async () => {
    const h = makeHarness({
      routes: [{ match: (p) => p === '/start', handle: () => jsonResponse({ ok: false, error: 'python 不存在' }, 500) }],
    });
    await expect(h.client.start()).resolves.toEqual({ ok: false, error: 'python 不存在' });
  });

  it('网络层异常（连接拒绝等）映射为 {ok:false,error}', async () => {
    const h = makeHarness({
      routes: [
        {
          match: (p) => p === '/stop',
          handle: () => {
            throw new Error('ECONNREFUSED 127.0.0.1:48920');
          },
        },
      ],
    });
    await expect(h.client.stop()).resolves.toEqual({ ok: false, error: 'ECONNREFUSED 127.0.0.1:48920' });
  });
});

describe('stopAdapterProcess：先停运行时再杀进程', () => {
  it('顺序：POST /stop → SIGTERM → 超时未退 → SIGKILL', async () => {
    const h = makeHarness({ clientOverrides: { stopTimeoutMs: 15 } });
    await h.client.ensureAdapter();

    const events: string[] = [];
    h.setRoute({
      match: (p, m) => p === '/stop' && m === 'POST',
      handle: () => {
        events.push('post:/stop');
        return jsonResponse({ ok: true });
      },
    });
    // 覆盖为「顽固子进程」：SIGTERM 不退出，仅 SIGKILL 退出
    const child = h.children[0];
    child.kill = (signal?: NodeJS.Signals | number): boolean => {
      events.push(`kill:${String(signal)}`);
      child.killed = true;
      if (signal === 'SIGKILL') child.emitExit(1, 'SIGKILL');
      return true;
    };

    await h.client.stopAdapterProcess();
    expect(events).toEqual(['post:/stop', 'kill:SIGTERM', 'kill:SIGKILL']);
    expect(h.client.isAdapterRunning()).toBe(false);
  });

  it('无子进程时仅尝试 POST /stop 且不抛错', async () => {
    const h = makeHarness();
    await expect(h.client.stopAdapterProcess()).resolves.toBeUndefined();
    expect(h.fetchCalls.some((c) => h.pathOf(c) === '/stop' && c.init?.method === 'POST')).toBe(true);
  });
});

describe('SSE 日志流', () => {
  it('首连逐行解析广播：data 帧解码、注释帧忽略', async () => {
    const h = makeHarness({
      routes: [
        {
          match: (p) => p === '/logs/stream',
          handle: () => sseResponse(['data: "hello"\n\n', ': heartbeat\n\n', 'data: "world"\n\n'], { hang: true }),
        },
      ],
    });
    await h.client.ensureAdapter();
    await vi.waitFor(
      () => {
        expect(h.sinkLines).toContain('hello');
        expect(h.sinkLines).toContain('world');
      },
      { timeout: 2000 },
    );
    expect(h.sinkLines).not.toContain('heartbeat');
  });

  it('断线自动重连：重连先 GET /logs/recent?limit=200 补发再续流', async () => {
    let streamCount = 0;
    const h = makeHarness({
      routes: [
        { match: (p) => p === '/logs/recent', handle: () => jsonResponse({ lines: ['r1', 'r2'] }) },
        {
          match: (p) => p === '/logs/stream',
          handle: (init) => {
            streamCount++;
            if (streamCount === 1) return sseResponse([]); // 首连立即断开
            const resp = sseResponse(['data: "live"\n\n'], { hang: true });
            init?.signal?.addEventListener('abort', () => {
              try {
                (resp as unknown as { __controller?: ReadableStreamDefaultController<Uint8Array> }).__controller?.close();
              } catch {
                /* ignore */
              }
            });
            return resp;
          },
        },
      ],
      clientOverrides: { reconnectBaseMs: 5, reconnectMaxMs: 10 },
    });
    await h.client.ensureAdapter();
    await vi.waitFor(() => expect(h.sinkLines).toContain('live'), { timeout: 2000 });

    // 顺序断言：首连 stream → 断开后 recent 补发 → 二次 stream 续流
    const paths = h.fetchCalls.map((c) => h.pathOf(c));
    const firstStream = paths.indexOf('/logs/stream');
    const recentIdx = paths.indexOf('/logs/recent?limit=200');
    const secondStream = paths.findIndex((p, i) => i > firstStream && p === '/logs/stream');
    expect(firstStream).toBeGreaterThanOrEqual(0);
    expect(recentIdx).toBeGreaterThan(firstStream);
    expect(secondStream).toBeGreaterThan(recentIdx);
    expect(h.sinkLines).toEqual(expect.arrayContaining(['r1', 'r2', 'live']));
  });
});
