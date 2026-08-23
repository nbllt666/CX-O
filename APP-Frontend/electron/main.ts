/**
 * CXO-Pet Electron 主进程
 * ============================================================================
 * 三窗模型（桌宠优先）：
 *   1. petWindow        桌宠悬浮窗：默认创建；无边框透明、置顶、跳过任务栏
 *   2. managementWindow 管理窗：默认不创建，IPC 唤起；原生标题栏、可调整
 *   3. danmakuWindow    弹幕窗：默认不创建，IPC 切换显示/隐藏；透明无边框
 *
 * 生命周期策略（二选一，本工程选择 A）：
 *   A. 桌宠窗关闭 → 退出应用（当前实现）。桌宠是应用本体，关闭即退出语义最直观
 *   B. 托盘常驻：桌宠窗关闭仅隐藏。若后续需切换，仅需在 petWindow 'closed'
 *      回调中改为 petWindow = null 并移除 app.quit() 调用
 *
 * 窗口标题：桌宠窗标题固定为 'CXO-Pet'（page-title-updated 拦截），
 *   供 OBS 等采集端按窗口名稳定捕获。
 * ============================================================================
 */
import { app, BrowserWindow, desktopCapturer, dialog, ipcMain, session, Menu, Tray, nativeImage, globalShortcut, shell, powerMonitor } from 'electron';
import type { NativeImage } from 'electron';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
import { loadStore, saveStore } from './store';
import { getConfig, setConfig } from './config';
import { BleHeartRateCollector } from './ble/ble_collector';
import { PhysioUploader } from './ble/uploader';
import {
  startComputerControlPlugin,
  stopComputerControlPlugin,
  getComputerControlAuthorization,
  setComputerControlAuthorization,
  getPluginInfo,
  callComputerControlTool,
  type ComputerControlPlugin,
} from './plugins/computerControl/index';
import { createCxfcClient, type CxfcClient, type PluginRuntimeInfo } from './cxfc/client';
import {
  applyStartupOnLaunch,
  getStartupSettings,
  setAutoStart,
  setRunAsAdmin,
} from './startup';
import { registerNekoIpc } from './neko/ipc';
import { getNekoConfig, startNekoRuntime, stopNekoRuntime } from './neko/launcher';

// ESM 主进程下自行构造 __dirname（产物为 ESM 格式，Node 不注入该全局）
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// vite-plugin-electron 在开发模式注入 dev server 地址；生产模式为 undefined
const devServerUrl = process.env['VITE_DEV_SERVER_URL'];
const appIconPath = path.join(__dirname, devServerUrl ? '../public/icon.png' : '../dist/icon.png');

let petWindow: BrowserWindow | null = null;
let managementWindow: BrowserWindow | null = null;
let danmakuWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let isQuitting = false;
let cxfcClient: CxfcClient | null = null;

// 手环心率 BLE 采集（Task 5 / spec：前端 Electron BLE 采集）
// collector 懒加载：渲染层首次调用 ble:* IPC 才创建（noble 原生依赖缺失时 graceful 降级）
let bleCollector: BleHeartRateCollector | null = null;
let physioUploader: PhysioUploader | null = null;
let physioBackgroundStarted = false;

/** 向所有窗口广播（ble:notify 实时 HR/状态推送等）。 */
function broadcastToAll(channel: string, payload: unknown): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send(channel, payload);
    }
  }
}

/** 懒创建 BLE 采集器（含 HR→IPC 广播 + ≤1Hz REST 上送接线）。 */
function ensureBleCollector(): BleHeartRateCollector {
  if (!bleCollector) {
    bleCollector = new BleHeartRateCollector(
      {
        scanTimeoutSec: 15,
        deviceNameHint: getConfig('physioDeviceNameHint') || '',
        reconnectIntervalSec: 30,
      },
      {
        onHr: (bpm) => {
          // 实时 HR 推给渲染进程（ble:notify）
          broadcastToAll('ble:notify', { type: 'hr', bpm, ts: Date.now() });
          // 后台任务：≤1Hz 节流上送后端（PhysioUploader 内部节流；离线丢弃不积压）
          const fingerprint = bleCollector?.getDeviceFingerprint();
          if (fingerprint && physioUploader) {
            // ts 上送 epoch 秒（对齐 HrSample 契约；后端 _parse_ts 兼容毫秒/秒）
            void physioUploader.reportHr({ bpm, ts: Math.floor(Date.now() / 1000), device_fingerprint: fingerprint });
          }
        },
        onStatus: (status, detail) =>
          broadcastToAll('ble:notify', { type: 'status', status, detail }),
        onError: (error, context) =>
          broadcastToAll('ble:notify', { type: 'error', context, message: String(error) }),
      },
    );
  }
  return bleCollector;
}

