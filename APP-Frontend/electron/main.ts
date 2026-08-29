/**
 * CXO-Pet Electron 主进程
 * ============================================================================
 * 多窗模型（桌宠多开优先）：
 *   1. petWindows       桌宠悬浮窗（多开，Map<agentId, BrowserWindow>）：按 agent 各一窗；
 *                       无边框透明、置顶、跳过任务栏，加载 /pet?agentId=<id>
 *   2. managementWindow 管理窗：默认不创建，IPC 唤起；原生标题栏、可调整
 *   3. danmakuWindow    弹幕窗：默认不创建，IPC 切换显示/隐藏；透明无边框
 *
 * 生命周期策略：
 *   桌宠窗 closed → 若为最后一个桌宠窗则退出应用；否则仅从 Map 移除。
 *   桌宠窗是应用本体，全部关闭即退出语义最直观；管理窗/弹幕窗关闭不退出。
 *
 * 窗口标题：桌宠窗标题为 'CXO-Pet-<agentId>'（page-title-updated 拦截），
 *   供 OBS 等采集端按窗口名区分多个桌宠。
 * ============================================================================
 */
import { app, BrowserWindow, desktopCapturer, dialog, session, Menu, Tray, nativeImage, globalShortcut, shell, powerMonitor } from 'electron';
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
import { registerIpcHandler } from './security';

// ESM 主进程下自行构造 __dirname（产物为 ESM 格式，Node 不注入该全局）
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// vite-plugin-electron 在开发模式注入 dev server 地址；生产模式为 undefined
const devServerUrl = process.env['VITE_DEV_SERVER_URL'];
const appIconPath = path.join(__dirname, devServerUrl ? '../public/icon.png' : '../dist/icon.png');

// 桌宠多开：多 Agent 各自一个独立悬浮窗，键为 agentId（见 createPetWindow）。
// `closed` 时若空（最后一个桌宠窗被关）才退出应用。
const petWindows = new Map<string, BrowserWindow>();
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
  physioUploader = new PhysioUploader({
    backendUrl,
    // 每轮上送前重新读取配置（G5b）：跟随设置页修改后的最新后端地址，
    // 解决构造期快照漂移；config.ts 的 getter 本身每次读盘即运行时刷新
    backendUrlResolver: () => getConfig('backendUrl'),
  });
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
function loadRoute(win: BrowserWindow, route: string): void {
  if (devServerUrl) {
    win.loadURL(route === '/' ? devServerUrl : `${devServerUrl}#${route}`);
  } else {
    const filePath = path.join(__dirname, '../dist/index.html');
    win.loadFile(filePath, route === '/' ? {} : { hash: route });
  }
}

