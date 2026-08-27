/**
 * Neko 插件运行时 sidecar 启动器（Electron 主进程）
 * ============================================================================
 * 职责：把 neko 的插件服务器（python -m plugin.user_plugin_server）作为本机
 * 子进程拉起/停止，并复用它监听 127.0.0.1 的端口。由于前端与后端可能不在同一
 * 台机器，neko 相关一切（进程、插件、商店）都运行在本机前端这一侧。
 *
 * 依赖：本机已安装 Python 且能导入 neko 源码根目录下的 config/plugin/utils 包。
 * 不修改 neko 源码（C:\N.E.K.O-main 只读）。
 * ============================================================================
 */
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync } from 'node:fs';
import * as net from 'node:net';
import { getConfig, setConfig } from '../config';
import { startNekoToolRegistrar, startNekoToolBridge, stopNekoToolBridge } from './toolBridge';

/** 运行时配置（持久化于 userData/config.json，均为字符串键值） */
export interface NekoRuntimeConfig {
  /** Python 可执行路径；空则用 PATH 中的 python */
  python: string;
  /** neko 源码目录（含 config/plugin/utils 包） */
  sourceDir: string;
  /** 插件服务器端口；0 表示自动分配 */
  port: number;
  /** 是否随 CX-O 应用启动自动拉起 */
  autoStart: boolean;
}

export const NEKO_CONFIG_KEYS = {
  python: 'neko.python',
  sourceDir: 'neko.sourceDir',
  port: 'neko.port',
  autoStart: 'neko.autoStart',
} as const;

export const DEFAULT_NEKO_CONFIG: NekoRuntimeConfig = {
  python: 'python',
  sourceDir: 'C:\\N.E.K.O-main',
  port: 48916,
  autoStart: false,
};

export function getNekoConfig(): NekoRuntimeConfig {
  return {
    python: getConfig(NEKO_CONFIG_KEYS.python) || DEFAULT_NEKO_CONFIG.python,
    sourceDir: getConfig(NEKO_CONFIG_KEYS.sourceDir) || DEFAULT_NEKO_CONFIG.sourceDir,
    port: Number(getConfig(NEKO_CONFIG_KEYS.port)) || DEFAULT_NEKO_CONFIG.port,
    autoStart: getConfig(NEKO_CONFIG_KEYS.autoStart) === 'true',
  };
}

export function setNekoConfig(partial: Partial<NekoRuntimeConfig>): NekoRuntimeConfig {
  if (partial.python !== undefined) setConfig(NEKO_CONFIG_KEYS.python, partial.python.trim());
  if (partial.sourceDir !== undefined) setConfig(NEKO_CONFIG_KEYS.sourceDir, partial.sourceDir.trim());
  if (partial.port !== undefined) setConfig(NEKO_CONFIG_KEYS.port, String(Math.max(0, Math.floor(partial.port))));
  if (partial.autoStart !== undefined) setConfig(NEKO_CONFIG_KEYS.autoStart, String(!!partial.autoStart));
  return getNekoConfig();
}

// ---------------------------------------------------------------------------
// 子进程状态
// ---------------------------------------------------------------------------
let child: ChildProcess | null = null;
/** 当前实际端口（跨 reload 保持） */
let activePort: number | null = null;
/** M-G 修复：startNeko 进行中的互斥句柄——并发重入共享同一 Promise，杜绝双 python 孤儿进程 */
let nekoStarting: Promise<{ port: number }> | null = null;
let logSink: ((line: string) => void) | null = null;

export function setNekoLogSink(sink: ((line: string) => void) | null): void {
  logSink = sink;
}

export function isNekoRunning(): boolean {
  return !!child && child.exitCode === null && !child.killed;
}

/** 返回当前状态：running / 端口 / 配置 */
export function getNekoStatus(): { running: boolean; port: number | null; config: NekoRuntimeConfig } {
  const running = isNekoRunning();
  return { running, port: running ? activePort : null, config: getNekoConfig() };
}

function emit(chunk: Buffer | string): void {
  if (logSink) logSink(String(chunk).replace(/\s+$/, ''));
}

// 在 host 上找空闲端口（与 neko 自身策略一致：base 起向后探测）
async function pickAvailablePort(host: string, basePort: number): Promise<number> {
  if (basePort > 0) {
    // 直接探测目标端口是否可用
    if (await isPortAvailable(host, basePort)) return basePort;
  }
  for (let port = Math.max(1, basePort); port < basePort + 200; port++) {
    if (await isPortAvailable(host, port)) return port;
  }
  throw new Error(`在 ${host}:${basePort} 起找不到可用端口`);
}

function isPortAvailable(host: string, port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const probe = net.createConnection({ host, port });
    probe.once('connect', () => {
      probe.destroy();
      resolve(false);
    });
    probe.once('error', () => resolve(true));
  });
}

/**
 * 启动插件服务器。返回起跑时确定的端口。
 * 若已在运行，直接返回当前端口（幂等）。
 * 并发重入经模块级 starting Promise 互斥：首个调用创建 Promise 持有全流程
 * （源码目录校验 → 选端口 → spawn → 等就绪），后续调用 await 同一 Promise，
 * 不再各自 spawn 出双 python 孤儿进程。
 */