/**
 * 启动生理信号上送后台任务：
 *  - HR 样本：由 onHr 接线经 PhysioUploader.reportHr（≤1Hz）上送
 *  - 系统静默：≥30s 周期，powerMonitor.getSystemIdleTime() 构造载荷
 */
function startPhysioBackground(): void {
  if (physioBackgroundStarted) return;
  physioBackgroundStarted = true;
  const backendUrl = getConfig('backendUrl') || 'http://127.0.0.1:8000';
  physioUploader = new PhysioUploader({ backendUrl });
  physioUploader.startIdleReport(() => {
    const systemIdleSec = powerMonitor.getSystemIdleTime();
    return { system_idle_sec: systemIdleSec, user_active: systemIdleSec < 60 };
  });
  console.log(`[physio] 生理信号上送后台任务已启动（后端 ${backendUrl}）`);
}

async function stopPhysioBackground(): Promise<void> {
  physioBackgroundStarted = false;
  physioUploader?.stop();
  physioUploader = null;
  if (bleCollector) {
    try {
      await bleCollector.disconnect();
    } catch {
      // 忽略退出时的断开异常
    }
  }
}

/** 渲染层路由加载：开发模式走 dev server + hash 路由，生产模式走静态文件 */
function loadRoute(win: BrowserWindow, route: '/' | '/pet' | '/danmaku'): void {
  if (devServerUrl) {
    win.loadURL(route === '/' ? devServerUrl : `${devServerUrl}#${route}`);
  } else {
    const filePath = path.join(__dirname, '../dist/index.html');
    win.loadFile(filePath, route === '/' ? {} : { hash: route });
  }
}

/**
 * 共享 webPreferences。
 * 注：ESM 预加载（.mjs）要求 sandbox:false；安全边界由 contextIsolation:true
 * + nodeIntegration:false 保证（页面侧仍无法触碰 Node API，仅经 contextBridge）。
 */
function sharedWebPreferences(): Electron.WebPreferences {
  return {
    preload: path.join(__dirname, 'preload.mjs'),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: false,
  };
}

// ---------------------------------------------------------------------------
// 1. 桌宠悬浮窗（默认创建）
// ---------------------------------------------------------------------------
function createPetWindow(): BrowserWindow {
  petWindow = new BrowserWindow({
    title: 'CXO-Pet',
    width: 400,
    height: 500,
    minWidth: 300,
    minHeight: 400,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    resizable: true,
    fullscreenable: false,
    icon: appIconPath,
    webPreferences: sharedWebPreferences(),
  });

  // 固定窗口标题为 CXO-Pet：阻止 document.title 覆盖，保证 OBS 按名捕获稳定
  petWindow.on('page-title-updated', (event) => {
    event.preventDefault();
  });

  loadRoute(petWindow, '/pet');

  petWindow.on('closed', () => {
    petWindow = null;
    // 策略 A：桌宠窗关闭即退出应用（见文件头注释）
    if (!isQuitting) {
      app.quit();
    }
  });

  return petWindow;
}

// ---------------------------------------------------------------------------
// 2. 管理窗（按需创建或聚焦）
// ---------------------------------------------------------------------------
function openManagementWindow(): BrowserWindow {
  if (managementWindow && !managementWindow.isDestroyed()) {
    managementWindow.focus();
    return managementWindow;
  }

  managementWindow = new BrowserWindow({
    title: 'CXO-Pet 管理界面',
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    show: false,
    backgroundColor: '#12121a', // 与暗色主题底色一致，减少白闪
    icon: appIconPath,
    webPreferences: sharedWebPreferences(),
  });

  managementWindow.once('ready-to-show', () => {
    managementWindow?.show();
  });

  loadRoute(managementWindow, '/');

  if (devServerUrl) {
    managementWindow.webContents.openDevTools({ mode: 'detach' });
  }

  // 关闭仅销毁窗口，不退出应用
  managementWindow.on('closed', () => {
    managementWindow = null;
  });

  return managementWindow;
}