/** 启动/重建桌宠窗使用的默认 agentId（优先持久化的 chatStore.currentAgentId，缺省 'default'） */
function getInitialPetAgentId(): string {
  try {
    const raw = loadStore('cxo-pet-chat');
    if (raw) {
      const parsed = JSON.parse(raw) as { state?: { currentAgentId?: string | null } };
      const id = parsed.state?.currentAgentId;
      if (id) return id;
    }
  } catch {
    // 持久化数据损坏时忽略，回退默认
  }
  return 'default';
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
// 1. 桌宠悬浮窗（多开：每 Agent 一窗，默认创建一个）
// ---------------------------------------------------------------------------
function createPetWindow(agentId: string): BrowserWindow {
  const normalized = String(agentId || 'default');
  const existing = petWindows.get(normalized);
  if (existing && !existing.isDestroyed()) {
    existing.focus();
    return existing;
  }

  const win = new BrowserWindow({
    // 标题按 agent 命名（CXO-Pet-<agentId>）供 OBS 按窗名区分多桌宠
    title: `CXO-Pet-${normalized}`,
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

  // 固定窗口标题为 CXO-Pet-<agentId>：阻止 document.title 覆盖，保证 OBS 按名捕获稳定
  win.on('page-title-updated', (event) => {
    event.preventDefault();
  });

  // 路由带 query 参数：HashRouter 下 /pet?agentId=<id> 仍落在 #/pet 段内，react-router 可从
  // useSearchParams 读取 agentId。桌宠窗按 agentId 各自绑定独立的会话/WS/TTS。
  loadRoute(win, `/pet?agentId=${encodeURIComponent(normalized)}`);

  win.on('closed', () => {
    petWindows.delete(normalized);
    // 最后一个桌宠窗关闭才退出应用（管理窗/弹幕窗关闭不触发）
    if (petWindows.size === 0 && !isQuitting) {
      app.quit();
    }
  });

  petWindows.set(normalized, win);
  return win;
}

/** 按 agentId 取对应桌宠窗；不存在或已销毁返回 null（供 IPC 幂等控制）。 */
function getPetWindow(agentId: string): BrowserWindow | null {
  const win = petWindows.get(agentId);
  if (win && !win.isDestroyed()) return win;
  return null;
}

/** 按 agentId 关闭对应桌宠窗；关闭最后一个桌宠窗会触发应用退出（见 closed 回调）。 */
function closePetWindow(agentId: string): void {
  const win = getPetWindow(agentId);
  if (win) win.close();
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

  // 关闭仅销毁窗口，不退出应用。
  // M-G 修复：闭包捕获局部 win 引用，closed 时比对模块级变量仍是本窗才置 null，
  // 防止旧窗迟到的销毁事件误清掉已被重建的新窗口引用。
  const win = managementWindow;
  win.on('closed', () => {
    if (managementWindow === win) managementWindow = null;
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

  // 关闭仅销毁窗口，不退出应用。
  // M-G 修复：闭包捕获局部 win 引用，closed 时比对模块级变量仍是本窗才置 null，
  // 防止旧窗迟到的销毁事件误清掉已被重建的新窗口引用（与管理窗同型竞态）。
  const win = danmakuWindow;
  win.on('closed', () => {
    if (danmakuWindow === win) danmakuWindow = null;
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
// VRM 模型读取白名单（R8-07）
// model:read-file 原仅校验 .vrm 后缀，受信渲染层可直读全盘任意 .vrm。收紧为：
//   1) 最近一次经系统对话框（model:pick-file）选中的路径（精确命中）
//   2) 历史会话中用户经对话框选过的目录（目录前缀命中）
// 目录集合持久化于 userData/store/cxo-pet-model-whitelist.json：pick 选中的
// 路径经渲染层 settingsStore 持久化，重启后 VRMViewer 直接以持久化路径恢复
// 加载（多 Agent 各自绑定不同模型），仅凭本会话 pick 记录会误杀该合法场景，
// 故白名单必须跨会话保留用户曾授权的目录。
// 比较统一 resolve 后小写（目标平台 Windows，路径大小写不敏感）。
// ---------------------------------------------------------------------------
let lastPickedModelPath: string | null = null;
const pickedModelDirs = new Set<string>();

/** 白名单比较用规范化：resolve 归一 + 小写（Windows 大小写不敏感语义） */
function normalizeModelPath(p: string): string {
  return path.resolve(p).toLowerCase();
}

/** 启动时从 userData/store 恢复历史 pick 目录白名单 */
function loadPickedModelDirs(): void {
  try {
    const raw = loadStore('cxo-pet-model-whitelist');
    if (!raw) return;
    const parsed = JSON.parse(raw) as { dirs?: unknown };
    if (!Array.isArray(parsed.dirs)) return;
    for (const dir of parsed.dirs) {
      if (typeof dir === 'string' && dir) pickedModelDirs.add(normalizeModelPath(dir));
    }
  } catch {
    // 白名单持久化损坏时忽略：回退空集合，仅影响跨会话恢复加载，pick 后自动重建
  }
}

/** 将历史 pick 目录白名单持久化到 userData/store */
function savePickedModelDirs(): void {
  try {
    saveStore('cxo-pet-model-whitelist', JSON.stringify({ dirs: [...pickedModelDirs] }));
  } catch {
    // 持久化失败不阻断 pick 主流程：本会话白名单仍在内存生效
  }
}

/** 白名单判定：最近 pick 路径精确命中，或位于历史 pick 目录内（目录前缀，含目录自身） */
function isWhitelistedModelPath(filePath: string): boolean {
  const normalized = normalizeModelPath(filePath);
  if (lastPickedModelPath && normalized === normalizeModelPath(lastPickedModelPath)) return true;
  for (const dir of pickedModelDirs) {
    if (normalized === dir || normalized.startsWith(dir + path.sep)) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// IPC 处理器
// ---------------------------------------------------------------------------
function registerIpcHandlers(): void {
  // 持久化存储（userData/store/<name>.json）
  registerIpcHandler('store:load', (_event, name: string) => loadStore(name));
  registerIpcHandler('store:save', (_event, name: string, data: string) => {
    saveStore(name, data);
  });

  // 窗口控制
  registerIpcHandler('window:open-management', () => {
    openManagementWindow();
  });

  // 桌宠多开：按 agentId 创建/聚焦对应桌宠窗（幂等）
  registerIpcHandler('window:open-pet', (_event, agentId: string) => {
    createPetWindow(String(agentId || 'default'));
  });

  // 桌宠多开：按 agentId 关闭对应桌宠窗（最后窗关闭触发应用退出）
  registerIpcHandler('window:close-pet', (_event, agentId: string) => {
    if (agentId) {
      closePetWindow(String(agentId));
      return;
    }
    // 兼容无参调用方：关闭发起窗
    const win = BrowserWindow.fromWebContents(_event.sender);
    if (win && !win.isDestroyed()) win.close();
  });

  // 桌宠多开：返回当前实际已开启的桌宠窗 agentId 列表（权威来源 = 主进程窗口），
  // 供管理页初始化时对齐 UI 的「开启」状态（覆盖启动默认窗等未写入面板记忆的来源）。
  registerIpcHandler('window:list-pet', () => {
    const ids: string[] = [];
    for (const [agentId, win] of petWindows) {
      if (win && !win.isDestroyed()) ids.push(agentId);
    }
    return ids;
  });

  // 在系统默认浏览器打开外部 URL（OBS 源预览等；仅放行 http/https，不放行 file:）
  registerIpcHandler('shell:open-external', (_event, url: string) => {
    if (typeof url !== 'string') return;
    if (/^https?:\/\//i.test(url)) {
      shell.openExternal(url);
    }
  });

  registerIpcHandler('window:toggle-danmaku', () => {
    toggleDanmakuWindow();
  });

  // 幂等显隐（启动恢复、托盘同步等场景语义确定）
  registerIpcHandler('window:set-danmaku-visible', (_event, visible: boolean) => {
    setDanmakuVisible(visible);
  });

  // 桌宠窗拖拽：增量坐标移动（渲染层记录按下点，逐帧回传 delta）
  // 坐标合法性校验对齐 window:set-size：非有限值直接忽略，防止 setPosition 写入 NaN。
  registerIpcHandler('window:move', (event, dx: number, dy: number) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win && !win.isDestroyed() && Number.isFinite(dx) && Number.isFinite(dy)) {
      const [currentX, currentY] = win.getPosition();
      win.setPosition(currentX + dx, currentY + dy);
    }
  });

  // 鼠标穿透：保留 forward 以便窗口重新收到 mousemove，避免离开窗口后永久卡在穿透态
  registerIpcHandler('window:set-ignore-mouse-events', (event, ignore: boolean) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win && !win.isDestroyed()) {
      win.setIgnoreMouseEvents(ignore, { forward: true });
    }
  });

  registerIpcHandler('window:set-always-on-top', (event, flag: boolean) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win && !win.isDestroyed()) {
      win.setAlwaysOnTop(flag);
    }
  });

  // 桌宠窗采集尺寸预设（SubTask 9.3）：渲染层下发目标尺寸，主进程 setSize。
  // 尺寸合法化（下限 300x400 对齐窗口 minWidth/minHeight）在渲染层 obsStore 完成，
  // 此处仅取整兜底；窗口最小尺寸约束由 Electron 自身强制。
  registerIpcHandler('window:set-size', (event, width: number, height: number) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win && !win.isDestroyed() && Number.isFinite(width) && Number.isFinite(height)) {
      win.setSize(Math.round(width), Math.round(height));
    }
  });

  // 后端地址配置（userData/config.json）
  registerIpcHandler('config:get-backend-url', () => getConfig('backendUrl'));
  registerIpcHandler('config:set-backend-url', (_event, url: string) => {
    setConfig('backendUrl', url);
  });

  // 前端启动配置（Task 5）：自启动 / 管理员权限启动，仅作用于前端 Electron。
  // 浏览器模式渲染层无 electronAPI，不会调用这些 IPC。
  registerIpcHandler('startup:get-settings', () => getStartupSettings());
  registerIpcHandler('startup:set-auto-start', (_event, enabled: boolean) => {
    setAutoStart(!!enabled);
    return getStartupSettings();
  });
  registerIpcHandler('startup:set-run-as-admin', (_event, enabled: boolean) => {
    setRunAsAdmin(!!enabled);
    return getStartupSettings();
  });

  // 电脑控制插件：授权状态读写 + 运行信息。
  // 渲染层不得直接执行本机控制，只能经主进程校验授权后调用插件（插件服务内部仍校验授权）。
  registerIpcHandler('computerControl:get-auth', () => getComputerControlAuthorization());
  registerIpcHandler('computerControl:set-auth', (_event, value: boolean) =>
    setComputerControlAuthorization(!!value),
  );
  registerIpcHandler('computerControl:get-info', () => getPluginInfo());

  // P2-T2 relay 推送路径：渲染层收到后端 cxfc_relay_call 后经主进程执行本机工具。
  // 沿用"渲染层不得直接执行本机控制"安全边界：执行前校验本地授权（与 /call HTTP 端点一致），
  // 未授权不执行任何本机动作。
  registerIpcHandler(
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
  registerIpcHandler('model:pick-file', async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    // 窗口可能已销毁（竞态）：win 可为 null，非空断言会同步抛错。校验后优雅降级取消。
    if (!win || win.isDestroyed()) {
      return { canceled: true, path: undefined };
    }
    const result = await dialog.showOpenDialog(win, {
      title: '选择 VRM 模型',
      filters: [{ name: 'VRM Model', extensions: ['vrm'] }],
      properties: ['openFile'],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { canceled: true, path: undefined };
    }
    const picked = result.filePaths[0];
    // R8-07：登记本次 pick 结果进读取白名单（精确路径 + 所在目录，目录集合持久化）
    lastPickedModelPath = picked;
    pickedModelDirs.add(normalizeModelPath(picked));
    savePickedModelDirs();
    return { canceled: false, path: picked };
  });

  // VRM 模型：读取本地 .vrm 文件为字节流（仅放行 .vrm 后缀，读取失败返回 null）。
  // 渲染层持 blob URL 交给 GLTFLoader，避免 file:// 跨域问题，dev(http) 与生产(file) 行为一致。
  // R8-07：叠加路径白名单——仅放行用户经系统对话框授权过的模型（见上方白名单区段）。
  registerIpcHandler('model:read-file', async (_event, filePath: string) => {
    try {
      if (typeof filePath !== 'string' || !/\.vrm$/i.test(filePath)) return null;
      if (!isWhitelistedModelPath(filePath)) return null;
      return await readFile(filePath);
    } catch {
      return null;
    }
  });

  // 手环心率 BLE 采集（Task 5 / spec：前端 Electron BLE 采集）。
  // 实时 HR / 状态 / 错误经主进程 webContents.send('ble:notify') 推送（见 ensureBleCollector）。
  registerIpcHandler('ble:scan', async () => {
    try {
      const result = await ensureBleCollector().startScan();
      return { ok: result.ok, status: result.status, devices: result.devices ?? [], error: result.error };
    } catch (err) {
      return { ok: false, status: ensureBleCollector().getStatus().status, devices: [], error: String(err) };
    }
  });

  registerIpcHandler('ble:connect', async (_event, deviceId: string) => {
    try {
      const result = await ensureBleCollector().connect(String(deviceId ?? ''));
      return { ok: result.ok, status: result.status, error: result.error };
    } catch (err) {
      return { ok: false, status: ensureBleCollector().getStatus().status, error: String(err) };
    }
  });

  registerIpcHandler('ble:disconnect', async () => {
    try {
      const result = await ensureBleCollector().disconnect();
      return { ok: result.ok, status: result.status, error: result.error };
    } catch (err) {
      return { ok: false, status: ensureBleCollector().getStatus().status, error: String(err) };
    }
  });

  registerIpcHandler('ble:status', () => ensureBleCollector().getStatus());
}

// ---------------------------------------------------------------------------
// 跨域放行（安全加固·收窄版）：仅对本机可信来源下发 CORS 头。
// 三态策略：
//   - Origin 缺失或 'null' → ACAO:'*' 保持放行
//     （打包态 file:// 渲染进程 fetch 表现为 null，一方壳可信，不能破坏自家页面）
//   - Origin 明确命中 http://localhost:* / http://127.0.0.1:*（任意端口）
//     → 回显该 Origin 放行（dev 场景，含 Vite dev server 3100）
//   - 其它明确 Origin → 不下发 Access-Control-Allow-Origin 头（log debug 记录）
// Allow-Headers 透传优先：后端已带该头时不覆盖，缺失时补写兜底值（含 x-api-key）；Methods 维持固定值。
// ---------------------------------------------------------------------------
function configureCors(): void {
  // dev 本机 Origin 白名单：任意端口的 localhost / 127.0.0.1，锚定结尾防伪装域
  const LOCAL_ORIGIN_RE = /^http:\/\/(?:localhost|127\.0\.0\.1):\d+$/i;

  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    // Origin 从请求头提取（键大小写不敏感）。
    // 注意：headersReceived 的官方类型不包含 requestHeaders（仅 beforeSendHeaders 声明），
    // 历史运行时部分 channel 仍携带；此处按可选读取，缺失时自然落入下方无-Origin 兜底分支。
    let requestOrigin: string | undefined;
    const rawReqHeaders = (details as { requestHeaders?: Record<string, string> }).requestHeaders ?? {};
    for (const [key, value] of Object.entries(rawReqHeaders)) {
      if (key.toLowerCase() === 'origin') {
        requestOrigin = String(value);
        break;
      }
    }

    let allowOrigin: string | null = null;
    if (!requestOrigin || requestOrigin === 'null') {
      // 打包态渲染进程为 file:// 页面：无 Origin 或 'null'，一方壳可信 → 保持放行
      allowOrigin = '*';
    } else if (LOCAL_ORIGIN_RE.test(requestOrigin)) {
      allowOrigin = requestOrigin; // dev 本机来源 → 回显该 Origin（窄于 *）
    } else {
      console.debug(`[cors] 未放行非本机 Origin，不下发 CORS 头: ${requestOrigin}`);
    }

    if (allowOrigin === null) {
      callback({ responseHeaders: details.responseHeaders }); // 其余来源不下发 CORS 头
      return;
    }

    const responseHeaders = details.responseHeaders ?? {};
    responseHeaders['Access-Control-Allow-Origin'] = [allowOrigin];
    responseHeaders['Access-Control-Allow-Methods'] = ['GET, POST, PUT, DELETE, OPTIONS'];
    // Allow-Headers 透传优先：后端 FastAPI CORSMiddleware 已下发更宽名单时不覆盖
    // （键大小写不敏感检测），仅在后端缺失该头时补写兜底值（含 x-api-key）。
    const hasAllowHeaders = Object.keys(responseHeaders).some(
      (key) => key.toLowerCase() === 'access-control-allow-headers',
    );
    if (!hasAllowHeaders) {
      responseHeaders['Access-Control-Allow-Headers'] = ['Content-Type, Authorization, x-api-key'];
    }
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
    // 每轮注册/心跳前重新读取配置（G5b）：跟随设置页修改后的最新后端地址
    backendUrlResolver: () => getConfig('backendUrl'),
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

// 单实例锁（模块顶层、whenReady 前最早生效）：startup.ts 的提权是经 PowerShell
// Start-Process 另启一个新实例且当前非提权实例继续运行，不加锁会造成双实例并存
// （争抢托盘/端口/配置）。拿锁失败 = 已有实例在跑，直接退出本实例。
// 提权场景下新提权实例会因锁被旧实例持有而退出——旧实例受控退出后才轮到新实例
// 正常创建窗口；若用户拒绝 UAC 则无新实例，当前实例照常运行（"设置未生效"语义不变）。
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
} else {
  // 第二个实例尝试启动时聚焦既有主窗口；已销毁则忽略
  app.on('second-instance', () => {
    for (const win of petWindows.values()) {
      if (win.isDestroyed()) continue;
      if (win.isMinimized()) win.restore();
      win.focus();
    }
    if (managementWindow && !managementWindow.isDestroyed()) {
      if (managementWindow.isMinimized()) managementWindow.restore();
      managementWindow.focus();
    }
  });
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  ensureDefaultConfig();
  loadPickedModelDirs();
  // 前端启动配置（Task 5）：若持久化 run_as_admin=true 且当前未提权，请求 UAC 提权 relaunch。
  // 返回 true = 已触发提权请求：当前实例必须受控退出让出单实例锁，否则新提权实例
  // 拿锁失败直接退出。延迟约 800ms（给 PowerShell UAC 弹窗弹出时间）后经既有
  // before-quit 清理路径退出；期间不再创建窗口/启动后台服务。
  try {
    if (applyStartupOnLaunch()) {
      setTimeout(() => {
        isQuitting = true;
        app.quit(); // 触发 before-quit：异步完成清理后 app.exit(0)
      }, 800);
      return;
    }
  } catch (err) {
    console.error('[startup] 启动时应用提权配置失败:', err);
  }
  registerIpcHandlers();
  registerNekoIpc();
  configureCors();
  configureDisplayMediaHandler();
  createPetWindow(getInitialPetAgentId());
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
      createPetWindow(getInitialPetAgentId());
    }
  });
});

