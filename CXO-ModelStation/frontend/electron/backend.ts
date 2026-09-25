/**
 * 后端生命周期与目录布局解析（Electron 主进程专用）。
 *
 * 设计约束：
 * - 本模块不 import 'electron'，可在纯 Node（vitest）环境下直接加载；
 *   `isPackaged` / `resourcesPath` 由主进程调用方显式注入。
 * - 所有判定与副作用均以参数注入（spawn / execFile / fetch / sleep），便于单测。
 *
 * 冻结契约（change-id: package-modelstation-desktop-installer）：
 *   <安装根>/CXO-ModelStation.exe
 *   <安装根>/resources/backend/            # 后端根（cwd 锚点，含 modelstation/ 包）
 *   <安装根>/resources/runtime/python/python.exe
 *   <安装根>/resources/engines/{so-vits-svc-4.1-Stable,VoxCPM-main,MeloTTS}
 *   <安装根>/resources/data/               # 包内 data 种子
 *   后端 base 默认 http://127.0.0.1:8300
 */
import { execFile as nodeExecFile, spawn as nodeSpawn } from "node:child_process";
import type { ChildProcess, SpawnOptions } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

/** 后端 /health 返回值中固定的服务标识 */
export const BACKEND_SERVICE_NAME = "CXO-ModelStation";
/** 后端 base（冻结契约默认值） */
export const DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8300";
/** 后端默认监听地址/端口（写入 CXO_MODELSTATION_CONFIG.server） */
export const DEFAULT_BACKEND_HOST = "127.0.0.1";
export const DEFAULT_BACKEND_PORT = 8300;
/** 端口顺延步长与候选数：8300 → 8310 → 8320 → 8330 → 8340 */
export const BACKEND_PORT_STEP = 10;
export const BACKEND_PORT_MAX_TRIES = 5;
/** 前端本地站点首选端口（冻结契约默认值） */
export const DEFAULT_FRONTEND_PORT = 3300;
/** 数据根目录名（%LOCALAPPDATA%\\CXO-ModelStation\\data） */
export const DATA_ROOT_DIR_NAME = "CXO-ModelStation";
/** 数据根种子幂等标记文件名与当前种子版本 */
export const DATA_SEED_MARKER_FILENAME = ".seed.json";
export const DATA_SEED_VERSION = 1;
/**
 * 数据根下必须存在的可写子目录（相对数据根）。
 * 与 buildBackendConfig 注入的可写目录一一对应：
 * training/sovits_svc、models/sovits_svc、audition、input、training/melotts、models/melotts。
 */
export const REQUIRED_DATA_SUBDIRS: readonly string[] = [
  "training/sovits_svc",
  "models/sovits_svc",
  "audition",
  "input",
  "training/melotts",
  "models/melotts",
];
/** 健康门默认上限与轮询间隔 */
export const DEFAULT_HEALTH_TIMEOUT_MS = 60_000;
export const DEFAULT_HEALTH_INTERVAL_MS = 400;

/** 解析后的目录布局（打包态 / 开发态） */
export interface AppLayout {
  mode: "packaged" | "dev";
  /** 打包态=resources 的父目录（安装根）；开发态=仓库根 CXO-ModelStation */
  installRoot: string;
  /** 打包态=process.resourcesPath；开发态=仓库根 */
  resourcesDir: string;
  /** 后端 cwd 锚点（含 modelstation/ 包） */
  backendRoot: string;
  /** 便携 Python 解释器绝对路径 */
  pythonExe: string;
  /** 引擎根（so-vits-svc-4.1-Stable / VoxCPM-main / MeloTTS） */
  enginesDir: string;
  /** 包内 data 种子目录 */
  dataSeedDir: string;
  soVitsSvcDir: string;
  voxcpmWorkingDir: string;
  /** PYTHONPATH 注入根：<engines>/VoxCPM-main/src */
  voxcpmSrcDir: string;
  melottsEngineDir: string;
  /** 前端构建产物目录（静态服务托管根） */
  frontendDistDir: string;
}

export interface LayoutOptions {
  isPackaged?: boolean;
  /** 打包态必填：主进程的 process.resourcesPath */
  resourcesPath?: string;
  /** 主进程 bundle 所在目录（默认由 import.meta.url 推导） */
  moduleDir?: string;
  pythonExe?: string;
  frontendDistDir?: string;
}

