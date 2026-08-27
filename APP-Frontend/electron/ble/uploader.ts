/**
 * 生理信号 REST 上送器（主进程后台任务）
 * ============================================================================
 * 职责：
 *  1. HR 样本上送 `POST {backendUrl}/api/physio/hr`，按 ≤1Hz 节流（默认 1000ms）。
 *     后端离线/失败时丢弃当前样本，不缓冲不积压（spec：丢弃不积压）。
 *  2. 系统静默上送 `POST {backendUrl}/api/physio/state`，由调用方周期触发
 *     （startIdleReport，默认 ≥30s），载荷 {system_idle_sec, user_active}。
 *
 * 可测试性：fetchImpl 注入（对齐 cxfc/client.ts 模式），不依赖 electron。
 * 后端离线不抛异常，仅记日志——绝不影响 Electron 主流程。
 * ============================================================================
 */

export interface HrSample {
  bpm: number;
  /** epoch 秒（后端 _parse_ts 兼容毫秒/秒；前端统一上送秒消除歧义） */
  ts: number;
  device_fingerprint: string;
}

export interface SystemStateSample {
  system_idle_sec: number;
  user_active: boolean;
}

export interface PhysioUploaderOptions {
  backendUrl: string;
  /**
   * 运行时后端地址解析器（可选）：每轮上送前调用以跟随最新配置
   * （设置页修改后端地址后无需重启）。返回空值时回落构造期 backendUrl 快照。
   * 已知限制：config.json 改动在下一轮 tick 才生效（HR ≤1s / 静默 ≥30s 周期）。
   */
  backendUrlResolver?: () => string | null;
  /** HR 节流窗口（毫秒），默认 1000（≤1Hz） */
  hrThrottleMs?: number;
  /** 系统静默上送周期（毫秒），默认 30000（≥30s） */
  idleIntervalMs?: number;
  fetchImpl?: typeof fetch;
  logger?: (line: string) => void;
}

/** 单请求超时（毫秒）：防止后端挂起拖住后台任务/退出链。 */
const REQUEST_TIMEOUT_MS = 5_000;

export class PhysioUploader {
  private readonly backendUrl: string;
  private readonly backendUrlResolver: (() => string | null) | null;
  private readonly hrThrottleMs: number;
  private readonly idleIntervalMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly logger: (line: string) => void;

  private stopped = false;
  private lastHrSentAt = 0;
  private idleTimer: ReturnType<typeof setInterval> | null = null;

  constructor(options: PhysioUploaderOptions) {
    this.backendUrl = options.backendUrl.replace(/\/+$/, '');
    this.backendUrlResolver = options.backendUrlResolver ?? null;
    this.hrThrottleMs = options.hrThrottleMs ?? 1000;
    this.idleIntervalMs = options.idleIntervalMs ?? 30000;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.logger = options.logger ?? (() => undefined);
  }

  /** 当前生效后端基址：优先每轮解析的最新值，空值回落构造期快照 */
  private baseUrl(): string {
    const resolved = this.backendUrlResolver?.() ?? '';
    if (resolved) return resolved.replace(/\/+$/, '');
    return this.backendUrl;
  }

  /**
   * HR 上送（≤1Hz 节流）。返回本次是否实际发起上送；
   * 节流窗口内的样本直接丢弃；后端离线时丢弃当前样本不积压。
   */
  async reportHr(sample: HrSample): Promise<boolean> {
    if (this.stopped) return false;
    const now = Date.now();
    if (now - this.lastHrSentAt < this.hrThrottleMs) {
      return false; // 节流丢弃
    }
    this.lastHrSentAt = now;
    try {
      // M-G 修复：HR 上送同样走每轮解析的 baseUrl()（对齐 reportState），
      // 避免沿用构造期 backendUrl 快照——设置页换址后仍发旧地址。
      const resp = await this.fetchImpl(`${this.baseUrl()}/api/physio/hr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sample),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (!resp.ok) {
        this.logger(`[physio] HR 上送失败 HTTP ${resp.status}，丢弃当前样本`);
        return false;
      }
      return true;
    } catch (err) {
      this.logger(`[physio] HR 上送异常（后端离线，丢弃不积压）: ${String(err)}`);
      return false;
    }
  }

  /** 系统静默上送。返回是否上送成功；后端离线时丢弃不抛异常。 */
  async reportState(sample: SystemStateSample): Promise<boolean> {
    if (this.stopped) return false;
    try {
      const resp = await this.fetchImpl(`${this.baseUrl()}/api/physio/state`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sample),
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (!resp.ok) {
        this.logger(`[physio] 系统状态上送失败 HTTP ${resp.status}`);
        return false;
      }
      return true;
    } catch (err) {
      this.logger(`[physio] 系统状态上送异常（后端离线，丢弃）: ${String(err)}`);
      return false;
    }
  }

  /**
   * 启动系统静默周期上送（≥30s）。sampleProvider 由调用方注入
   * （main.ts 用 electron powerMonitor.getSystemIdleTime() 构造载荷）。
   * 首次立即上送一次，随后按 idleIntervalMs 周期。
   */
  startIdleReport(sampleProvider: () => SystemStateSample): void {
    if (this.stopped || this.idleTimer) return;
    const run = (): void => {
      try {
        void this.reportState(sampleProvider());
      } catch (err) {
        this.logger(`[physio] 构造系统状态样本失败: ${String(err)}`);
      }
    };
    run();
    this.idleTimer = setInterval(run, this.idleIntervalMs);
  }

  /** 停止周期上送（应用退出时调用）。 */
  stop(): void {
    this.stopped = true;
    if (this.idleTimer) {
      clearInterval(this.idleTimer);
      this.idleTimer = null;
    }
  }
}
