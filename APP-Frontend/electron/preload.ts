/**
 * 预加载脚本（CJS 产物 preload.cjs，sandbox 兼容）
 * 通过 contextBridge 暴露类型安全的 electronAPI；渲染层类型声明见 src/types/electron.d.ts
 */
import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  // 持久化存储
  storeLoad: (name: string) => ipcRenderer.invoke('store:load', name),
  storeSave: (name: string, data: string) => ipcRenderer.invoke('store:save', name, data),

  // 窗口控制
  openManagementWindow: () => ipcRenderer.invoke('window:open-management'),
  toggleDanmakuWindow: () => ipcRenderer.invoke('window:toggle-danmaku'),
  closePet: () => ipcRenderer.invoke('window:close-pet'),
  setDanmakuVisible: (visible: boolean) =>
    ipcRenderer.invoke('window:set-danmaku-visible', visible),
  /** 订阅弹幕窗显隐变化（托盘/快捷键触发时主进程回播）；返回取消订阅函数 */
  onDanmakuVisibility: (callback: (visible: boolean) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, visible: boolean) => callback(visible);
    ipcRenderer.on('danmaku:visibility-changed', listener);
    return () => ipcRenderer.removeListener('danmaku:visibility-changed', listener);
  },
  moveWindow: (dx: number, dy: number) => ipcRenderer.invoke('window:move', dx, dy),
  setIgnoreMouseEvents: (ignore: boolean) =>
    ipcRenderer.invoke('window:set-ignore-mouse-events', ignore),
  setAlwaysOnTop: (flag: boolean) => ipcRenderer.invoke('window:set-always-on-top', flag),
  /** 桌宠窗采集尺寸预设（SubTask 9.3）：调整调用方窗口尺寸 */
  setWindowSize: (width: number, height: number) =>
    ipcRenderer.invoke('window:set-size', width, height),

  // 后端地址配置
  getBackendUrl: () => ipcRenderer.invoke('config:get-backend-url'),
  setBackendUrl: (url: string) => ipcRenderer.invoke('config:set-backend-url', url),

  // 前端启动配置（Task 5）：自启动 / 管理员权限启动
  getStartupSettings: () => ipcRenderer.invoke('startup:get-settings'),
  setAutoStart: (enabled: boolean) => ipcRenderer.invoke('startup:set-auto-start', enabled),
  setRunAsAdmin: (enabled: boolean) => ipcRenderer.invoke('startup:set-run-as-admin', enabled),

  // 电脑控制插件：授权状态读写与运行信息（渲染层仅能读/写授权开关，本机控制经主进程）
  getComputerControlAuth: () => ipcRenderer.invoke('computerControl:get-auth'),
  setComputerControlAuth: (value: boolean) =>
    ipcRenderer.invoke('computerControl:set-auth', value),
  getComputerControlInfo: () => ipcRenderer.invoke('computerControl:get-info'),
});
