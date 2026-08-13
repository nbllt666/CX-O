/**
 * SubTask 3.1 Electron CXFC 客户端。
 *
 * 将本地已启动的电脑控制插件注册到 CX-O-SERVER 后端（/cxfc/register），并按
 * 契约周期发送心跳（/cxfc/heartbeat）；后端不可用/断线时指数退避自动重连；
 * 应用退出时注销（DELETE /cxfc/plugins/{pluginId}）。
 *
 * 注册载荷从插件运行信息构建：host/port/name/version/tools/skills +
 * tls_cert_fingerprint + token（令牌由插件侧持久化，见 Task2
 * computerControl/index.ts loadOrCreatePluginConfig）。
 *
 * 不依赖 electron：通过依赖注入 readPluginInfo 与 fetchImpl，可在纯 node 环境
 * 单测（见 client.test.ts）。
 */
import { randomBytes } from 'node:crypto';

/** 插件运行信息（由调用方从电脑控制插件对象读取/构造）。 */
export interface PluginRuntimeInfo {
  host: string;
  port: number;
  name: string;
  version: string;
  capabilities: string[];
  tools: unknown[];
  skills: unknown[];
  /** 注册令牌（插件侧持久化生成） */
  token: string;
  /** TLS 自签名证书指纹（SHA-256 十六进制冒号分隔，插件 /health 暴露） */
  tls_cert_fingerprint: string;
  /** TLS 自签名证书 PEM 原文（B-1：后端据此做 TOFU 首次信任并以 https 访问） */
  tls_cert_pem: string;
}

export interface CxfcClientOptions {
  /** 后端基址，如 http://127.0.0.1:8000 */
  backendUrl: string;
  /** 读取插件运行信息的函数（每次注册/心跳前调用，可异步）。 */
  readPluginInfo: () => PluginRuntimeInfo | Promise<PluginRuntimeInfo>;
  /** 心跳周期（毫秒），默认 10000 */
  heartbeatIntervalMs?: number;
  /** 指数退避初始延迟（毫秒），默认 1000 */
  retryBaseDelayMs?: number;
  /** 指数退避上限（毫秒），默认 30000 */
  maxRetryDelayMs?: number;
  /** 可注入 fetch（默认全局 fetch） */
  fetchImpl?: typeof fetch;
  logger?: (line: string) => void;
}

interface RegisterResponse {
  status?: string;
  plugin_id?: string;
}

const DEFAULT_HEARTBEAT_MS = 10_000;
const DEFAULT_RETRY_BASE_MS = 1_000;
const DEFAULT_MAX_RETRY_MS = 30_000;

/** 生成随机的 request_id（对齐防重放契约，128 字符以内）。 */
export function makeRequestId(): string {
  return randomBytes(16).toString('hex');
}

export class CxfcClient {
  private readonly backendUrl: string;
  private readonly readPluginInfo: () => PluginRuntimeInfo | Promise<PluginRuntimeInfo>;
  private readonly heartbeatIntervalMs: number;
  private readonly retryBaseDelayMs: number;
  private readonly maxRetryDelayMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly logger: (line: string) => void;

  private stopped = false;
  private registered = false;
  private pluginId: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private retryDelayMs = 0;

  constructor(options: CxfcClientOptions) {
    this.backendUrl = options.backendUrl.replace(/\/+$/, '');
    this.readPluginInfo = options.readPluginInfo;
    this.heartbeatIntervalMs = options.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_MS;
    this.retryBaseDelayMs = options.retryBaseDelayMs ?? DEFAULT_RETRY_BASE_MS;
    this.maxRetryDelayMs = options.maxRetryDelayMs ?? DEFAULT_MAX_RETRY_MS;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.logger = options.logger ?? (() => undefined);
  }

  /**
   * 启动注册/心跳循环。首次注册成功前以退避间隔重试（后端不可用自动重连），
   * 注册成功后按心跳周期维持。
   */
  start(): void {
    if (this.stopped) return;
    void this.runOnce();
  }

  /** 停止循环并注销（应用退出时调用；注销为尽力而为，失败不阻断退出）。 */
  async stop(): Promise<void> {
    if (this.stopped) return;
    this.stopped = true;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    try {
      if (this.registered && this.pluginId) {
        await this.unregister(this.pluginId);
        this.registered = false;
      }
    } catch (err) {
      this.logger(`[cxfc] 注销失败（忽略）: ${String(err)}`);
    }
  }

  isRegistered(): boolean {
    return this.registered;
  }

  getPluginId(): string | null {
    return this.pluginId;
  }

  // -------------------------------------------------------------------------
  // 内部循环
  // -------------------------------------------------------------------------
  private async runOnce(): Promise<void> {
    if (this.stopped) return;
    let ok = false;
    try {
      if (!this.registered) {
        ok = await this.registerOnce();
      } else {
        ok = await this.heartbeatOnce();
      }
    } catch (err) {
      this.logger(`[cxfc] 循环异常: ${String(err)}`);
      ok = false;
    }

    if (this.stopped) return;

    if (ok) {
      this.retryDelayMs = 0;
      this.schedule(this.heartbeatIntervalMs);
    } else {
      this.retryDelayMs =
        this.retryDelayMs === 0
          ? this.retryBaseDelayMs
          : Math.min(this.retryDelayMs * 2, this.maxRetryDelayMs);
      this.logger(`[cxfc] 后端不可用/失败，${this.retryDelayMs}ms 后重试`);
      this.schedule(this.retryDelayMs);
    }
  }

  private schedule(delayMs: number): void {
    if (this.stopped) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.runOnce();
    }, delayMs);
  }

  private async registerOnce(): Promise<boolean> {
    const info = await this.readPluginInfo();
    const body = {
      host: info.host,
      port: info.port,
      name: info.name,
      version: info.version,
      capabilities: info.capabilities,
      tools: info.tools,
      skills: info.skills,
      token: info.token,
      tls_cert_fingerprint: info.tls_cert_fingerprint,
      // B-1：注册载荷携带自签名证书 PEM，供后端 TOFU 首次信任（证书固定）与 https 访问
      tls_cert_pem: info.tls_cert_pem,
    };
    const resp = await this.fetchImpl(`${this.backendUrl}/cxfc/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      this.logger(`[cxfc] 注册失败 HTTP ${resp.status}`);
      return false;
    }
    const data = (await resp.json()) as RegisterResponse;
    this.pluginId = data.plugin_id ?? `cxfc_${info.host}_${info.port}`;
    this.registered = true;
    this.logger(`[cxfc] 注册成功 plugin_id=${this.pluginId}`);
    return true;
  }

  private async heartbeatOnce(): Promise<boolean> {
    const info = await this.readPluginInfo();
    const resp = await this.fetchImpl(`${this.backendUrl}/cxfc/heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ plugin_id: this.pluginId, port: info.port }),
    });
    if (!resp.ok) {
      this.logger(`[cxfc] 心跳失败 HTTP ${resp.status}`);
      // 404 说明后端已遗忘本插件（如后端重启清空注册），重置为未注册以重新注册
      if (resp.status === 404) {
        this.registered = false;
      }
      return false;
    }
    return true;
  }

  private async unregister(pluginId: string): Promise<void> {
    await this.fetchImpl(`${this.backendUrl}/cxfc/plugins/${pluginId}`, { method: 'DELETE' });
  }
}

/** 便捷工厂：以默认心跳/退避参数创建客户端。 */
export function createCxfcClient(options: CxfcClientOptions): CxfcClient {
  return new CxfcClient(options);
}