// ---------------------------------------------------------------------------
// 3. 弹幕窗（按需创建；幂等显隐 + 显隐变化通知渲染层）
// ---------------------------------------------------------------------------
function createDanmakuWindow(): BrowserWindow {
  danmakuWindow = new BrowserWindow({
    title: 'CXO-Pet 弹幕',
    width: 960,
    height: 600,
    minWidth: 480,
    minHeight: 320,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    icon: appIconPath,
    webPreferences: sharedWebPreferences(),
  });

  loadRoute(danmakuWindow, '/danmaku');

  // 关闭仅销毁窗口，不退出应用
  danmakuWindow.on('closed', () => {
    danmakuWindow = null;
  });
  return danmakuWindow;
}

/** 显隐变化时通知渲染层，供 danmakuStore 同步持久化记忆 */
function notifyDanmakuVisibility(visible: boolean): void {
  if (danmakuWindow && !danmakuWindow.isDestroyed()) {
    danmakuWindow.webContents.send('danmaku:visibility-changed', visible);
  }
}

/** 幂等设置弹幕窗显隐（恢复场景语义确定，区别于 toggle） */
function setDanmakuVisible(visible: boolean): void {
  if (!danmakuWindow || danmakuWindow.isDestroyed()) {
    if (!visible) return;
    createDanmakuWindow();
    notifyDanmakuVisibility(true);
    return;
  }
  if (visible) {
    danmakuWindow.show();
  } else {
    danmakuWindow.hide();
  }
  notifyDanmakuVisibility(visible);
}

function toggleDanmakuWindow(): void {
  const currentlyVisible = !!(
    danmakuWindow &&
    !danmakuWindow.isDestroyed() &&
    danmakuWindow.isVisible()
  );
  setDanmakuVisible(!currentlyVisible);
}

// ---------------------------------------------------------------------------
// 系统托盘
// ---------------------------------------------------------------------------

function createTrayIcon(): NativeImage {
  return nativeImage.createFromPath(appIconPath).resize({ width: 16, height: 16 });
}

function createTray(): void {
  tray = new Tray(createTrayIcon());
  tray.setToolTip('CXO-Pet 桌宠');
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '打开管理界面', click: () => openManagementWindow() },
      { label: '显示/隐藏弹幕窗', click: () => toggleDanmakuWindow() },
      {
        // 弹幕窗鼠标穿透开启后窗口不可交互，此处作为恢复入口
        label: '关闭弹幕窗鼠标穿透',
        click: () => {
          if (danmakuWindow && !danmakuWindow.isDestroyed()) {
            danmakuWindow.setIgnoreMouseEvents(false, { forward: true });
          }
        },
      },
      { type: 'separator' },
      {
        label: '退出应用',
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]),
  );
}

