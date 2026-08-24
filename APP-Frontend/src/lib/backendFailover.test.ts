/**
 * backendFailover 单元测试：候选集持久化 / 可达性探测 / 集群角色 / 故障转移主流程。
 * 全部 mock fetch，不发真实网络；localStorage 由 jsdom 提供。
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';

import {
  normalize,
  probeBackend,
  readClusterRole,
  fetchClusterPeers,
  fetchDiscoveryBackends,
  readCandidates,
  writeCandidates,
  refreshCandidates,
  runBackendFailover,
  backendFailoverInternals,
} from './backendFailover';
import { httpToWsUrl } from '../api/base';

const BACKEND_KEY = 'cxo-backend-url';
const WS_KEY = 'cxo-ws-url';

type FetchStub = (url: string) => { ok: boolean; json?: () => Promise<unknown> };

function stubFetch(fn: FetchStub): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const r = fn(url);
      return {
        ok: !!r.ok,
        status: r.ok ? 200 : 503,
        json: r.json ?? (() => Promise.resolve(null)),
      };
    }),
  );
}

function healthyJson(json: unknown) {
  return { ok: true, status: 200, json: () => Promise.resolve(json) };
}

beforeEach(() => {
  localStorage.clear();
  // 默认后端 A
  localStorage.setItem(BACKEND_KEY, 'http://127.0.0.1:8100');
  vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('normalize', () => {
  it('去掉末尾斜杠', () => {
    expect(normalize('http://a:8100/')).toBe('http://a:8100');
    expect(normalize('http://a:8100')).toBe('http://a:8100');
  });
});

describe('候选集持久化', () => {
  it('写入后可读回，且去重复/去空', () => {
    writeCandidates(['http://b:8100/', 'http://b:8100', 'http://c:8100', '']);
    expect(readCandidates()).toEqual(['http://b:8100', 'http://c:8100']);
  });
});

describe('probeBackend', () => {
  it('health 返回 ok → true', async () => {
    stubFetch(() => healthyJson({}));
    expect(await probeBackend('http://a:8100')).toBe(true);
  });
  it('health 非 ok → false', async () => {
    stubFetch(() => ({ ok: false }));
    expect(await probeBackend('http://a:8100')).toBe(false);
  });
  it('fetch 抛错 → false', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('network'))));
    expect(await probeBackend('http://a:8100')).toBe(false);
  });
});

describe('读取集群信息', () => {
  it('readClusterRole 解析 active', async () => {
    stubFetch((url) =>
      url.endsWith('/api/cluster/state')
        ? healthyJson({ state: { role: 'active', enabled: true } })
        : healthyJson({}),
    );
    expect(await readClusterRole('http://b:8100')).toBe('active');
  });
  it('fetchClusterPeers 返回对等节点', async () => {
    stubFetch((url) =>
      url.endsWith('/api/cluster/state')
        ? healthyJson({ state: { enabled: true, peers: ['http://b:8100', 'http://c:8100'] } })
        : healthyJson({}),
    );
    expect(await fetchClusterPeers('http://a:8100')).toEqual(['http://b:8100', 'http://c:8100']);
  });
  it('fetchDiscoveryBackends 返回发现后端', async () => {
    stubFetch((url) =>
      url.endsWith('/api/discovery/backends')
        ? healthyJson({ backends: [{ url: 'http://192.168.1.10:8100' }] })
        : healthyJson({}),
    );
    expect(await fetchDiscoveryBackends('http://a:8100')).toEqual(['http://192.168.1.10:8100']);
  });
});

describe('refreshCandidates', () => {
  it('合并 当前 + cluster peers + 局域网发现 并持久化', async () => {
    stubFetch((url) => {
      if (url.endsWith('/api/cluster/state')) {
        return healthyJson({ state: { enabled: true, peers: ['http://b:8100'] } });
      }
      if (url.endsWith('/api/discovery/backends')) {
        return healthyJson({ backends: [{ url: 'http://192.168.1.20:8100' }] });
      }
      return healthyJson({});
    });
    const list = await refreshCandidates('http://a:8100');
    expect(list).toContain('http://a:8100');
    expect(list).toContain('http://b:8100');
    expect(list).toContain('http://192.168.1.20:8100');
    expect(readCandidates()).toContain('http://b:8100');
  });
});

describe('runBackendFailover', () => {
  it('当前仍健康 → 返回 null 且不切换', async () => {
    writeCandidates(['http://a:8100', 'http://b:8100']);
    stubFetch((url) =>
      url.endsWith('/health') ? { ok: true, status: 200, json: () => Promise.resolve({}) } : { ok: false },
    );
    expect(await runBackendFailover('http://a:8100')).toBeNull();
    expect(localStorage.getItem(BACKEND_KEY)).toBe('http://127.0.0.1:8100');
  });

  it('当前失联 + 有健康对等 → 切到对等并更新 base/ws 地址', async () => {
    const from = 'http://a:8100';
    const target = 'http://b:8100';
    localStorage.setItem(BACKEND_KEY, 'http://127.0.0.1:8100');
    writeCandidates([from, target]);
    // 让 a 不可达、b 可达：按 host 区分
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        const isB = url.includes('//b:8100');
        return {
          ok: isB,
          status: isB ? 200 : 503,
          json: async () => ({ state: { role: 'standby', enabled: true } }),
        };
      }),
    );
    const next = await runBackendFailover(from);
    expect(next).toBe(target);
    expect(localStorage.getItem(BACKEND_KEY)).toBe(target);
    expect(localStorage.getItem(WS_KEY)).toBe(httpToWsUrl(target));
  });

  it('当前失联 + 无健康对等 → 返回 null', async () => {
    const from = 'http://a:8100';
    writeCandidates([from, 'http://c:8100']);
    stubFetch(() => ({ ok: false }));
    expect(await runBackendFailover(from)).toBeNull();
  });

  it('多健康对等时优先选 active', async () => {
    const from = 'http://a:8100';
    const standby = 'http://b:8100';
    const active = 'http://c:8100';
    writeCandidates([from, standby, active]);
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes('//a:8100')) return { ok: false, status: 503, json: async () => ({}) };
        if (url.endsWith('/api/cluster/state')) {
          const role = url.includes('//c:8100') ? 'active' : 'standby';
          return { ok: true, status: 200, json: async () => ({ state: { role, enabled: true } }) };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      }),
    );
    expect(await runBackendFailover(from)).toBe(active);
  });

  it('最近刚切换到的目标在冷却期内失联 → 不再切回，防止震荡', async () => {
    const target = 'http://b:8100';
    backendFailoverInternals.writeLastSwitch(target); // 刚切到 b
    writeCandidates(['http://b:8100', 'http://a:8100']);
    stubFetch(() => ({ ok: false })); // b 也不可达
    // 冷却期内：b 是当前且刚切换过，即使 b 失联也不切回 a
    expect(await runBackendFailover(target)).toBeNull();
  });
});
