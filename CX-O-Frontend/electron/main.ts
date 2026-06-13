import { app, BrowserWindow, ipcMain, session, Menu } from 'electron';
import * as path from 'node:path';
import { loadStore, saveStore } from './store';
import { getConfig, setConfig } from './config';

let mainWindow: BrowserWindow | null = null;
let petWindow: BrowserWindow | null = null;

const isDev = !app.isPackaged;

function createMainWindow(): BrowserWindow {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:3000');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

function createPetWindow(): BrowserWindow {
  petWindow = new BrowserWindow({
    width: 400,
    height: 500,
    frame: false,
    alwaysOnTop: true,
    transparent: true,
    backgroundColor: '#00000000',
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  petWindow.setIgnoreMouseEvents(true, { forward: true });

  if (isDev) {
    petWindow.loadURL('http://localhost:3000/#/pet');
  } else {
    petWindow.loadFile(path.join(__dirname, '../dist/index.html'), { hash: '/pet' });
  }

  petWindow.on('closed', () => {
    petWindow = null;
  });

  return petWindow;
}

function registerIpcHandlers(): void {
  // Store handlers
  ipcMain.handle('store:load', (_event, name: string) => {
    return loadStore(name);
  });

  ipcMain.handle('store:save', (_event, name: string, data: string) => {
    saveStore(name, data);
  });

  // Window control handlers
  ipcMain.handle('window:open-pet', () => {
    if (!petWindow || petWindow.isDestroyed()) {
      createPetWindow();
    } else {
      petWindow.show();
    }
  });

  ipcMain.handle('window:close-pet', () => {
    if (petWindow && !petWindow.isDestroyed()) {
      petWindow.close();
    }
  });

  ipcMain.handle('window:toggle-pet', () => {
    if (!petWindow || petWindow.isDestroyed()) {
      createPetWindow();
    } else if (petWindow.isVisible()) {
      petWindow.hide();
    } else {
      petWindow.show();
    }
  });

  ipcMain.handle('window:move', (_event, dx: number, dy: number) => {
    if (petWindow && !petWindow.isDestroyed()) {
      const [currentX, currentY] = petWindow.getPosition();
      petWindow.setPosition(currentX + dx, currentY + dy);
    }
  });

  ipcMain.handle('window:set-ignore-mouse-events', (_event, ignore: boolean) => {
    if (petWindow && !petWindow.isDestroyed()) {
      petWindow.setIgnoreMouseEvents(ignore, { forward: true });
    }
  });

  // Config handlers
  ipcMain.handle('config:get-backend-url', () => {
    return getConfig('backendUrl');
  });

  ipcMain.handle('config:set-backend-url', (_event, url: string) => {
    setConfig('backendUrl', url);
  });
}

async function configureCors(): Promise<void> {
  // Allow cross-origin requests from the renderer to the backend
  await session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    callback({ requestHeaders: details.requestHeaders });
  });

  // Add CORS response headers so the renderer can read backend responses
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const responseHeaders = details.responseHeaders ?? {};
    responseHeaders['Access-Control-Allow-Origin'] = ['*'];
    responseHeaders['Access-Control-Allow-Methods'] = ['GET, POST, PUT, DELETE, OPTIONS'];
    responseHeaders['Access-Control-Allow-Headers'] = ['Content-Type, Authorization'];
    responseHeaders['Access-Control-Allow-Credentials'] = ['true'];
    callback({ responseHeaders });
  });
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  registerIpcHandlers();
  await configureCors();
  createMainWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    } else if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
    }
  });
});

app.on('window-all-closed', () => {
  // On macOS, keep the app running even when all windows are closed
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
