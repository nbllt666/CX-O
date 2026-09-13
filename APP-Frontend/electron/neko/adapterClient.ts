/**
 * CXO-NekoAdapter 独立适配器客户端（Electron 主进程）
 * ============================================================================
 * 背景：原主进程内嵌的 Neko 运行时（neko/launcher.ts + neko/toolBridge*.ts）已
 *   迁出为独立适配器项目 CXO-NekoAdapter（`node dist/index.js --port <n>` 启动
 *   控制面 HTTP，仅绑 127.0.0.1）。本文件把主进程侧瘦身为该适配器的纯客户端：
 *   - 拉起/停止适配器进程（spawn 系统 node，/health 轮询就绪 250ms×10s）
 *   - 控制面 API 统一封装（/health /status /start /stop /restart /config，
 *     15s 超时，错误统一 {ok:false,error}，不抛出）
 *   - 存量 electron 配置一次性种子同步（neko.seeded 标记；任一 PUT 失败不标记，
 *     下次启动重试）
 *   - SSE 日志订阅（/logs/stream）：逐行经 logSink 广播；断线指数退避重连
 *     （1s→8s 封顶，无限重试，应用退出时停止），重连成功先 GET /logs/recent
 *     补发再续流
 *   - 适配器进程 exit 事件经 logSink 广播（不自动重拉）
 *
 * 可测性：本文件不 import electron——getConfig/setConfig/resolveAdapterDir/
 *   spawnImpl/fetchImpl/logSink 及各超时参数全部经 createAdapterClient(options)
 *   注入；electron 侧单例由 neko/ipc.ts 用真实依赖构造（getNekoAdapter()）。
 * ============================================================================
 */
