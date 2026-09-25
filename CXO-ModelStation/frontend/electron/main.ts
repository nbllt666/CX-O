/**
 * Electron 主进程入口（change-id: package-modelstation-desktop-installer）。
 *
 * 职责：
 * 1) 单实例锁 + second-instance 聚焦；
 * 2) 数据根落地（首次启动从包内 <resources>/data 拷贝种子并打幂等标记，不覆盖用户数据）；
 * 3) 以包内便携 Python 拉起后端（cwd=包内 backend 根，注入 CXO_MODELSTATION_CONFIG/PYTHONPATH），
 *    并先选定实际端点（默认端口非健康 ModelStation 时按 8300→8310→… 顺延）再等健康门；
 * 4) 生产态启动本地静态服务（默认 127.0.0.1:3300，占用则顺延）托管前端产物，
 *    并把 /api、/health 反代到实际后端 base；开发态（vite dev）不启该服务；
 * 5) 窗口加载本地站点；退出时清理后端进程树与静态服务。
 */
import { app, BrowserWindow, ipcMain, shell } from "electron";
import type { ChildProcess } from "node:child_process";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_FRONTEND_PORT,
  isBackendHealthy,
  prepareDataRoot,
  resolveBackendEndpoint,
  resolveDataRoot,
  resolveLayout,
  spawnBackend,
  stopBackendProcessTree,
  waitHealthy,
  type AppLayout,
  type ResolvedBackendEndpoint,
} from "./backend";
import { IPC, type BackendActionResult, type BackendStatus, type DesktopInfo } from "./ipc";
import { createPortProbe } from "./ports";
import {
  configFilePath,
  defaultAppConfig,
  patchAppConfig,
  readAppConfig,
  type AppConfig,
} from "./settings";
import { startStaticServer, type RunningStaticServer } from "./staticServer";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));

const layout: AppLayout = resolveLayout({
  isPackaged: app.isPackaged,
  resourcesPath: process.resourcesPath,
  moduleDir,
});

let mainWindow: BrowserWindow | null = null;
let staticServerHandle: RunningStaticServer | null = null;
let backendProcess: ChildProcess | null = null;
let appConfig: AppConfig = defaultAppConfig(resolveDataRoot(), DEFAULT_FRONTEND_PORT);
/**
 * 实际后端 base（可能与配置值不同）：
 * 默认端口被非 ModelStation 占用时按 8300→8310→… 顺延，此处记录真实监听端点，
 * 供静态服务反代与渲染层连接面板使用（不在界面显示死值 8300）。
 */
let backendBaseUrl = appConfig.backendBaseUrl;
let configPath = "";
let frontendUrl = "";
let frontendPort = 0;
let shuttingDown = false;

function log(message: string): void {
  process.stdout.write(`[CXO-ModelStation] ${message}\n`);
}

/** 是否为由本进程管理的本机后端（远程地址不得被本地拉起逻辑覆盖） */
export function isLocalBackendBaseUrl(baseUrl: string): boolean {
  try {
    const hostname = new URL(baseUrl).hostname;
    return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "::1";
  } catch {
    return false;
  }
}

async function checkBackend(baseUrl: string, timeoutMs = 1500): Promise<BackendStatus> {
  const healthy = await isBackendHealthy({ baseUrl, timeoutMs });
  return {
    healthy,
    baseUrl,
    checkedAt: Date.now(),
    detail: healthy
      ? undefined
      : `GET ${baseUrl.replace(/\/+$/, "")}/health 未返回 healthy（service=CXO-ModelStation）。` +
        `可在安装目录运行 start.bat 启动后端，或在连接设置中修改地址。`,
  };
}

/**
 * 拉起本机后端（已有健康实例则复用；默认端口不可用时按 8300→8310→… 顺延）。
 *
 * 修复「目标端口被无关服务占用 → 健康门空转 60s」：
 * 先判定目标 base 是否已是健康 ModelStation（是 → 复用，不拉起）；
 * 否则在顺延序列中挑出可用端口并把实际 server 端点注入 CXO_MODELSTATION_CONFIG 后再拉起。
 */
