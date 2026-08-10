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
import { app, BrowserWindow, desktopCapturer, ipcMain, session, Menu, Tray, nativeImage, globalShortcut } from 'electron';
import type { NativeImage } from 'electron';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadStore, saveStore } from './store';
import { getConfig, setConfig } from './config';

// ESM 主进程下自行构造 __dirname（产物为 ESM 格式，Node 不注入该全局）
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// vite-plugin-electron 在开发模式注入 dev server 地址；生产模式为 undefined
const devServerUrl = process.env['VITE_DEV_SERVER_URL'];

let petWindow: BrowserWindow | null = null;
let managementWindow: BrowserWindow | null = null;
let danmakuWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let isQuitting = false;

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

/** 运行时生成 16x16 樱花粉占位图标（BGRA 位图），后续可替换为 assets 下的真实 PNG */
function createTrayIcon(): NativeImage {
  const size = 16;
  const buffer = Buffer.alloc(size * size * 4);
  for (let i = 0; i < size * size; i++) {
    buffer[i * 4 + 0] = 0xe1; // B
    buffer[i * 4 + 1] = 0xb7; // G
    buffer[i * 4 + 2] = 0xff; // R（#FFB7E1 樱花粉）
    buffer[i * 4 + 3] = 0xff; // A
  }
  return nativeImage.createFromBitmap(buffer, { width: size, height: size });
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
// 应用生命周期
// ---------------------------------------------------------------------------
app.whenReady().then(() => {
  Menu.setApplicationMenu(null);
  ensureDefaultConfig();
  registerIpcHandlers();
  configureCors();
  configureDisplayMediaHandler();
  createPetWindow();
  createTray();

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
});

app.on('before-quit', () => {
  isQuitting = true;
});

app.on('window-all-closed', () => {
  // 所有窗口关闭即退出（桌宠窗关闭已先行触发 quit，此处为兜底）
  app.quit();
});
