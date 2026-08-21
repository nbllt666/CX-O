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
      closePet: () => Promise<void>;
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
      // VRM 模型：选择/读取本地模型文件（桌面模式模型选择，默认模型打包在包内）
      pickModelFile: () => Promise<{ canceled: boolean; path?: string }>;
      readModelFile: (path: string) => Promise<ArrayBuffer | null>;
    };
  }
}
