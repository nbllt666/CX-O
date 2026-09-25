/**
 * 主进程 ↔ 预加载 ↔ 渲染层共享的 IPC 契约（不含 electron 依赖，可单测/复用）。
 */
export const IPC = {
  getInfo: "modelstation:get-info",
  getConfig: "modelstation:get-config",
  setConfig: "modelstation:set-config",
  checkBackend: "modelstation:check-backend",
  restartBackend: "modelstation:restart-backend",
  stopBackend: "modelstation:stop-backend",
} as const;

/** 渲染层只读环境信息 */
export interface DesktopInfo {
  isDesktop: true;
  /** 后端连接地址（可被面板修改） */
  backendBaseUrl: string;
  /** 渲染层实际加载地址（本地静态站点或 vite dev） */
  frontendUrl: string;
  /** 本地静态站点实际端口；vite dev 形态为 0 */
  frontendPort: number;
  /** 数据根（可写） */
  dataRoot: string;
  /** packaged=安装态，dev=仓库开发态 */
  layoutMode: "packaged" | "dev";
  /** 配置文件绝对路径 */
  configFilePath: string;
}

export interface BackendStatus {
  healthy: boolean;
  baseUrl: string;
  checkedAt: number;
  detail?: string;
}

export interface BackendActionResult {
  ok: boolean;
  message: string;
  status?: BackendStatus;
}

export interface DesktopBridge {
  isDesktop: true;
  getInfo(): Promise<DesktopInfo>;
  getConfig(): Promise<unknown>;
  setConfig(patch: Record<string, unknown>): Promise<unknown>;
  checkBackend(baseUrl?: string): Promise<BackendStatus>;
  restartBackend(): Promise<BackendActionResult>;
  stopBackend(): Promise<BackendActionResult>;
}