function moduleDirFromImportMeta(): string {
  try {
    return path.dirname(fileURLToPath(import.meta.url));
  } catch {
    return process.cwd();
  }
}

function trimTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

/**
 * 解析布局。
 *
 * 开发态仓库根推导：`<仓库根>/frontend/{electron|dist-electron}` 上溯两级 → `<仓库根>`。
 * 该推导对「vite-node 直接跑 TS 源码」与「vite-plugin-electron 产物 dist-electron」同时成立。
 */
export function resolveLayout(options: LayoutOptions = {}): AppLayout {
  const moduleDir = options.moduleDir ?? moduleDirFromImportMeta();

  if (options.isPackaged) {
    const resourcesDir = options.resourcesPath ?? path.resolve(moduleDir, "..");
    const enginesDir = path.join(resourcesDir, "engines");
    return {
      mode: "packaged",
      installRoot: path.dirname(resourcesDir),
      resourcesDir,
      backendRoot: path.join(resourcesDir, "backend"),
      pythonExe: options.pythonExe ?? path.join(resourcesDir, "runtime", "python", "python.exe"),
      enginesDir,
      dataSeedDir: path.join(resourcesDir, "data"),
      soVitsSvcDir: path.join(enginesDir, "so-vits-svc-4.1-Stable"),
      voxcpmWorkingDir: path.join(enginesDir, "VoxCPM-main"),
      voxcpmSrcDir: path.join(enginesDir, "VoxCPM-main", "src"),
      melottsEngineDir: path.join(enginesDir, "MeloTTS"),
      frontendDistDir: options.frontendDistDir ?? path.resolve(moduleDir, "..", "dist"),
    };
  }

  const repoRoot = path.resolve(moduleDir, "..", "..");
  const enginesDir = path.join(repoRoot, "engines");
  return {
    mode: "dev",
    installRoot: repoRoot,
    resourcesDir: repoRoot,
    backendRoot: repoRoot,
    // 项目先例：优先项目根 py311 虚拟环境，缺失时回退 PATH 上的 python
    pythonExe: options.pythonExe ?? path.resolve(repoRoot, "..", "py311", "Scripts", "python.exe"),
    enginesDir,
    dataSeedDir: path.join(repoRoot, "data"),
    soVitsSvcDir: path.join(enginesDir, "so-vits-svc-4.1-Stable"),
    voxcpmWorkingDir: path.join(enginesDir, "VoxCPM-main"),
    voxcpmSrcDir: path.join(enginesDir, "VoxCPM-main", "src"),
    melottsEngineDir: path.join(enginesDir, "MeloTTS"),
    frontendDistDir: options.frontendDistDir ?? path.join(repoRoot, "frontend", "dist"),
  };
}

/** 数据根：显式 env 覆盖 > %LOCALAPPDATA%\\CXO-ModelStation\\data > 兜底路径 */
export function resolveDataRoot(env: NodeJS.ProcessEnv = process.env): string {
  const explicit = (env.CXO_MODELSTATION_DATA_ROOT ?? "").trim();
  if (explicit) return path.resolve(explicit);
  if (env.LOCALAPPDATA) return path.join(env.LOCALAPPDATA, DATA_ROOT_DIR_NAME, "data");
  if (env.APPDATA) return path.join(env.APPDATA, DATA_ROOT_DIR_NAME, "data");
  return path.join(os.homedir(), ".cxo-modelstation", "data");
}

// ======================== 数据根落地与种子（4.3） ========================
/** 可注入的最小 fs 面（便于单测模拟只读/空目录等边界） */
export interface DataRootFsLike {
  existsSync(p: string): boolean;
  readdirSync(p: string): string[];
  mkdirSync(p: string, options: { recursive: boolean }): unknown;
  cpSync(src: string, dest: string, options: { recursive: boolean }): unknown;
  writeFileSync(p: string, data: string, encoding: BufferEncoding): unknown;
}

export interface DataRootPrepResult {
  ok: boolean;
  dataRoot: string;
  markerPath: string;
  /** 本次是否执行了包内种子拷贝 */
  seeded: boolean;
  /** 是否跳过了种子拷贝（命中幂等标记 / 数据根非空） */
  skippedSeed: boolean;
  reason: string;
  copiedFrom: string | null;
  /** 本次 ensure 出的可写子目录绝对路径 */
  createdDirs: string[];
  /** ok=false 时的可读错误（调用方只记录，不崩溃） */
  error?: string;
}