export async function startNeko(): Promise<{ port: number }> {
  if (isNekoRunning() && activePort) {
    return { port: activePort };
  }
  if (nekoStarting) {
    return nekoStarting;
  }
  const attempt = doStartNeko().finally(() => {
    // 仅当互斥句柄仍指向本轮 attempt 时清空（异步回调时刻常量已完成初始化），
    // 防止极端时序下误清新一轮 attempt
    if (nekoStarting === attempt) nekoStarting = null;
  });
  nekoStarting = attempt;
  // 附着兜底消费，避免无外部 catch 时 unhandledRejection；真实错误仍由调用方拿到
  attempt.catch(() => undefined);
  return attempt;
}

async function doStartNeko(): Promise<{ port: number }> {
  const cfg = getNekoConfig();
  if (!existsSync(cfg.sourceDir)) {
    throw new Error(`neko 源码目录不存在：${cfg.sourceDir}`);
  }

  const host = '127.0.0.1';
  const port = await pickAvailablePort(host, cfg.port);
  activePort = port;

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    PYTHONPATH: cfg.sourceDir,
    // 绑定源码根目录，确保 import config/plugin/utils 走我们的目录
    NEKO_USER_PLUGIN_SERVER_PORT: String(port),
    // 市场桥配置（保持可选；不设则 neko 走内置默认）
    ...(process.env.MARKET_API_URL ? { MARKET_API_URL: process.env.MARKET_API_URL } : {}),
    ...(process.env.MARKET_WEB_URL ? { MARKET_WEB_URL: process.env.MARKET_WEB_URL } : {}),
  };

  const pythonExe = cfg.python.trim() || 'python';
  const proc = spawn(pythonExe, ['-m', 'plugin.user_plugin_server'], {
    cwd: cfg.sourceDir,
    env,
    windowsHide: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child = proc;

  proc.stdout?.on('data', emit);
  proc.stderr?.on('data', emit);

  proc.on('exit', (code, signal) => {
    emit(`[neko] 插件服务器退出 code=${code} signal=${signal}`);
    // M-G 修复（代际防护）：仅当仍是当前代际时才清状态——退出回调迟到期间若已
    // startNeko 新一代子进程，不得误置新实例的 child/activePort。
    if (child === proc) child = null;
    if (activePort === port) activePort = null;
  });
  proc.on('error', (err) => {
    emit(`[neko] 插件服务器启动失败: ${err.message}`);
    // H10: spawn 失败（如 python 不存在 ENOENT）不会触发 exit 事件，
    // 默认残留 child/activePort 会让后续 startNeko 误判"正在运行"、
    // stopNeko 误走 SIGKILL。此处必须手动清理状态（同样带代际比对）。
    if (child === proc) child = null;
    if (activePort === port) activePort = null;
  });

  // 请求超时：等待端口真正可连
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 250));
    if (!isNekoRunning()) {
      throw new Error('插件服务器进程未存活，请检查 python 路径与源码目录后重试');
    }
    if (await isPortAvailable(host, port) === false) {
      return { port };
    }
  }
  throw new Error(`插件服务器端口 ${port} 30s 内未就绪`);
}

/** 停止插件服务器：先 SIGTERM 优雅关闭，超时后强杀 */
export async function stopNeko(): Promise<void> {
  if (!child) {
    activePort = null;
    return;
  }
  const proc = child;
  const exited = new Promise<void>((resolve) => {
    proc.once('exit', () => resolve());
    proc.once('error', () => resolve());
  });
  try {
    proc.kill('SIGTERM');
  } catch {
    /* 已退出则忽略 */
  }
  await Promise.race([exited, new Promise((r) => setTimeout(r, 3000))]);
  if (proc.exitCode === null) {
    try {
      proc.kill('SIGKILL');
    } catch {
      /* ignore */
    }
    await exited;
  }
  child = null;
  activePort = null;
}

/** 重启：停止后再次启动 */
export async function restartNeko(): Promise<{ port: number }> {
  await stopNeko();
  return startNeko();
}

// ---------------------------------------------------------------------------
// 组合编排：插件服务器 + 工具→CXFC 桥
// ---------------------------------------------------------------------------

/**
 * 完整启动 neko 运行时：先起工具注册接收器 → 起插件服务器 → 起 CXFC 工具桥并
 * 注册到 CX-O 后端。接收器必须在插件服务器之前就绪，否则插件启动期上报的工具
 * 定义会被丢弃。桥/注册为尽力而为，失败不阻断插件服务器。
 */
export async function startNekoRuntime(): Promise<{ port: number; bridge: boolean }> {
  // 1) 工具定义捕获（注册接收器，loopback 主服务器端口）
  const registrarOk = await startNekoToolRegistrar();
  if (registrarOk) emit('[neko] 工具注册接收器已就绪');

  // 2) 插件服务器
  const { port } = await startNeko();

  // 3) CXFC 工具桥 + 向后端注册（尽力而为）
  let bridge = false;
  try {
    await startNekoToolBridge(port);
    bridge = true;
    emit(`[neko] CXFC 工具桥已启动并注册（插件端口 ${port}）`);
  } catch (err) {
    emit(`[neko] CXFC 工具桥启动失败（忽略）: ${err instanceof Error ? err.message : String(err)}`);
  }
  return { port, bridge };
}

/** 完整停止 neko 运行时：停 CXFC 桥 → 停插件服务器 */
export async function stopNekoRuntime(): Promise<void> {
  await stopNekoToolBridge();
  await stopNeko();
}
