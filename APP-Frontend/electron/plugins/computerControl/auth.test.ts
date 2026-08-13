// @vitest-environment node
/**
 * SubTask 2.3 认证与防重放单测。
 */
import { describe, it, expect } from 'vitest';
import { Authenticator } from './auth';

describe('Authenticator.verifyAuth', () => {
  const auth = new Authenticator({ token: 'secret-token' });

  it('正确令牌通过', () => {
    expect(auth.verifyAuth('secret-token')).toEqual({ ok: true });
  });

  it('错误令牌 → UNAUTHORIZED', () => {
    const r = auth.verifyAuth('wrong');
    if (r.ok) throw new Error('expected auth failure');
    expect(r.code).toBe('UNAUTHORIZED');
  });

  it('缺失令牌 → UNAUTHORIZED', () => {
    const r = auth.verifyAuth(undefined);
    if (r.ok) throw new Error('expected auth failure');
    expect(r.code).toBe('UNAUTHORIZED');
  });

  it('空令牌配置时任何输入都不通过', () => {
    const a = new Authenticator({ token: '' });
    const r = a.verifyAuth('anything');
    if (r.ok) throw new Error('expected auth failure');
    expect(r.code).toBe('UNAUTHORIZED');
  });
});

describe('Authenticator.verifyReplay', () => {
  it('首次 request_id 通过并记账', () => {
    const auth = new Authenticator({ token: 't', replayWindowMs: 1000, clock: () => 0 });
    expect(auth.verifyReplay('id-1')).toEqual({ ok: true });
  });

  it('窗内重复 request_id → REPLAY_DETECTED', () => {
    let now = 0;
    const auth = new Authenticator({ token: 't', replayWindowMs: 1000, clock: () => now });
    expect(auth.verifyReplay('dup')).toEqual({ ok: true });
    now = 500;
    const r = auth.verifyReplay('dup');
    if (r.ok) throw new Error('expected replay failure');
    expect(r.code).toBe('REPLAY_DETECTED');
  });

  it('超窗后同一 request_id 复用放行', () => {
    let now = 0;
    const auth = new Authenticator({ token: 't', replayWindowMs: 1000, clock: () => now });
    expect(auth.verifyReplay('old').ok).toBe(true);
    now = 2000;
    expect(auth.verifyReplay('old').ok).toBe(true);
  });

  it('缺失/非字符串/超长 request_id → INVALID_ARGUMENT', () => {
    const auth = new Authenticator({ token: 't' });
    const cases = [undefined, 123, '', 'x'.repeat(129)];
    for (const c of cases) {
      const r = auth.verifyReplay(c);
      if (r.ok) throw new Error('expected invalid argument');
      expect(r.code).toBe('INVALID_ARGUMENT');
    }
  });

  it('不同 request_id 互不影响', () => {
    const auth = new Authenticator({ token: 't', clock: () => 0 });
    expect(auth.verifyReplay('a').ok).toBe(true);
    expect(auth.verifyReplay('b').ok).toBe(true);
  });
});