async function ensureBackend(): Promise<void> {
  const configuredBaseUrl = appConfig.backendBaseUrl;
  if (!isLocalBackendBaseUrl(configuredBaseUrl)) {
    log(`后端地址为外部服务（${configuredBaseUrl}），跳过本地后端拉起`);
    backendBaseUrl = configuredBaseUrl;
    return;
  }

  let resolved: ResolvedBackendEndpoint;
  try {
    resolved = await resolveBackendEndpoint({
      baseUrl: configuredBaseUrl,
      isHealthy: (baseUrl: string) => isBackendHealthy({ baseUrl, timeoutMs: 1200 }),
      isPortFree: createPortProbe("127.0.0.1"),
    });
  } catch (error) {
    // 无可用端口：明确失败而不是空转等待健康门
    backendBaseUrl = configuredBaseUrl;
    log(`后端端点选定时失败：${error instanceof Error ? error.message : String(error)}`);
    return;
  }

  backendBaseUrl = resolved.baseUrl;
  log(`后端端点：${resolved.reason}`);

  if (resolved.reused) {
    log(`检测到后端已就绪（${resolved.baseUrl}），复用既有实例`);
    return;
  }

  const server = { host: resolved.host, port: resolved.port };
  log(
    `拉起后端：${layout.pythonExe} -m modelstation.main（cwd=${layout.backendRoot}，` +
      `server=${server.host}:${server.port}${resolved.changed ? `，默认 ${parsePort(configuredBaseUrl)} 已顺延` : ""}）`,
  );
  backendProcess = spawnBackend({ layout, dataRoot: appConfig.dataRoot, server });
  backendProcess.stdout?.on("data", (chunk: Buffer) => process.stdout.write(`[backend] ${chunk}`));
  backendProcess.stderr?.on("data", (chunk: Buffer) => process.stderr.write(`[backend] ${chunk}`));
  backendProcess.on("exit", (code, signal) => {
    log(`后端进程退出：code=${code ?? "null"} signal=${signal ?? "null"}`);
    backendProcess = null;
  });

  const result = await waitHealthy({ baseUrl: resolved.baseUrl });
  if (result.healthy) {
    log(`后端健康门通过（${resolved.baseUrl}，尝试 ${result.attempts} 次 / ${result.elapsedMs}ms）`);
  } else {
    log(`后端健康门失败：${result.reason ?? "未知原因"}`);
  }
}

function parsePort(baseUrl: string): string {
  try {
    return new URL(baseUrl).port || "80";
  } catch {
    return "?";
  }
}

async function stopBackend(): Promise<BackendActionResult> {
  const child = backendProcess;
  if (!child || child.pid === undefined) {
    return { ok: true, message: "后端非主进程拉起（或已停止），无需清理" };
  }
  const pid = child.pid;
  backendProcess = null;
  const ok = await stopBackendProcessTree(pid);
  return {
    ok,
    message: ok ? `已停止后端进程树（pid=${pid}）` : `停止后端进程树失败（pid=${pid}）`,
  };
}

async function closeStaticServer(): Promise<void> {
  const handle = staticServerHandle;
  staticServerHandle = null;
  if (!handle) return;
  await new Promise<void>((resolve) => handle.server.close(() => resolve()));
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: "模型工作站 · CXO-ModelStation",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(moduleDir, "preload.mjs"),
      contextIsolation: true,
      nodeIntegration: false,
      // ESM 预加载脚本（.mjs）要求 sandbox=false；渲染层仍无 Node 能力
      sandbox: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  log(`窗口加载：${frontendUrl}`);
  void mainWindow.loadURL(frontendUrl);
}

