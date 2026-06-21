import { app, Menu, BrowserWindow, ipcMain, session } from "electron";
import * as path from "node:path";
import * as fs from "node:fs";
function getStoreDir() {
  const userData = app.getPath("userData");
  const storeDir = path.join(userData, "store");
  if (!fs.existsSync(storeDir)) {
    fs.mkdirSync(storeDir, { recursive: true });
  }
  return storeDir;
}
function loadStore(name) {
  const filePath = path.join(getStoreDir(), `${name}.json`);
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch (error) {
    if (error.code === "ENOENT") {
      return null;
    }
    throw error;
  }
}
function saveStore(name, data) {
  const filePath = path.join(getStoreDir(), `${name}.json`);
  fs.writeFileSync(filePath, data, "utf-8");
}
function getConfigPath() {
  return path.join(app.getPath("userData"), "config.json");
}
function readConfig() {
  const configPath = getConfigPath();
  try {
    const data = fs.readFileSync(configPath, "utf-8");
    return JSON.parse(data);
  } catch (error) {
    if (error.code === "ENOENT") {
      return {};
    }
    throw error;
  }
}
function writeConfig(config) {
  const configPath = getConfigPath();
  try {
    fs.writeFileSync(configPath, JSON.stringify(config, null, 2), "utf-8");
  } catch (error) {
    console.error(`Failed to write config to ${configPath}:`, error);
  }
}
function getConfig(key) {
  const config = readConfig();
  return config[key] ?? null;
}
function setConfig(key, value) {
  const config = readConfig();
  config[key] = value;
  writeConfig(config);
}
let mainWindow = null;
let petWindow = null;
const isDev = !app.isPackaged;
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  if (isDev) {
    mainWindow.loadURL("http://localhost:3000");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, "../dist/index.html"));
  }
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  return mainWindow;
}
function createPetWindow() {
  petWindow = new BrowserWindow({
    width: 400,
    height: 500,
    frame: false,
    alwaysOnTop: true,
    transparent: true,
    backgroundColor: "#00000000",
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  petWindow.setIgnoreMouseEvents(true, { forward: true });
  if (isDev) {
    petWindow.loadURL("http://localhost:3000/#/pet");
  } else {
    petWindow.loadFile(path.join(__dirname, "../dist/index.html"), { hash: "/pet" });
  }
  petWindow.on("closed", () => {
    petWindow = null;
  });
  return petWindow;
}
function registerIpcHandlers() {
  ipcMain.handle("store:load", (_event, name) => {
    return loadStore(name);
  });
  ipcMain.handle("store:save", (_event, name, data) => {
    saveStore(name, data);
  });
  ipcMain.handle("window:open-pet", () => {
    if (!petWindow || petWindow.isDestroyed()) {
      createPetWindow();
    } else {
      petWindow.show();
    }
  });
  ipcMain.handle("window:close-pet", () => {
    if (petWindow && !petWindow.isDestroyed()) {
      petWindow.close();
    }
  });
  ipcMain.handle("window:toggle-pet", () => {
    if (!petWindow || petWindow.isDestroyed()) {
      createPetWindow();
    } else if (petWindow.isVisible()) {
      petWindow.hide();
    } else {
      petWindow.show();
    }
  });
  ipcMain.handle("window:move", (_event, dx, dy) => {
    if (petWindow && !petWindow.isDestroyed()) {
      const [currentX, currentY] = petWindow.getPosition();
      petWindow.setPosition(currentX + dx, currentY + dy);
    }
  });
  ipcMain.handle("window:set-ignore-mouse-events", (_event, ignore) => {
    if (petWindow && !petWindow.isDestroyed()) {
      petWindow.setIgnoreMouseEvents(ignore, { forward: true });
    }
  });
  ipcMain.handle("config:get-backend-url", () => {
    return getConfig("backendUrl");
  });
  ipcMain.handle("config:set-backend-url", (_event, url) => {
    setConfig("backendUrl", url);
  });
}
async function configureCors() {
  await session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    callback({ requestHeaders: details.requestHeaders });
  });
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    const responseHeaders = details.responseHeaders ?? {};
    responseHeaders["Access-Control-Allow-Origin"] = ["*"];
    responseHeaders["Access-Control-Allow-Methods"] = ["GET, POST, PUT, DELETE, OPTIONS"];
    responseHeaders["Access-Control-Allow-Headers"] = ["Content-Type, Authorization"];
    responseHeaders["Access-Control-Allow-Credentials"] = ["true"];
    callback({ responseHeaders });
  });
}
app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  registerIpcHandlers();
  await configureCors();
  createMainWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    } else if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.show();
    }
  });
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