import { spawn as nodeSpawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

// ---------------------------------------------------------------------------
// 常量与类型
// ---------------------------------------------------------------------------

/** 适配器默认配置镜像（对齐 CXO-NekoAdapter/src/shared/config.ts DEFAULT_CONFIG），
 *  用于种子同步时判断 electron 存量值是否与适配器默认不同 */
export const ADAPTER_DEFAULTS = {
  python: 'python',
  sourceDir: 'C:\\N.E.K.O-main',
  port: 48916,
  autoStart: false,
} as const;

/** 适配器控制面默认端口（electron 配置键 neko.adapterControlPort 缺省值） */
export const DEFAULT_ADAPTER_CONTROL_PORT = 48920;

/** electron 侧 Neko 相关配置键（userData/config.json 字符串键值） */
export const NEKO_ELECTRON_KEYS = {
  python: 'neko.python',
  sourceDir: 'neko.sourceDir',
  port: 'neko.port',
  autoStart: 'neko.autoStart',
  /** 适配器项目目录；空串表示自动向上探测解析 */
  adapterDir: 'neko.adapterDir',
  /** 适配器控制面端口 */
  adapterControlPort: 'neko.adapterControlPort',
  /** 存量配置一次性种子同步完成标记 */
  seeded: 'neko.seeded',
} as const;

/** PUT /config 允许的补丁形状（与适配器 validateConfigPatch 的键/类型对齐） */
export interface AdapterConfigPatch {
  python?: string;
  sourceDir?: string;
  backendUrl?: string;
  port?: number;
  controlPort?: number;
  autoStart?: boolean;
}

/** 适配器全量配置（GET/PUT /config 响应） */
export type AdapterConfigFull = AdapterConfigPatch;

/** 适配器 /status 聚合快照（对齐 CXO-NekoAdapter control/server.ts ControlStatusSnapshot） */
export interface AdapterStatusSnapshot {
  running: boolean;
  /** running 时为插件服务器端口，未运行时为 null */
  port: number | null;
  config: AdapterConfigFull;
  bridge: {
    registrarRunning: boolean;
    bridgeRunning: boolean;
    bridgePort: number | null;
    tools: number;
    cxfcRegistered: boolean;
  };
}

/** start/restart 统一返回 */
export interface StartStopResult {
  ok: boolean;
  port?: number;
  error?: string;
}

/** 控制面请求统一返回（绝不抛出） */
type RequestResult = { ok: true; payload: Record<string, unknown> } | { ok: false; error: string };

export interface AdapterClientOptions {
  /** electron 键值配置读取（含默认值回落） */
  getConfig: (key: string) => string | null;
  /** electron 键值配置写入 */
  setConfig: (key: string, value: string) => void;
  /** 适配器项目目录解析；缺省从本模块位置向上逐级探测 CXO-NekoAdapter（最多 6 级） */
  resolveAdapterDir?: () => string;
  /** spawn 注入（测试用假子进程） */
  spawnImpl?: typeof nodeSpawn;
  /** fetch 注入（测试用路由 mock） */
  fetchImpl?: typeof fetch;
  /** 日志出口（ipc.ts 注入 BrowserWindow 广播链） */
  logSink?: ((line: string) => void) | null;
  /** /health 轮询间隔毫秒，默认 250 */
  pollIntervalMs?: number;
  /** /health 就绪总超时毫秒，默认 10000 */
  healthTimeoutMs?: number;
  /** 普通控制面请求超时毫秒，默认 15000 */
  requestTimeoutMs?: number;
  /** stop 各阶段超时毫秒（/stop 通知 + SIGTERM 宽限），默认 3000 */
  stopTimeoutMs?: number;
  /** SSE 重连退避基数毫秒，默认 1000 */
  reconnectBaseMs?: number;
  /** SSE 重连退避封顶毫秒，默认 8000 */
  reconnectMaxMs?: number;
  /** 重连补发 recent 行数，默认 200 */
  recentBackfillLimit?: number;
}

export interface AdapterClient {
  /** 确保适配器进程已拉起且控制面就绪（幂等，并发互斥共享同一 Promise） */
  ensureAdapter(): Promise<void>;
  /** 停止运行时（POST /stop，尽力 3s 超时）→ 杀适配器进程（SIGTERM→超时→SIGKILL） */
  stopAdapterProcess(): Promise<void>;
  /** 适配器进程是否存活 */
  isAdapterRunning(): boolean;
  /** 控制面基址 http://127.0.0.1:<port> */
  getControlBase(): string;
  /** GET /status（失败抛出，由调用方决定回落行为） */
  getStatus(): Promise<AdapterStatusSnapshot>;
  /** GET /config（失败抛出） */
  getAdapterConfig(): Promise<AdapterConfigFull>;
  /** PUT /config 部分更新（失败抛出） */
  putConfig(partial: AdapterConfigPatch): Promise<AdapterConfigFull>;
  /** POST /start（错误映射为 {ok:false,error}，不抛出） */
  start(): Promise<StartStopResult>;
  /** POST /stop（幂等；错误映射为 {ok:false,error}，不抛出） */
  stop(): Promise<{ ok: boolean; error?: string }>;
  /** POST /restart（完整运行时重建=修复语义；错误映射为 {ok:false,error}，不抛出） */
  restart(): Promise<StartStopResult>;
}

// ---------------------------------------------------------------------------
// 默认目录解析：从本模块位置向上最多 6 级探测 CXO-NekoAdapter
// ---------------------------------------------------------------------------

/** 开发态：electron/neko → APP-Frontend → CX-O（命中）；打包态：dist-electron → APP-Frontend → CX-O（命中） */
export function resolveAdapterDirDefault(): string {
  let dir = path.dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 6; i++) {
    const candidate = path.join(dir, 'CXO-NekoAdapter');
    if (existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) break; // 到达根目录
    dir = parent;
  }
  throw new Error('未能自动定位 CXO-NekoAdapter 目录，请在应用配置 neko.adapterDir 中手动指定');
}

// ---------------------------------------------------------------------------
// 客户端工厂
// ---------------------------------------------------------------------------

