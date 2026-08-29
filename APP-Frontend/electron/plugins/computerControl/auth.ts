/**
 * SubTask 2.3 认证与防重放。
 *
 * - 注册令牌校验：Authorization: Bearer <token> 与持久化令牌以恒定时间比较
 *   （sha256 摘要后 timingSafeEqual），避免时序侧信道。
 * - 防重放：request_id 在当前时间窗内重复即拒绝；按首次出现时间记账，超窗自动
 *   淘汰，条目数达上限时先修剪再插入，防止无界内存增长。
 *
 * 不依赖 electron，可纯 node 单测。
 */
import { createHash, timingSafeEqual } from 'node:crypto';
import type { ErrorCode } from './errors';

export interface AuthenticatorConfig {
  /** 持久化注册令牌（明文仅存在于主进程侧，用于比对） */
  token: string;
  /** 防重放时间窗（毫秒），默认 120000 */
  replayWindowMs?: number;
  /** 防重放记账上限，默认 10000 */
  maxReplayEntries?: number;
  /** 可注入时钟便于测试 */
  clock?: () => number;
}

export type AuthDecision =
  | { ok: true }
  | { ok: false; code: ErrorCode };

export class Authenticator {
  private readonly windowMs: number;
  private readonly maxEntries: number;
  private readonly clock: () => number;
  /** request_id -> 首次出现时间戳 */
  private readonly seen = new Map<string, number>();

  constructor(private readonly config: AuthenticatorConfig) {
    this.windowMs = config.replayWindowMs ?? 120_000;
    this.maxEntries = config.maxReplayEntries ?? 10_000;
    this.clock = config.clock ?? Date.now;
  }

  private tokenMatches(provided: string | undefined): boolean {
    if (!provided || !this.config.token) return false;
    const expected = createHash('sha256').update(this.config.token).digest();
    const actual = createHash('sha256').update(provided).digest();
    return timingSafeEqual(expected, actual);
  }

  /** 校验 Bearer 令牌。失败返回 UNAUTHORIZED。 */
  verifyAuth(providedToken: string | undefined): AuthDecision {
    if (!this.tokenMatches(providedToken)) {
      return { ok: false, code: 'UNAUTHORIZED' };
    }
    return { ok: true };
  }

  /**
   * 校验 request_id 是否在当前时间窗内重复，并记账。
   * - 非字符串/空/超长 → INVALID_ARGUMENT
   * - 窗内重复 → REPLAY_DETECTED
   * - 其余 → ok:true
   */
  verifyReplay(requestId: unknown): AuthDecision {
    if (typeof requestId !== 'string' || requestId.length === 0 || requestId.length > 128) {
      return { ok: false, code: 'INVALID_ARGUMENT' };
    }
    const now = this.clock();
    if (this.seen.size >= this.maxEntries) {
      this.prune(now);
    }
    const firstSeen = this.seen.get(requestId);
    if (firstSeen !== undefined) {
      if (now - firstSeen < this.windowMs) {
        return { ok: false, code: 'REPLAY_DETECTED' };
      }
      // 超窗条目视为过期，复用槽位
      this.seen.set(requestId, now);
      return { ok: true };
    }
    // 满窗高频退化策略：prune 后仍满额（记账被窗口内高频请求占满且无过期可删），
    // 强制驱逐 Map 迭代顺序中最旧的条目再插入，保证记账容量有界、不无界增长。
    // 不会误伤本请求的重放判定：已在窗内的 request_id 在上方分支提前返回。
    if (this.seen.size >= this.maxEntries) {
      const oldest = this.seen.keys().next().value;
      if (oldest !== undefined) this.seen.delete(oldest);
    }
    this.seen.set(requestId, now);
    return { ok: true };
  }

  private prune(now: number): void {
    for (const [id, ts] of this.seen) {
      if (now - ts >= this.windowMs) {
        this.seen.delete(id);
      }
    }
  }
}