export interface PrepareDataRootOptions {
  dataRoot: string;
  /** 包内 data 种子目录（打包态 = <resources>/data） */
  seedDir: string;
  fsImpl?: DataRootFsLike;
  now?: () => Date;
}

/** 目录不存在或为空 → true（读取失败也按空处理，避免阻塞启动） */
export function isDirectoryEmptySync(dir: string, fsImpl: DataRootFsLike = fs): boolean {
  try {
    if (!fsImpl.existsSync(dir)) return true;
    return fsImpl.readdirSync(dir).length === 0;
  } catch {
    return true;
  }
}

function dataRootWritableError(dataRoot: string, error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error);
  return (
    `数据根不可写（${dataRoot}）：${detail}。请检查目录权限，` +
    `或用环境变量 CXO_MODELSTATION_DATA_ROOT 指向可写目录后重试。`
  );
}

/**
 * 数据根落地（首次启动拷贝包内种子，重复启动幂等跳过）。
 *
 * 顺序：
 *   1) mkdir dataRoot（不可写 → 返回可读 error，调用方继续启动不崩溃）；
 *   2) 命中 .seed.json 标记 → 跳过种子拷贝；数据根非空且无标记 → 尊重既有数据跳过；
 *   3) 否则（不存在或为空）从包内种子递归拷贝（含子目录结构）；
 *   4) 补齐注入给后端的 6 个可写子目录（幂等）；
 *   5) 幂等标记落盘（已存在则不覆盖）。
 */