// ---------------------------------------------------------------------------
// IPC 处理器
// ---------------------------------------------------------------------------
function registerIpcHandlers(): void {
  // 持久化存储（userData/store/<name>.json）
  ipcMain.handle('store:load', (_event, name: string) => loadStore(name));
  ipcMain.handle('store:save', (_event, name: string, data: string) => {
    saveStore(name, data);
  });

  // 窗口控制
  ipcMain.handle('window:open-management', () => {
    openManagementWindow();
  });

  // 在系统默认浏览器打开外部 URL（OBS 源预览等；仅放行 http/https/file）
  ipcMain.handle('shell:open-external', (_event, url: string) => {
    if (typeof url !== 'string') return;
    if (/^(https?:|file:)/i.test(url)) {
      shell.openExternal(url);
    }
  });

  ipcMain.handle('window:toggle-danmaku', () => {
    toggleDanmakuWindow();
  });

  ipcMain.handle('window:close-pet', () => {
    isQuitting = true;
    app.quit();
  });

  // 幂等显隐（启动恢复、托盘同步等场景语义确定）
  ipcMain.handle('window:set-danmaku-visible', (_event, visible: boolean) => {
    setDanmakuVisible(visible);
  });

  // 桌宠窗拖拽：增量坐标移动（渲染层记录按下点，逐帧回传 delta）
  ipcMain.handle('window:move', (event, dx: number, dy: number) => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? petWindow;
    if (win && !win.isDestroyed()) {
      const [currentX, currentY] = win.getPosition();
      win.setPosition(currentX + dx, currentY + dy);
    }
  });

  // 鼠标穿透：保留 forward 以便窗口重新收到 mousemove，避免离开窗口后永久卡在穿透态
  ipcMain.handle('window:set-ignore-mouse-events', (event, ignore: boolean) => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? petWindow;
    if (win && !win.isDestroyed()) {
      win.setIgnoreMouseEvents(ignore, { forward: true });
    }
  });

  ipcMain.handle('window:set-always-on-top', (event, flag: boolean) => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? petWindow;
    if (win && !win.isDestroyed()) {
      win.setAlwaysOnTop(flag);
    }
  });

  // 桌宠窗采集尺寸预设（SubTask 9.3）：渲染层下发目标尺寸，主进程 setSize。
  // 尺寸合法化（下限 300x400 对齐窗口 minWidth/minHeight）在渲染层 obsStore 完成，
  // 此处仅取整兜底；窗口最小尺寸约束由 Electron 自身强制。
  ipcMain.handle('window:set-size', (event, width: number, height: number) => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? petWindow;
    if (win && !win.isDestroyed() && Number.isFinite(width) && Number.isFinite(height)) {
      win.setSize(Math.round(width), Math.round(height));
    }
  });

  // 后端地址配置（userData/config.json）
  ipcMain.handle('config:get-backend-url', () => getConfig('backendUrl'));
  ipcMain.handle('config:set-backend-url', (_event, url: string) => {
    setConfig('backendUrl', url);
  });

  // 前端启动配置（Task 5）：自启动 / 管理员权限启动，仅作用于前端 Electron。
  // 浏览器模式渲染层无 electronAPI，不会调用这些 IPC。
  ipcMain.handle('startup:get-settings', () => getStartupSettings());
  ipcMain.handle('startup:set-auto-start', (_event, enabled: boolean) => {
    setAutoStart(!!enabled);
    return getStartupSettings();
  });
  ipcMain.handle('startup:set-run-as-admin', (_event, enabled: boolean) => {
    setRunAsAdmin(!!enabled);
    return getStartupSettings();
  });

  // 电脑控制插件：授权状态读写 + 运行信息。
  // 渲染层不得直接执行本机控制，只能经主进程校验授权后调用插件（插件服务内部仍校验授权）。
  ipcMain.handle('computerControl:get-auth', () => getComputerControlAuthorization());
  ipcMain.handle('computerControl:set-auth', (_event, value: boolean) =>
    setComputerControlAuthorization(!!value),
  );
  ipcMain.handle('computerControl:get-info', () => getPluginInfo());

  // P2-T2 relay 推送路径：渲染层收到后端 cxfc_relay_call 后经主进程执行本机工具。
  // 沿用"渲染层不得直接执行本机控制"安全边界：执行前校验本地授权（与 /call HTTP 端点一致），
  // 未授权不执行任何本机动作。
  ipcMain.handle(
    'computerControl:call-tool',
    (_event, tool: string, args: Record<string, unknown>) => {
      if (!getComputerControlAuthorization()) {
        return {
          ok: false,
          code: 'NOT_AUTHORIZED',
          error: '本地授权未开启（授权被撤销或尚未授权）。不执行任何本机动作。',
        };
      }
      return callComputerControlTool(tool, args ?? {});
    },
  );

  // VRM 模型：桌面模式模型选择（默认模型打包在包内，用户可选本地 .vrm 覆盖）。
  // 安全边界：仅返回用户经系统对话框选中的 .vrm 路径；渲染层无法任意枚举文件系统。
  ipcMain.handle('model:pick-file', async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender) ?? petWindow;
    const result = await dialog.showOpenDialog(win!, {
      title: '选择 VRM 模型',
      filters: [{ name: 'VRM Model', extensions: ['vrm'] }],
      properties: ['openFile'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { canceled: true, path: undefined };
    }
    return { canceled: false, path: result.filePaths[0] };
  });

  // VRM 模型：读取本地 .vrm 文件为字节流（仅放行 .vrm 后缀，读取失败返回 null）。
  // 渲染层持 blob URL 交给 GLTFLoader，避免 file:// 跨域问题，dev(http) 与生产(file) 行为一致。
  ipcMain.handle('model:read-file', async (_event, filePath: string) => {
    try {
      if (typeof filePath !== 'string' || !/\.vrm$/i.test(filePath)) return null;
      return await readFile(filePath);
    } catch {
      return null;
    }
  });

  // 手环心率 BLE 采集（Task 5 / spec：前端 Electron BLE 采集）。
  // 实时 HR / 状态 / 错误经主进程 webContents.send('ble:notify') 推送（见 ensureBleCollector）。
  ipcMain.handle('ble:scan', async () => {
    try {
      const result = await ensureBleCollector().startScan();
      return { ok: result.ok, status: result.status, devices: result.devices ?? [], error: result.error };
    } catch (err) {
      return { ok: false, status: ensureBleCollector().getStatus().status, devices: [], error: String(err) };
    }
  });

  ipcMain.handle('ble:connect', async (_event, deviceId: string) => {
    try {
      const result = await ensureBleCollector().connect(String(deviceId ?? ''));
      return { ok: result.ok, status: result.status, error: result.error };
    } catch (err) {
      return { ok: false, status: ensureBleCollector().getStatus().status, error: String(err) };
    }
  });

  ipcMain.handle('ble:disconnect', async () => {
    try {
      const result = await ensureBleCollector().disconnect();
      return { ok: result.ok, status: result.status, error: result.error };
    } catch (err) {
      return { ok: false, status: ensureBleCollector().getStatus().status, error: String(err) };
    }
  });

  ipcMain.handle('ble:status', () => ensureBleCollector().getStatus());
}

