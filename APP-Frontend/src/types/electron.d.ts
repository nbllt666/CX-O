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
      // 后端地址配置
      getBackendUrl: () => Promise<string | null>;
      setBackendUrl: (url: string) => Promise<void>;
    };
  }
}
