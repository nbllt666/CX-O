// @vitest-environment node
/**
 * Authenticator 单测（tests/auth.test.ts）
 * ============================================================================
 * 覆盖 src/shared/auth.ts（行为与源实现 APP-Frontend
 * electron/plugins/computerControl/auth.ts 完全一致）：
 *  - Bearer 令牌校验：正确 token 通过；错误/缺失 token 拒绝（UNAUTHORIZED）；
 *    空 token 配置一律拒绝；恒定时间比较（sha256 + timingSafeEqual）行为等价；
 *  - 防重放 request_id 语义：非字符串/空/超长 → INVALID_ARGUMENT；
 *    窗内重复 → REPLAY_DETECTED；超窗后重新记账 ok；记账容量有界（满额驱逐）。
 * 时间相关用例通过注入 clock 控制，不依赖真实时钟。
 * ============================================================================
 */
import { describe, expect, it } from 'vitest';
import { Authenticator } from '../src/shared/auth';

describe('verifyAuth（Bearer 令牌校验）', () => {
  it('正确 token 通过', () => {
    const auth = new Authenticator({ token: 'reg-token-abc' });
    expect(auth.verifyAuth('reg-token-abc')).toEqual({ ok: true });
  });

  it('错误 token 拒绝（UNAUTHORIZED）', () => {
    const auth = new Authenticator({ token: 'reg-token-abc' });
    expect(auth.verifyAuth('wrong-token')).toEqual({ ok: false, code: 'UNAUTHORIZED' });
  });

  it('缺失 token（undefined/空串）拒绝', () => {
    const auth = new Authenticator({ token: 'reg-token-abc' });
    expect(auth.verifyAuth(undefined)).toEqual({ ok: false, code: 'UNAUTHORIZED' });
    expect(auth.verifyAuth('')).toEqual({ ok: false, code: 'UNAUTHORIZED' });
  });

  it('配置 token 为空时任何输入一律拒绝（防止空令牌放行）', () => {
    const auth = new Authenticator({ token: '' });
    expect(auth.verifyAuth('').ok).toBe(false);
    expect(auth.verifyAuth('anything').ok).toBe(false);
  });

  it('恒定时间比较语义：sha256 摘要后 timingSafeEqual，不同长度 token 也不抛错', () => {
    const auth = new Authenticator({ token: 'a'.repeat(64) });
    // 提供串与配置串长度不同：sha256 后定长摘要，timingSafeEqual 可安全比较
    expect(auth.verifyAuth('short')).toEqual({ ok: false, code: 'UNAUTHORIZED' });
  });
});

describe('verifyReplay（request_id 防重放）', () => {
  it('非法 request_id（非字符串/空/超长）→ INVALID_ARGUMENT', () => {
    const auth = new Authenticator({ token: 't' });
    expect(auth.verifyReplay(123)).toEqual({ ok: false, code: 'INVALID_ARGUMENT' });
    expect(auth.verifyReplay(null)).toEqual({ ok: false, code: 'INVALID_ARGUMENT' });
    expect(auth.verifyReplay('')).toEqual({ ok: false, code: 'INVALID_ARGUMENT' });
    expect(auth.verifyReplay('x'.repeat(129))).toEqual({ ok: false, code: 'INVALID_ARGUMENT' });
    // 128 恰好为合法上限
    expect(auth.verifyReplay('x'.repeat(128))).toEqual({ ok: true });
  });

  it('首次出现记账 ok；窗内重复 REPLAY_DETECTED；超窗后重新记账 ok', () => {
    let now = 1000;
    const auth = new Authenticator({ token: 't', replayWindowMs: 1000, clock: () => now });
    expect(auth.verifyReplay('req-1')).toEqual({ ok: true });

    now = 1500; // now - firstSeen = 500 < 1000，仍在窗内
    expect(auth.verifyReplay('req-1')).toEqual({ ok: false, code: 'REPLAY_DETECTED' });

    now = 2000; // now - firstSeen = 1000 >= windowMs，超窗放行
    expect(auth.verifyReplay('req-1')).toEqual({ ok: true });

    // 超窗条目复用槽位重新记账（firstSeen 更新为 2000）：再次推入窗内即拒
    now = 2400;
    expect(auth.verifyReplay('req-1')).toEqual({ ok: false, code: 'REPLAY_DETECTED' });
  });

  it('不同 request_id 互不影响，可并发记账', () => {
    let now = 0;
    const auth = new Authenticator({ token: 't', clock: () => now });
    expect(auth.verifyReplay('req-a').ok).toBe(true);
    expect(auth.verifyReplay('req-b').ok).toBe(true);
    expect(auth.verifyReplay('req-c').ok).toBe(true);
    // 窗内各自重复均被拒
    expect(auth.verifyReplay('req-a')).toEqual({ ok: false, code: 'REPLAY_DETECTED' });
    expect(auth.verifyReplay('req-b')).toEqual({ ok: false, code: 'REPLAY_DETECTED' });
  });

  it('记账容量有界：满额且无过期时驱逐最旧条目再插入，不无界增长', () => {
    let now = 0;
    const auth = new Authenticator({ token: 't', maxReplayEntries: 2, clock: () => now });
    expect(auth.verifyReplay('a').ok).toBe(true);
    expect(auth.verifyReplay('b').ok).toBe(true);
    // 满额：a、b 均未过期（now-firstSeen=0 < window），prune 无效 → 强制驱逐最旧 a
    expect(auth.verifyReplay('c').ok).toBe(true);
    // a 已被驱逐：重新记账 ok（容量有界的直接证据）
    expect(auth.verifyReplay('a').ok).toBe(true);
    // c 仍在窗内：重复仍被拒（驱逐只针对最旧，不误伤窗内判定）
    expect(auth.verifyReplay('c')).toEqual({ ok: false, code: 'REPLAY_DETECTED' });
  });
});