export function prepareDataRoot(options: PrepareDataRootOptions): DataRootPrepResult {
  const dataRoot = path.resolve(options.dataRoot);
  const seedDir = path.resolve(options.seedDir);
  const fsImpl = options.fsImpl ?? fs;
  const markerPath = path.join(dataRoot, DATA_SEED_MARKER_FILENAME);
  const createdDirs: string[] = [];
  const base: DataRootPrepResult = {
    ok: true,
    dataRoot,
    markerPath,
    seeded: false,
    skippedSeed: false,
    reason: "",
    copiedFrom: null,
    createdDirs,
  };

  try {
    fsImpl.mkdirSync(dataRoot, { recursive: true });
  } catch (error) {
    return { ...base, ok: false, reason: "数据根创建失败", error: dataRootWritableError(dataRoot, error) };
  }

  const markerExists = fsImpl.existsSync(markerPath);
  const empty = isDirectoryEmptySync(dataRoot, fsImpl);
  let seeded = false;
  let skippedSeed = false;
  let reason: string;
  let copiedFrom: string | null = null;

  if (markerExists) {
    skippedSeed = true;
    reason = `命中种子标记（${DATA_SEED_MARKER_FILENAME}），跳过种子拷贝（幂等，不覆盖用户数据）`;
  } else if (!empty) {
    skippedSeed = true;
    reason = "数据根非空且无种子标记，尊重既有数据，跳过种子拷贝";
  } else if (fsImpl.existsSync(seedDir)) {
    try {
      fsImpl.cpSync(seedDir, dataRoot, { recursive: true });
      seeded = true;
      copiedFrom = seedDir;
      reason = `首次启动：已从包内种子拷贝（${seedDir}）`;
    } catch (error) {
      return {
        ...base,
        ok: false,
        reason: "种子拷贝失败",
        error: `数据根种子拷贝失败（${seedDir} → ${dataRoot}）：${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  } else {
    reason = `包内种子目录缺失（${seedDir}），仅初始化空数据根`;
  }

  try {
    for (const rel of REQUIRED_DATA_SUBDIRS) {
      const dir = path.join(dataRoot, rel);
      fsImpl.mkdirSync(dir, { recursive: true });
      createdDirs.push(dir);
    }
  } catch (error) {
    return { ...base, ok: false, seeded, skippedSeed, reason, error: dataRootWritableError(dataRoot, error) };
  }

  if (!markerExists) {
    const marker = {
      version: DATA_SEED_VERSION,
      seeded,
      seedDir,
      dataRoot,
      seededAt: (options.now ?? (() => new Date()))().toISOString(),
    };
    try {
      fsImpl.writeFileSync(markerPath, JSON.stringify(marker, null, 2), "utf8");
    } catch (error) {
      return {
        ...base,
        ok: false,
        seeded,
        skippedSeed,
        reason,
        error: `种子标记写入失败（${markerPath}）：${
          error instanceof Error ? error.message : String(error)
        }`,
      };
    }
  }

  return { ...base, seeded, skippedSeed, reason, copiedFrom };
}

// ======================== 后端端点解析与端口顺延（4.6） ========================

export interface BackendServerConfig {
  host: string;
  port: number;
}

export function defaultBackendServer(): BackendServerConfig {
  return { host: DEFAULT_BACKEND_HOST, port: DEFAULT_BACKEND_PORT };
}

/** 从后端 base 解析 host/port（非法/缺省回退默认值） */
export function parseBackendBaseUrl(baseUrl: string): BackendServerConfig {
  try {
    const url = new URL(baseUrl);
    const port = url.port ? Number(url.port) : url.protocol === "https:" ? 443 : 80;
    if (!Number.isInteger(port) || port <= 0 || port > 65535) return defaultBackendServer();
    return { host: url.hostname || DEFAULT_BACKEND_HOST, port };
  } catch {
    return defaultBackendServer();
  }
}

export function buildBackendBaseUrl(host: string, port: number): string {
  return `http://${host}:${port}`;
}

/** 端口顺延候选序列（含首选，步长 10） */
export function backendCandidatePorts(
  preferred: number,
  maxTries: number = BACKEND_PORT_MAX_TRIES,
): number[] {
  const total = Math.max(1, maxTries);
  return Array.from({ length: total }, (_, index) => preferred + index * BACKEND_PORT_STEP);
}

export interface ResolveBackendEndpointOptions {
  /** 配置里的后端 base（默认 http://127.0.0.1:8300） */
  baseUrl: string;
  /** 判定该 base 是否为健康的 ModelStation（复用） */
  isHealthy: (baseUrl: string) => Promise<boolean>;
  /** 判定端口是否空闲（可绑定） */
  isPortFree: (port: number) => Promise<boolean>;
  maxTries?: number;
}

export interface ResolvedBackendEndpoint {
  baseUrl: string;
  host: string;
  port: number;
  /** 复用既有健康实例（未拉起新进程） */
  reused: boolean;
  /** 实际端口与配置端口不同（发生了顺延/换端口） */
  changed: boolean;
  reason: string;
}

/**
 * 选定后端端点：
 *   1) 配置 base 已是健康 ModelStation → 原样复用；
 *   2) 否则按顺延序列（preferred, +10, +20 …）逐个判定：已是健康 ModelStation → 复用；
 *      端口空闲 → 作为实际端点返回；
 *   3) 全部不可用 → 抛出可读错误（调用方不得空转等待健康门）。
 */
export async function resolveBackendEndpoint(
  options: ResolveBackendEndpointOptions,
): Promise<ResolvedBackendEndpoint> {
  const configured = parseBackendBaseUrl(options.baseUrl);
  if (await options.isHealthy(options.baseUrl)) {
    return {
      baseUrl: options.baseUrl,
      host: configured.host,
      port: configured.port,
      reused: true,
      changed: false,
      reason: `目标端口 ${configured.port} 已是健康的 ModelStation，复用既有实例`,
    };
  }

  const candidates = backendCandidatePorts(configured.port, options.maxTries);
  for (const port of candidates) {
    const candidateBase = buildBackendBaseUrl(configured.host, port);
    if (port !== configured.port && (await options.isHealthy(candidateBase))) {
      return {
        baseUrl: candidateBase,
        host: configured.host,
        port,
        reused: true,
        changed: true,
        reason: `端口 ${configured.port} 非 ModelStation，顺延发现端口 ${port} 已有健康 ModelStation，复用`,
      };
    }
    if (await options.isPortFree(port)) {
      return {
        baseUrl: candidateBase,
        host: configured.host,
        port,
        reused: false,
        changed: port !== configured.port,
        reason:
          port === configured.port
            ? `目标端口 ${port} 空闲，使用默认端口`
            : `目标端口 ${configured.port} 不可用（被占用或非 ModelStation），顺延到空闲端口 ${port}`,
      };
    }
  }

  throw new Error(
    `后端端口 ${candidates[0]}-${candidates[candidates.length - 1]} 均不可用（被占用或无法绑定）。` +
      `请释放端口或修改连接地址后重试；不会在无可用端口时空转等待。`,
  );
}

/** CXO_MODELSTATION_CONFIG 的 JSON 结构（字段名与 modelstation/config.py 对齐） */
export interface BackendConfigPayload {
  server: {
    host: string;
    port: number;
  };
  sovits_svc: {
    python_path: string;
    so_vits_svc_dir: string;
    training_data_dir: string;
    models_dir: string;
    audition_dir: string;
    input_dir: string;
  };
  voxcpm: {
    working_dir: string;
  };
  melotts: {
    python_path: string;
    engine_dir: string;
    training_data_dir: string;
    models_dir: string;
  };
}

/** 组装 CXO_MODELSTATION_CONFIG 载荷（包内引擎/解释器 + 数据根下的可写子目录 + 实际监听端点） */
export function buildBackendConfig(
  layout: AppLayout,
  dataRoot: string,
  server: BackendServerConfig = defaultBackendServer(),
): BackendConfigPayload {
  const data = path.resolve(dataRoot);
  return {
    server: { host: server.host, port: server.port },
    sovits_svc: {
      python_path: layout.pythonExe,
      so_vits_svc_dir: layout.soVitsSvcDir,
      training_data_dir: path.join(data, "training", "sovits_svc"),
      models_dir: path.join(data, "models", "sovits_svc"),
      audition_dir: path.join(data, "audition"),
      input_dir: path.join(data, "input"),
    },
    voxcpm: {
      working_dir: layout.voxcpmWorkingDir,
    },
    melotts: {
      python_path: layout.pythonExe,
      engine_dir: layout.melottsEngineDir,
      training_data_dir: path.join(data, "training", "melotts"),
      models_dir: path.join(data, "models", "melotts"),
    },
  };
}

export function serializeBackendConfig(
  layout: AppLayout,
  dataRoot: string,
  server: BackendServerConfig = defaultBackendServer(),
): string {
  return JSON.stringify(buildBackendConfig(layout, dataRoot, server));
}

/** PYTHONPATH 追加（保留既有值，置于其后） */
export function mergePythonPath(voxcpmSrcDir: string, existing?: string): string {
  const prev = (existing ?? "").trim();
  return prev ? `${voxcpmSrcDir}${path.delimiter}${prev}` : voxcpmSrcDir;
}

/** 构建后端进程环境变量（CXO_MODELSTATION_CONFIG + PYTHONPATH + 缓冲关闭） */
export function buildBackendEnv(
  layout: AppLayout,
  dataRoot: string,
  baseEnv: NodeJS.ProcessEnv = process.env,
  server: BackendServerConfig = defaultBackendServer(),
): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(baseEnv)) {
    if (typeof value === "string") env[key] = value;
  }
  env.CXO_MODELSTATION_CONFIG = serializeBackendConfig(layout, dataRoot, server);
  env.PYTHONPATH = mergePythonPath(layout.voxcpmSrcDir, env.PYTHONPATH);
  env.PYTHONUNBUFFERED = "1";
  return env;
}

export type FetchLike = (input: string, init?: { signal?: AbortSignal; headers?: Record<string, string> }) => Promise<{
  ok: boolean;
  json: () => Promise<unknown>;
}>;

export interface HealthCheckOptions {
  baseUrl: string;
  fetchImpl?: FetchLike;
  /** 短超时（默认 1.5s），避免界面被不可达后端拖死 */
  timeoutMs?: number;
}

/** GET /health：判定 status==='healthy' && service==='CXO-ModelStation'，任何异常一律 false */
export async function isBackendHealthy(options: HealthCheckOptions): Promise<boolean> {
  const fetchImpl = options.fetchImpl ?? (globalThis.fetch as unknown as FetchLike | undefined);
  if (typeof fetchImpl !== "function") return false;
  const timeoutMs = options.timeoutMs ?? 1500;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetchImpl(`${trimTrailingSlash(options.baseUrl)}/health`, {
      signal: controller.signal,
      headers: { accept: "application/json" },
    });
    if (!res.ok) return false;
    const body = (await res.json()) as { status?: unknown; service?: unknown } | null;
    return body?.status === "healthy" && body?.service === BACKEND_SERVICE_NAME;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export interface WaitHealthyOptions {
  baseUrl: string;
  timeoutMs?: number;
  intervalMs?: number;
  isHealthy?: (baseUrl: string) => Promise<boolean>;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
}

export interface WaitHealthyResult {
  healthy: boolean;
  attempts: number;
  elapsedMs: number;
  reason?: string;
}

/** 健康门：轮询至上限，超时返回明确失败原因（不抛异常） */
export async function waitHealthy(options: WaitHealthyOptions): Promise<WaitHealthyResult> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
  const intervalMs = options.intervalMs ?? DEFAULT_HEALTH_INTERVAL_MS;
  const now = options.now ?? Date.now;
  const sleep =
    options.sleep ?? ((ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms)));
  const check =
    options.isHealthy ??
    ((baseUrl: string) =>
      isBackendHealthy({ baseUrl, timeoutMs: Math.min(Math.max(intervalMs * 2, 500), 2000) }));

  const started = now();
  let attempts = 0;
  for (;;) {
    attempts += 1;
    if (await check(options.baseUrl)) {
      return { healthy: true, attempts, elapsedMs: now() - started };
    }
    const elapsed = now() - started;
    if (elapsed + intervalMs >= timeoutMs) {
      return {
        healthy: false,
        attempts,
        elapsedMs: now() - started,
        reason:
          `后端在 ${timeoutMs}ms 内未通过健康检查（GET ${trimTrailingSlash(options.baseUrl)}/health），` +
          `共尝试 ${attempts} 次。请确认后端已启动（可在安装目录运行 start.bat）或连接地址正确。`,
      };
    }
    await sleep(intervalMs);
  }
}