// ---------------------------------------------------------------------------
// 跨域放行：前后端分离部署时，渲染进程需直连远端后端
// ---------------------------------------------------------------------------
function configureCors(): void {
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const responseHeaders = details.responseHeaders ?? {};
    responseHeaders['Access-Control-Allow-Origin'] = ['*'];
    responseHeaders['Access-Control-Allow-Methods'] = ['GET, POST, PUT, DELETE, OPTIONS'];
    responseHeaders['Access-Control-Allow-Headers'] = ['Content-Type, Authorization'];
    callback({ responseHeaders });
  });
}

/** 首次启动写入默认后端地址（auto_init：缺省自动补全） */
function ensureDefaultConfig(): void {
  if (!getConfig('backendUrl')) {
    setConfig('backendUrl', 'http://127.0.0.1:8000');
  }
}

// ---------------------------------------------------------------------------
// 屏幕共享采集授权（SubTask 4.6）
// 渲染层 navigator.mediaDevices.getDisplayMedia() 在 Electron 下必须经主进程
// setDisplayMediaRequestHandler 授权，否则 Promise 永不 resolve。
// 策略：授权主屏幕源（screen 列表第一项），不弹选择器——桌宠场景一键开关，
// 多屏选择归后续设置页增强。摄像头走 getUserMedia，不经此 handler。
// ---------------------------------------------------------------------------
function configureDisplayMediaHandler(): void {
  session.defaultSession.setDisplayMediaRequestHandler((_request, callback) => {
    desktopCapturer
      .getSources({ types: ['screen'] })
      .then((sources) => {
        if (sources.length > 0) {
          callback({ video: sources[0] });
        } else {
          callback({});
        }
      })
      .catch(() => callback({}));
  });
}

// ---------------------------------------------------------------------------
// 电脑控制 CXFC 注册（Task 3）：插件服务启动后向后端注册并维持心跳
// ---------------------------------------------------------------------------
const CXFC_TOOLS = [
  {
    name: 'computer_screen_control',
    description: '屏幕控制：capture/click/move/scroll',
    parameters: { action: 'string', x: 'number', y: 'number' },
    returns: {},
  },
  {
    name: 'computer_keyboard_control',
    description: '键盘控制：type/key/press/hotkey',
    parameters: { action: 'string', text: 'string', key: 'string' },
    returns: {},
  },
  {
    name: 'computer_run_command',
    description: '运行指令：结构化 command+args+cwd+timeout_ms+env 白名单',
    parameters: { command: 'string', args: 'string[]', cwd: 'string', timeout_ms: 'number' },
    returns: {},
  },
];

function buildCxfcRuntimeInfo(plugin: ComputerControlPlugin): PluginRuntimeInfo {
  return {
    host: '127.0.0.1',
    port: plugin.getPort(),
    name: 'APP-Frontend 电脑控制插件',
    version: '1.0.0',
    capabilities: ['computer_control'],
    tools: CXFC_TOOLS,
    skills: [],
    token: plugin.token,
    tls_cert_fingerprint: plugin.getFingerprint(),
    // B-1：注册载荷携带自签名证书 PEM 原文，供后端 TOFU 首次信任（证书固定）与 https 访问
    tls_cert_pem: plugin.getTlsCertPem(),
  };
}