export function createAdapterClient(options: AdapterClientOptions): AdapterClient {
  const {
    getConfig,
    setConfig,
    spawnImpl = nodeSpawn,
    fetchImpl = globalThis.fetch.bind(globalThis),
    logSink = null,
    pollIntervalMs = 250,
    healthTimeoutMs = 10_000,
    requestTimeoutMs = 15_000,
    stopTimeoutMs = 3_000,
    reconnectBaseMs = 1_000,
    reconnectMaxMs = 8_000,
    recentBackfillLimit = 200,
  } = options;

  const emit = (line: string): void => {
    try {
      logSink?.(line);
    } catch {
      /* sink 异常不影响主流程 */
    }
  };
  const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
  /** 重连等待用 unref 定时器：不阻止应用进程退出 */
  const unrefSleep = (ms: number): Promise<void> =>
    new Promise((r) => {
      const t = setTimeout(r, ms);
      t.unref?.();
    });

  let child: ChildProcess | null = null;
  let ensurePromise: Promise<void> | null = null;
  /** stopAdapterProcess 置位；SSE 循环据此退出 */
  let stopped = false;
  /** SSE 循环是否已启动（防重复启动） */
  let sseStarted = false;
  let sseAbort: AbortController | null = null;

  // ---- 配置读取 ----

  const getControlPort = (): number => {
    const n = Number(getConfig(NEKO_ELECTRON_KEYS.adapterControlPort));
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : DEFAULT_ADAPTER_CONTROL_PORT;
  };

  const getControlBase = (): string => `http://127.0.0.1:${getControlPort()}`;

  const getAdapterDir = (): string => {
    const configured = getConfig(NEKO_ELECTRON_KEYS.adapterDir);
    if (configured && configured.trim()) return configured.trim();
    return (options.resolveAdapterDir ?? resolveAdapterDirDefault)();
  };

  // ---- 控制面请求 ----

  /** 原始请求：返回解析后的 JSON；网络/超时/非 2xx 抛出（非 2xx 优先取响应体 error 字段） */
  async function rawRequest(
    pathname: string,
    init?: { method?: string; body?: unknown; timeoutMs?: number },
  ): Promise<unknown> {
    const url = `${getControlBase()}${pathname}`;
    const method = init?.method ?? 'GET';
    const resp = await fetchImpl(url, {
      method,
      ...(init?.body !== undefined
        ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(init.body) }
        : {}),
      signal: AbortSignal.timeout(init?.timeoutMs ?? requestTimeoutMs),
    });
    const text = await resp.text();
    let payload: unknown = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = { ok: false, error: `非 JSON 响应 (HTTP ${resp.status})` };
    }
    if (!resp.ok) {
      const bodyError =
        payload !== null && typeof payload === 'object' && !Array.isArray(payload) && typeof (payload as { error?: unknown }).error === 'string'
          ? (payload as { error: string }).error
          : null;
      throw new Error(bodyError ?? `HTTP ${resp.status}`);
    }
    return payload;
  }

  /** 统一请求封装：任何错误映射为 {ok:false,error}，绝不抛出 */
  async function request(
    pathname: string,
    init?: { method?: string; body?: unknown; timeoutMs?: number },
  ): Promise<RequestResult> {
    try {
      const payload = await rawRequest(pathname, init);
      if (payload !== null && typeof payload === 'object' && !Array.isArray(payload)) {
        return { ok: true, payload: payload as Record<string, unknown> };
      }
      return { ok: false, error: '控制面响应不是 JSON 对象' };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
  }

  // ---- 进程管理 ----

  const isChildAlive = (): boolean => !!child && child.exitCode === null && !child.killed;

  function spawnChild(): void {
    const adapterDir = getAdapterDir();
    const entry = path.join(adapterDir, 'dist', 'index.js');
    if (!existsSync(entry)) {
      throw new Error(`适配器入口不存在：${entry}（请先在适配器目录执行 npm run build）`);
    }
    const controlPort = getControlPort();
    const proc = spawnImpl('node', ['dist/index.js', '--port', String(controlPort)], {
      cwd: adapterDir,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    child = proc;

    // stdout/stderr 行缓冲转发 logSink（含机器可读就绪行 [adapter] control listening ...）
    const forward = (chunk: Buffer | string): void => {
      for (const line of String(chunk).split('\n')) {
        const trimmed = line.replace(/\s+$/, '');
        if (trimmed) emit(trimmed);
      }
    };
    proc.stdout?.on('data', forward);
    proc.stderr?.on('data', forward);

    proc.on('exit', (code, signal) => {
      emit(`[neko] 适配器进程退出 code=${code} signal=${signal}`);
      // 代际防护：退出回调迟到期间若已 spawn 新实例，不得误清新 child
      if (child === proc) child = null;
    });
    proc.on('error', (err) => {
      emit(`[neko] 适配器进程启动失败: ${err.message}`);
      if (child === proc) child = null;
    });
  }

  /** /health 就绪等待：250ms 间隔轮询，10s 超时；进程中途死亡立即报错 */
  async function waitHealthReady(): Promise<void> {
    const deadline = Date.now() + healthTimeoutMs;
    let lastError = '';
    while (Date.now() < deadline) {
      if (!isChildAlive()) {
        throw new Error('适配器进程未存活（可能启动即退出），请检查适配器目录与 dist 产物');
      }
      const r = await request('/health', { timeoutMs: Math.max(pollIntervalMs * 4, 500) });
      if (r.ok) return;
      lastError = r.error;
      await sleep(pollIntervalMs);
    }
    throw new Error(
      `适配器控制面 ${Math.round(healthTimeoutMs / 1000)}s 内未就绪${lastError ? `（最后错误：${lastError}）` : ''}`,
    );
  }

  // ---- 存量配置一次性种子同步 ----

  /** 把 electron 侧存量四键（存在且与适配器默认不同）逐键 PUT 到适配器 /config */
  async function seedConfigIfNeeded(): Promise<void> {
    if (getConfig(NEKO_ELECTRON_KEYS.seeded) === 'true') return;

    const patches: Array<[string, AdapterConfigPatch]> = [];
    const python = getConfig(NEKO_ELECTRON_KEYS.python);
    if (python !== null && python !== ADAPTER_DEFAULTS.python) {
      patches.push(['python', { python }]);
    }
    const sourceDir = getConfig(NEKO_ELECTRON_KEYS.sourceDir);
    if (sourceDir !== null && sourceDir !== ADAPTER_DEFAULTS.sourceDir) {
      patches.push(['sourceDir', { sourceDir }]);
    }
    const portRaw = getConfig(NEKO_ELECTRON_KEYS.port);
    if (portRaw !== null) {
      const portNum = Number(portRaw);
      if (Number.isFinite(portNum) && portNum > 0 && Math.floor(portNum) !== ADAPTER_DEFAULTS.port) {
        patches.push(['port', { port: Math.floor(portNum) }]);
      }
    }
    const autoStartRaw = getConfig(NEKO_ELECTRON_KEYS.autoStart);
    if (autoStartRaw !== null) {
      const autoStart = autoStartRaw === 'true';
      if (autoStart !== ADAPTER_DEFAULTS.autoStart) {
        patches.push(['autoStart', { autoStart }]);
      }
    }

    if (patches.length === 0) {
      // 无差异需要同步：直接标记完成，避免每次启动重复判断
      setConfig(NEKO_ELECTRON_KEYS.seeded, 'true');
      return;
    }

    // 逐键 PUT，单键失败容忍（记录继续），全部成功才标记 seeded
    let allOk = true;
    for (const [name, patch] of patches) {
      try {
        await rawRequest('/config', { method: 'PUT', body: patch });
      } catch (err) {
        allOk = false;
        emit(`[neko] 种子同步配置 ${name} 失败: ${err instanceof Error ? err.message : String(err)}`);
      }
    }
    if (allOk) {
      setConfig(NEKO_ELECTRON_KEYS.seeded, 'true');
      emit(`[neko] 存量配置种子同步完成（${patches.length} 项）`);
    } else {
      emit('[neko] 种子同步存在失败项，未标记 seeded，下次启动将重试');
    }
  }

  // ---- SSE 日志流 ----

  /** 解析单行 SSE 帧：空行/注释帧（: heartbeat）忽略；data 帧 JSON 解码后广播 */
  function handleSseLine(rawLine: string): void {
    const line = rawLine.replace(/\r$/, '');
    if (!line || line.startsWith(':')) return;
    if (!line.startsWith('data:')) return;
    const payload = line.slice(5).replace(/^ /, '');
    let text: string;
    try {
      const parsed: unknown = JSON.parse(payload);
      text = typeof parsed === 'string' ? parsed : payload;
    } catch {
      text = payload;
    }
    emit(text);
  }

  /** 重连补发：GET /logs/recent?limit=200，失败容忍（续流为主） */
  async function backfillRecent(): Promise<void> {
    try {
      const payload = await rawRequest(`/logs/recent?limit=${recentBackfillLimit}`);
      const lines = (payload as { lines?: unknown } | null)?.lines;
      if (Array.isArray(lines)) {
        for (const l of lines) emit(typeof l === 'string' ? l : String(l));
      }
    } catch {
      /* 补发失败容忍 */
    }
  }

  /** SSE 订阅主循环：断线指数退避重连（1s→8s 封顶，无限重试，stopped 时退出） */
  async function runSseLoop(): Promise<void> {
    let attempt = 0;
    while (!stopped) {
      try {
        // 重连成功先补发 recent 再续流（首连由适配器 SSE 端点自行补发历史）
        if (attempt > 0) await backfillRecent();
        sseAbort = new AbortController();
        const resp = await fetchImpl(`${getControlBase()}/logs/stream`, { signal: sseAbort.signal });
        if (!resp.ok || !resp.body) throw new Error(`SSE 连接失败 (HTTP ${resp.status})`);
        attempt = 0; // 连接成功重置退避
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf('\n')) >= 0) {
            handleSseLine(buf.slice(0, idx));
            buf = buf.slice(idx + 1);
          }
        }
        throw new Error('SSE 连接被对端关闭');
      } catch (err) {
        sseAbort = null;
        if (stopped) return;
        const message = err instanceof Error ? err.message : String(err);
        if (!/abort/i.test(message)) {
          emit(`[neko] 日志流断开，将自动重连: ${message}`);
        }
        await unrefSleep(Math.min(reconnectBaseMs * 2 ** attempt, reconnectMaxMs));
        attempt++;
      }
    }
  }

  function startLogStream(): void {
    if (sseStarted) return;
    sseStarted = true;
    void runSseLoop().finally(() => {
      sseStarted = false;
    });
  }

  // ---- 生命周期 ----

  function ensureAdapter(): Promise<void> {
    if (ensurePromise) return ensurePromise;
    const attempt: Promise<void> = (async () => {
      stopped = false; // 上次 stop 后再次 ensure 允许 SSE 循环恢复
      if (!isChildAlive()) spawnChild();
      await waitHealthReady();
      await seedConfigIfNeeded();
      startLogStream();
    })();
    // 附着兜底消费，避免无外部 catch 时 unhandledRejection；真实错误仍由调用方拿到
    attempt.catch(() => undefined);
    const guarded = attempt.finally(() => {
      if (ensurePromise === guarded) ensurePromise = null;
    });
    ensurePromise = guarded;
    return guarded;
  }

  async function stopAdapterProcess(): Promise<void> {
    stopped = true;
    ensurePromise = null;
    // 1) 尽力通知适配器停运行时（含 python 子进程与桥），超时兜底
    await request('/stop', { method: 'POST', timeoutMs: stopTimeoutMs });
    // 2) 断开 SSE 连接（abort 触发读循环退出）
    try {
      sseAbort?.abort();
    } catch {
      /* ignore */
    }
    // 3) 杀适配器进程：SIGTERM → 超时 → SIGKILL
    const proc = child;
    if (!proc) return;
    const exited = new Promise<void>((resolve) => {
      proc.once('exit', () => resolve());
      proc.once('error', () => resolve());
    });
    try {
      proc.kill('SIGTERM');
    } catch {
      /* 已退出则忽略 */
    }
    await Promise.race([exited, sleep(stopTimeoutMs)]);
    if (proc.exitCode === null) {
      try {
        proc.kill('SIGKILL');
      } catch {
        /* ignore */
      }
      await Promise.race([exited, sleep(stopTimeoutMs)]);
    }
    if (child === proc) child = null;
  }

  // ---- 控制面 API 封装 ----

  async function getStatus(): Promise<AdapterStatusSnapshot> {
    return (await rawRequest('/status')) as AdapterStatusSnapshot;
  }

  async function getAdapterConfig(): Promise<AdapterConfigFull> {
    return (await rawRequest('/config')) as AdapterConfigFull;
  }

  async function putConfig(partial: AdapterConfigPatch): Promise<AdapterConfigFull> {
    return (await rawRequest('/config', { method: 'PUT', body: partial })) as AdapterConfigFull;
  }

  async function start(): Promise<StartStopResult> {
    const r = await request('/start', { method: 'POST' });
    if (!r.ok) return { ok: false, error: r.error };
    const port = r.payload.port;
    return { ok: true, port: typeof port === 'number' ? port : undefined };
  }

  async function stop(): Promise<{ ok: boolean; error?: string }> {
    const r = await request('/stop', { method: 'POST' });
    return r.ok ? { ok: true } : { ok: false, error: r.error };
  }

  async function restart(): Promise<StartStopResult> {
    const r = await request('/restart', { method: 'POST' });
    if (!r.ok) return { ok: false, error: r.error };
    const port = r.payload.port;
    return { ok: true, port: typeof port === 'number' ? port : undefined };
  }

  return {
    ensureAdapter,
    stopAdapterProcess,
    isAdapterRunning: isChildAlive,
    getControlBase,
    getStatus,
    getAdapterConfig,
    putConfig,
    start,
    stop,
    restart,
  };
}