function registerIpc(): void {
  ipcMain.handle(IPC.getInfo, (): DesktopInfo => ({
    isDesktop: true,
    // 上报实际后端 base（可能因端口顺延与配置值不同），连接面板据此显示真实地址
    backendBaseUrl,
    frontendUrl,
    frontendPort,
    dataRoot: appConfig.dataRoot,
    layoutMode: layout.mode,
    configFilePath: configPath,
  }));

  ipcMain.handle(IPC.getConfig, () => appConfig);

  ipcMain.handle(IPC.setConfig, (_event, patch: unknown) => {
    const defaults = defaultAppConfig(resolveDataRoot(), DEFAULT_FRONTEND_PORT);
    appConfig = patchAppConfig(configPath, defaults, patch);
    log(`配置已更新：backendBaseUrl=${appConfig.backendBaseUrl} dataRoot=${appConfig.dataRoot}`);
    return appConfig;
  });

  ipcMain.handle(IPC.checkBackend, (_event, baseUrl?: string) =>
    checkBackend(baseUrl?.trim() || backendBaseUrl, 2500),
  );

  ipcMain.handle(IPC.restartBackend, async (): Promise<BackendActionResult> => {
    await stopBackend();
    await ensureBackend();
    const status = await checkBackend(backendBaseUrl, 2500);
    return {
      ok: status.healthy,
      message: status.healthy ? "后端已重启并健康" : status.detail ?? "后端重启后仍不可达",
      status,
    };
  });

  ipcMain.handle(IPC.stopBackend, () => stopBackend());
}

async function bootstrap(): Promise<void> {
  configPath = configFilePath(app.getPath("userData"));
  const defaults = defaultAppConfig(resolveDataRoot(), DEFAULT_FRONTEND_PORT);
  appConfig = readAppConfig(configPath, defaults);
  backendBaseUrl = appConfig.backendBaseUrl;
  log(`配置：${configPath}（backendBaseUrl=${appConfig.backendBaseUrl} dataRoot=${appConfig.dataRoot}）`);

  // 数据根落地：首次启动从包内 <resources>/data 拷贝种子并打幂等标记；不可写时只记录可读错误
  const seed = prepareDataRoot({ dataRoot: appConfig.dataRoot, seedDir: layout.dataSeedDir });
  if (seed.ok) {
    log(`数据根：${seed.dataRoot}（${seed.reason}；可写子目录 ${seed.createdDirs.length} 个）`);
  } else {
    log(`数据根不可用：${seed.error ?? seed.reason}`);
  }

  registerIpc();

  await ensureBackend();

  const devServerUrl = process.env.VITE_DEV_SERVER_URL;
  if (devServerUrl) {
    // 开发态：由 vite dev server 承担渲染层与 /api 代理，不启本地静态服务
    frontendUrl = devServerUrl;
    frontendPort = 0;
    log(`开发态加载 vite dev：${devServerUrl}`);
  } else {
    const handle = await startStaticServer({
      distDir: layout.frontendDistDir,
      // 反代目标必须为实际后端端点（顺延后不能再用配置里的 8300）
      backendBaseUrl,
      preferredPort: appConfig.preferredFrontendPort || DEFAULT_FRONTEND_PORT,
    });
    staticServerHandle = handle;
    frontendUrl = handle.url;
    frontendPort = handle.port;
    log(`本地静态服务就绪：${handle.url}（distDir=${layout.frontendDistDir}，反代 → ${backendBaseUrl}）`);
  }

  createWindow();
}

const gotSingleInstanceLock = app.requestSingleInstanceLock();

if (!gotSingleInstanceLock) {
  log("检测到已有实例，退出当前进程");
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("before-quit", (event) => {
    if (shuttingDown) return;
    shuttingDown = true;
    event.preventDefault();
    void (async () => {
      try {
        const result = await stopBackend();
        log(result.message);
        await closeStaticServer();
      } catch (error) {
        log(`退出清理失败：${error instanceof Error ? error.message : String(error)}`);
      } finally {
        app.quit();
      }
    })();
  });

  void app.whenReady().then(() =>
    bootstrap().catch((error: unknown) => {
      log(`启动失败：${error instanceof Error ? error.stack ?? error.message : String(error)}`);
      app.quit();
    }),
  );
}