export type SpawnLike = (command: string, args: string[], options: SpawnOptions) => ChildProcess;

export interface SpawnBackendOptions {
  layout: AppLayout;
  dataRoot: string;
  env?: NodeJS.ProcessEnv;
  spawnImpl?: SpawnLike;
  /** 实际监听端点（默认 127.0.0.1:8300；顺延后由调用方注入） */
  server?: BackendServerConfig;
}

/** 拉起后端：cwd=包内 backend 根，注入 env（含 CXO_MODELSTATION_CONFIG / PYTHONPATH） */
export function spawnBackend(options: SpawnBackendOptions): ChildProcess {
  const spawnImpl = options.spawnImpl ?? (nodeSpawn as unknown as SpawnLike);
  const env = buildBackendEnv(
    options.layout,
    options.dataRoot,
    options.env ?? process.env,
    options.server ?? defaultBackendServer(),
  );
  return spawnImpl(options.layout.pythonExe, ["-m", "modelstation.main"], {
    cwd: options.layout.backendRoot,
    env,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

export type ExecFileLike = (
  file: string,
  args: string[],
  options: { windowsHide?: boolean },
  callback: (error: Error | null) => void,
) => unknown;

export interface StopBackendOptions {
  platform?: NodeJS.Platform;
  execImpl?: ExecFileLike;
  killImpl?: (pid: number, signal?: NodeJS.Signals) => void;
}

/**
 * 停止后端进程树。
 * Windows 用 `taskkill /PID <pid> /T /F` 连带训练子进程；其他平台先 SIGTERM 再 SIGKILL。
 */
export async function stopBackendProcessTree(
  pid: number,
  options: StopBackendOptions = {},
): Promise<boolean> {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  const platform = options.platform ?? process.platform;
  const killImpl = options.killImpl ?? ((p: number, s?: NodeJS.Signals) => process.kill(p, s));

  if (platform === "win32") {
    const execImpl = options.execImpl ?? (nodeExecFile as unknown as ExecFileLike);
    return new Promise<boolean>((resolve) => {
      try {
        execImpl("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true }, (error) =>
          resolve(!error),
        );
      } catch {
        resolve(false);
      }
    });
  }

  try {
    killImpl(pid, "SIGTERM");
    return true;
  } catch {
    try {
      killImpl(pid, "SIGKILL");
      return true;
    } catch {
      return false;
    }
  }
}