// F5: before-quit 阻止默认退出，异步完成清理（CXFC 注销/端口释放/子进程回收）后
// 再 app.exit——原 will-quit 对多个异步回收全部 void 不等待，进程可能提前退出，
// 导致注销未发出（后端残留死插件元数据）、HTTP/HTTPS server 端口残留占用。
let quitCleanupDone = false;

app.on('before-quit', (event) => {
  isQuitting = true;
  if (quitCleanupDone) return;
  quitCleanupDone = true;
  event.preventDefault();
  globalShortcut.unregisterAll();
  void (async () => {
    try {
      // 总超时兜底：任一清理步骤挂起（网络注销超时/子进程回收卡死等）时 8s 后
      // 强制继续退出，防止进程无法关闭
      const timeout = new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), 8000));
      const result = await Promise.race([
        Promise.allSettled([
          // 停止 CXFC 注册并注销插件（Task 3）
          stopCxfcRegistration(),
          // 停止电脑控制插件 HTTPS 服务，回收端口与连接
          stopComputerControlPlugin(),
          // 停止 Neko 插件运行时 sidecar 与工具→CXFC 桥，回收子进程/接口
          stopNekoRuntime(),
          // 停止生理信号上送后台任务并断开 BLE（Task 5）
          stopPhysioBackground(),
        ]),
        timeout,
      ]);
      if (result === 'timeout') console.error('[quit] cleanup timeout, forcing exit');
    } finally {
      app.exit(0);
    }
  })();
});

app.on('window-all-closed', () => {
  // 所有窗口关闭即退出（桌宠窗关闭已先行触发 quit，此处为兜底）
  app.quit();
});
