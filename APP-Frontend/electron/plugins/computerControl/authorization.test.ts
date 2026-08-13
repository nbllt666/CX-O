// @vitest-environment node
/**
 * SubTask 2.1 授权状态代理单测。
 * 断言读写/撤销的持久化语义，且不产生任何 OS 副作用（用内存替身注入）。
 */
import { describe, it, expect, vi } from 'vitest';
import { AuthorizationStore, type AuthorizationPersistence } from './authorization';

function memoryPersistence(initial: boolean | null = null): AuthorizationPersistence & { saved: (boolean | null)[] } {
  const saved: (boolean | null)[] = [];
  let value: boolean | null = initial;
  return {
    load: vi.fn(() => value),
    save: vi.fn((v: boolean) => {
      value = v;
      saved.push(v);
    }),
    saved,
  };
}

describe('AuthorizationStore', () => {
  it('持久化无数据时使用默认状态（false）', () => {
    const store = new AuthorizationStore(memoryPersistence(null), false);
    expect(store.isAuthorized()).toBe(false);
  });

  it('读取已有持久化授权状态', () => {
    const store = new AuthorizationStore(memoryPersistence(true), false);
    expect(store.isAuthorized()).toBe(true);
  });

  it('setAuthorized 写入并持久化', () => {
    const p = memoryPersistence(null);
    const store = new AuthorizationStore(p);
    store.setAuthorized(true);
    expect(store.isAuthorized()).toBe(true);
    expect(p.save).toHaveBeenCalledWith(true);
    expect(p.saved).toEqual([true]);
  });

  it('revoke 撤销并持久化为 false', () => {
    const p = memoryPersistence(true);
    const store = new AuthorizationStore(p);
    store.revoke();
    expect(store.isAuthorized()).toBe(false);
    expect(p.saved).toEqual([false]);
  });

  it('只操作内存与持久化替身，不触碰任何 OS/系统 API', () => {
    const p = memoryPersistence(null);
    const store = new AuthorizationStore(p);
    store.setAuthorized(true);
    store.revoke();
    expect(p.save).toHaveBeenCalledTimes(2);
  });
});
