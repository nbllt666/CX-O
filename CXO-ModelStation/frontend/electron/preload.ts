/**
 * 预加载脚本：contextIsolation 下的最小桥（只读信息 + 受控动作）。
 *
 * 渲染层只能通过 window.modelstationDesktop 访问主进程能力，
 * 不暴露 ipcRenderer 本体，也不开启 nodeIntegration。
 */
import { contextBridge, ipcRenderer } from "electron";

import { IPC, type BackendActionResult, type BackendStatus, type DesktopBridge, type DesktopInfo } from "./ipc";

const bridge: DesktopBridge = {
  isDesktop: true,
  getInfo: () => ipcRenderer.invoke(IPC.getInfo) as Promise<DesktopInfo>,
  getConfig: () => ipcRenderer.invoke(IPC.getConfig) as Promise<unknown>,
  setConfig: (patch) => ipcRenderer.invoke(IPC.setConfig, patch) as Promise<unknown>,
  checkBackend: (baseUrl) => ipcRenderer.invoke(IPC.checkBackend, baseUrl) as Promise<BackendStatus>,
  restartBackend: () => ipcRenderer.invoke(IPC.restartBackend) as Promise<BackendActionResult>,
  stopBackend: () => ipcRenderer.invoke(IPC.stopBackend) as Promise<BackendActionResult>,
};

contextBridge.exposeInMainWorld("modelstationDesktop", bridge);