export {};

declare global {
  interface Window {
    /** 由 electron/preload.ts 通过 contextBridge 暴露；浏览器模式下为 undefined */
    electronAPI?: {
      // 持久化存储
      storeLoad: (name: string) => Promise<string | null>;
      storeSave: (name: string, data: string) => Promise<void>;
      // 窗口控制
      openManagementWindow: () => Promise<void>;
      toggleDanmakuWindow: () => Promise<void>;
      // 桌宠多开：按 agentId 打开/关闭对应桌宠窗
      openPet: (agentId: string) => Promise<void>;
      closePet: (agentId: string) => Promise<void>;
      // 桌宠多开：查询当前实际已开启的桌宠窗 agentId 列表（主进程权威来源；可选，
      //      管理页挂载时用于对齐开启状态，非 Electron/旧版桥缺失时跳过）
      listPetWindows?: () => Promise<string[]>;
      setDanmakuVisible: (visible: boolean) => Promise<void>;
      onDanmakuVisibility: (callback: (visible: boolean) => void) => () => void;
      moveWindow: (dx: number, dy: number) => Promise<void>;
      setIgnoreMouseEvents: (ignore: boolean) => Promise<void>;
      setAlwaysOnTop: (flag: boolean) => Promise<void>;
      setWindowSize: (width: number, height: number) => Promise<void>;
      // 在系统默认浏览器打开外部 URL（OBS 源预览等）
      openExternal: (url: string) => Promise<void>;
      // 后端地址配置
      getBackendUrl: () => Promise<string | null>;
      setBackendUrl: (url: string) => Promise<void>;
      // 前端启动配置（Task 5）：自启动 / 管理员权限启动
      getStartupSettings: () => Promise<{
        supported: boolean;
        autoStart: boolean;
        runAsAdmin: boolean;
        isAdmin: boolean;
      }>;
      setAutoStart: (enabled: boolean) => Promise<{
        supported: boolean;
        autoStart: boolean;
        runAsAdmin: boolean;
        isAdmin: boolean;
      }>;
      setRunAsAdmin: (enabled: boolean) => Promise<{
        supported: boolean;
        autoStart: boolean;
        runAsAdmin: boolean;
        isAdmin: boolean;
      }>;
      // 电脑控制插件：授权状态读写与运行信息
      getComputerControlAuth: () => Promise<boolean>;
      setComputerControlAuth: (value: boolean) => Promise<boolean>;
      getComputerControlInfo: () => Promise<{
        running: boolean;
        port: number | null;
        fingerprint: string | null;
        authorized: boolean;
      }>;
      // P2-T2 relay 推送：渲染层经主进程执行电脑控制工具（本机动作由主进程校验授权后执行）。
      // 可选字段：浏览器模式或旧 preload 产物可能未暴露；cxfcRelay 执行器据此回退为不可执行错误。
      callComputerControlTool?: (
        tool: string,
        args: Record<string, unknown>,
      ) => Promise<{
        ok: boolean;
        code?: string;
        error?: string;
        output?: unknown;
      }>;
      // VRM 模型：选择/读取本地模型文件（桌面模式模型选择，默认模型打包在包内）
      pickModelFile: () => Promise<{ canceled: boolean; path?: string }>;
      readModelFile: (path: string) => Promise<ArrayBuffer | null>;
    };
    /** 由 electron/preload.ts 通过 contextBridge 暴露的 Neko 插件运行时桥；浏览器模式下为 undefined */
    neko?: {
      getStatus: () => Promise<{
        running: boolean;
        port: number | null;
        config: NekoRuntimeConfig;
      }>;
      start: () => Promise<{ ok: boolean; port?: number; error?: string }>;
      stop: () => Promise<{ ok: boolean; error?: string }>;
      restart: () => Promise<{ ok: boolean; port?: number; error?: string }>;
      getConfig: () => Promise<NekoRuntimeConfig>;
      setConfig: (partial: Partial<NekoRuntimeConfig>) => Promise<NekoRuntimeConfig>;
      http: (req: {
        method?: string;
        path: string;
        query?: Record<string, string | number | boolean>;
        body?: unknown;
      }) => Promise<{ ok: boolean; status?: number; body?: string; error?: string }>;
      onLog: (callback: (line: string) => void) => () => void;
      getBridgeStatus: () => Promise<{
        registrarRunning: boolean;
        bridgeRunning: boolean;
        bridgePort: number | null;
        tools: number;
        cxfcRegistered: boolean;
      }>;
    };
    /** 由 electron/preload.ts 通过 contextBridge 暴露的手环心率 BLE 采集桥；浏览器模式下为 undefined */
    ble?: {
      scan: () => Promise<{
        ok: boolean;
        status: BleStatus;
        devices: BleDeviceInfo[];
        error?: string;
      }>;
      connect: (deviceId: string) => Promise<{ ok: boolean; status: BleStatus; error?: string }>;
      disconnect: () => Promise<{ ok: boolean; status: BleStatus; error?: string }>;
      getStatus: () => Promise<{
        status: BleStatus;
        fingerprint: string | null;
        deviceName: string | null;
      }>;
      /** 订阅主进程 ble:notify 推送（hr/status/error）；返回取消订阅函数 */
      onNotify: (callback: (payload: BleNotifyPayload) => void) => () => void;
      /** 仅订阅状态变化；返回取消订阅函数 */
      onStatus: (callback: (status: BleStatus, detail?: string) => void) => () => void;
    };
  }

  /** 手环心率采集器状态（对齐 electron/ble/ble_collector.ts BleStatus） */
  type BleStatus =
    | 'idle'
    | 'unavailable'
    | 'scanning'
    | 'unsupported'
    | 'connecting'
    | 'connected'
    | 'reconnecting'
    | 'disconnected';

  /** 扫描结果设备（对齐 electron/ble/ble_collector.ts BleDeviceInfo） */
  interface BleDeviceInfo {
    deviceId: string;
    name: string;
    address: string;
    fingerprint: string;
    rssi: number | null;
    serviceUuids: string[];
    hasHeartRate: boolean;
  }

  /** ble:notify 推送载荷（对齐 electron/preload.ts BleNotifyPayload） */
  type BleNotifyPayload =
    | { type: 'hr'; bpm: number; ts: number }
    | { type: 'status'; status: BleStatus; detail?: string }
    | { type: 'error'; context?: string; message: string };

  interface NekoRuntimeConfig {
    python: string;
    sourceDir: string;
    port: number;
    autoStart: boolean;
  }
}
