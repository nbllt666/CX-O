/**
 * 预加载脚本（CJS 产物 preload.cjs，sandbox 兼容）
 * 通过 contextBridge 暴露类型安全的 electronAPI；渲染层类型声明见 src/types/electron.d.ts
 */
import { contextBridge, ipcRenderer } from 'electron';
import type { BleStatus } from './ble/ble_collector';

/** ble:notify 推送载荷（主进程 → 渲染层实时 HR/状态/错误） */
export type BleNotifyPayload =
  | { type: 'hr'; bpm: number; ts: number }
  | { type: 'status'; status: BleStatus; detail?: string }
  | { type: 'error'; context?: string; message: string };

contextBridge.exposeInMainWorld('electronAPI', {
  // 持久化存储
  storeLoad: (name: string) => ipcRenderer.invoke('store:load', name),
  storeSave: (name: string, data: string) => ipcRenderer.invoke('store:save', name, data),

  // 窗口控制
  openManagementWindow: () => ipcRenderer.invoke('window:open-management'),
  toggleDanmakuWindow: () => ipcRenderer.invoke('window:toggle-danmaku'),
  // 桌宠多开：按 agentId 打开/关闭对应桌宠窗
  openPet: (agentId: string) => ipcRenderer.invoke('window:open-pet', agentId),
  closePet: (agentId: string) => ipcRenderer.invoke('window:close-pet', agentId),
  setDanmakuVisible: (visible: boolean) =>
    ipcRenderer.invoke('window:set-danmaku-visible', visible),
  /** 在系统默认浏览器打开外部 URL（OBS 源预览等） */
  openExternal: (url: string) => ipcRenderer.invoke('shell:open-external', url),
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
  // P2-T2 relay 推送：渲染层经主进程执行电脑控制工具（本机动作由主进程校验授权后执行）
  callComputerControlTool: (tool: string, args: Record<string, unknown>) =>
    ipcRenderer.invoke('computerControl:call-tool', tool, args),

  // VRM 模型：选择/读取本地模型文件（默认模型打包在包内，用户可选本地 .vrm 覆盖）
  pickModelFile: () => ipcRenderer.invoke('model:pick-file'),
  readModelFile: (path: string) => ipcRenderer.invoke('model:read-file', path),
});

contextBridge.exposeInMainWorld('neko', {
  // Neko 插件运行时 sidecar 生命周期
  getStatus: () => ipcRenderer.invoke('neko:get-status'),
  start: () => ipcRenderer.invoke('neko:start'),
  stop: () => ipcRenderer.invoke('neko:stop'),
  restart: () => ipcRenderer.invoke('neko:restart'),
  getConfig: () => ipcRenderer.invoke('neko:get-config'),
  setConfig: (partial: Record<string, unknown>) => ipcRenderer.invoke('neko:set-config', partial),
  /** 经主进程 net.fetch 代理直连插件服务器（规避 file:// 下 CORS / Host 守卫） */
  http: (req: { method?: string; path: string; query?: Record<string, string | number | boolean>; body?: unknown }) =>
    ipcRenderer.invoke('neko:http', req),
  /** 订阅 sidecar stdout/stderr；返回取消订阅函数 */
  onLog: (callback: (line: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, line: string) => callback(line);
    ipcRenderer.on('neko:stdout', listener);
    return () => ipcRenderer.removeListener('neko:stdout', listener);
  },
  /** 工具→CXFC 桥状态（仅供管理页展示） */
  getBridgeStatus: () => ipcRenderer.invoke('neko:get-bridge-status'),
});

contextBridge.exposeInMainWorld('ble', {
  // 手环心率 BLE 采集（Task 5 / spec：前端 Electron BLE 采集）
  scan: () => ipcRenderer.invoke('ble:scan'),
  connect: (deviceId: string) => ipcRenderer.invoke('ble:connect', deviceId),
  disconnect: () => ipcRenderer.invoke('ble:disconnect'),
  getStatus: () => ipcRenderer.invoke('ble:status'),
  /** 订阅主进程 ble:notify 推送（hr/status/error）；返回取消订阅函数 */
  onNotify: (callback: (payload: BleNotifyPayload) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: BleNotifyPayload) =>
      callback(payload);
    ipcRenderer.on('ble:notify', listener);
    return () => ipcRenderer.removeListener('ble:notify', listener);
  },
  /** 仅订阅状态变化（从 ble:notify 过滤 type=status）；返回取消订阅函数 */
  onStatus: (callback: (status: BleStatus, detail?: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: BleNotifyPayload) => {
      if (payload?.type === 'status') {
        callback(payload.status, payload.detail);
      }
    };
    ipcRenderer.on('ble:notify', listener);
    return () => ipcRenderer.removeListener('ble:notify', listener);
  },
});