/** 插件启动成功后调用：以后端地址为基址注册并维持心跳；后端不可用自动重连。 */
function startCxfcRegistration(plugin: ComputerControlPlugin): void {
  const backendUrl = getConfig('backendUrl') || 'http://127.0.0.1:8000';
  cxfcClient = createCxfcClient({
    backendUrl,
    readPluginInfo: () => buildCxfcRuntimeInfo(plugin),
    logger: (line) => console.log(line),
  });
  cxfcClient.start();
}

async function stopCxfcRegistration(): Promise<void> {
  if (!cxfcClient) return;
  try {
    await cxfcClient.stop();
  } finally {
    cxfcClient = null;
  }
}

// ---------------------------------------------------------------------------
// 应用生命周期
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  ensureDefaultConfig();
  // 前端启动配置（Task 5）：若持久化 run_as_admin=true 且当前未提权，请求 UAC 提权 relaunch。
  // 用户拒绝 UAC 时当前实例保持可用（不阻断后续窗口创建）。
  try {
    applyStartupOnLaunch();
  } catch (err) {
    console.error('[startup] 启动时应用提权配置失败:', err);
  }
  registerIpcHandlers();
  registerNekoIpc();
  configureCors();
  configureDisplayMediaHandler();
  createPetWindow();
  createTray();

  // 生理信号上送后台任务（Task 5）：系统静默 ≥30s 上送；HR 由 onHr 接线 ≤1Hz 上送。
  // 后台任务失败不阻断主流程（PhysioUploader 内部已隔离异常）。
  try {
    startPhysioBackground();
  } catch (err) {
    console.error('[physio] 生理信号后台上送任务启动失败:', err);
  }

  // Neko 插件运行时 + 工具→CXFC 桥：若配置了自动启动，异步拉起（不阻断主流程）
  try {
    if (getNekoConfig().autoStart) {
      startNekoRuntime()
        .then(({ port, bridge }) => console.log(`[neko] 插件服务器已自动启动，端口 ${port}，工具桥=${bridge}`))
        .catch((err) => console.error('[neko] 自动启动失败:', err));
    }
  } catch (err) {
    console.error('[neko] 自动启动检查失败:', err);
  }

  // 电脑控制插件：随应用启动 HTTPS 插件服务（异步，失败不阻断主流程）
  startComputerControlPlugin()
    .then((plugin) => {
      // Task 3：插件服务就绪后向后端注册并维持心跳/重连/注销
      startCxfcRegistration(plugin);
    })
    .catch((err) => {
      console.error('[computerControl] 插件启动失败:', err);
    });

  // 全局快捷键：Ctrl/Cmd+Shift+D 切换弹幕窗
  globalShortcut.register('CommandOrControl+Shift+D', () => toggleDanmakuWindow());

  // 恢复弹幕窗显隐记忆（渲染层 danmakuStore 经 store:save 持久化）
  try {
    const raw = loadStore('cxo-pet-danmaku');
    if (raw) {
      const parsed = JSON.parse(raw) as { state?: { visible?: boolean } };
      if (parsed.state?.visible) {
        setDanmakuVisible(true);
      }
    }
  } catch {
    // 持久化数据损坏时忽略，保持默认隐藏
  }

  app.on('activate', () => {
    // macOS：点击 dock 图标时若无窗口则重建桌宠窗
    if (BrowserWindow.getAllWindows().length === 0) {
      createPetWindow();
    }
  });
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  // 停止 CXFC 注册并注销插件（Task 3）
  void stopCxfcRegistration();
  // 停止电脑控制插件 HTTPS 服务，回收端口与连接
  void stopComputerControlPlugin();
  // 停止 Neko 插件运行时 sidecar 与工具→CXFC 桥，回收子进程/接口
  void stopNekoRuntime();
  // 停止生理信号上送后台任务并断开 BLE（Task 5）
  void stopPhysioBackground();
});

app.on('before-quit', () => {
  isQuitting = true;
});

app.on('window-all-closed', () => {
  // 所有窗口关闭即退出（桌宠窗关闭已先行触发 quit，此处为兜底）
  app.quit();
});
