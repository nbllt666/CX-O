/**
 * neko 兼容层纯函数单测（Vitest）
 */
import { afterEach, beforeAll, afterAll, describe, expect, it, vi } from 'vitest';
import { nekoRequest, normalizePluginList, pluginUiUrl, setNekoPort } from './neko';

describe('normalizePluginList', () => {
  it('透传数组形态', () => {
    const list = normalizePluginList([
      { id: 'a', name: 'A', description: 'x' },
      { id: 'b', name: 'B' },
    ]);
    expect(list).toHaveLength(2);
    expect(list[0].id).toBe('a');
  });

  it('归一化 { plugins: [...] } 形态', () => {
    const list = normalizePluginList({ plugins: [{ id: 'a' }], length: 1 });
    expect(list).toHaveLength(1);
    expect(list[0].id).toBe('a');
  });

  it('兜底 { id: {...} } 字典形态', () => {
    const list = normalizePluginList({ alpha: { name: 'Alpha' }, beta: { version: '1.0' } });
    expect(list).toHaveLength(2);
    expect(list.some((p) => p.id === 'alpha' && p.name === 'Alpha')).toBe(true);
  });

  it('空/非法输入返回空数组', () => {
    expect(normalizePluginList(null)).toEqual([]);
    expect(normalizePluginList(undefined)).toEqual([]);
    expect(normalizePluginList('x')).toEqual([]);
  });
});

describe('pluginUiUrl', () => {
  it('拼接插件 UI 地址并在端口缺失时抛错', () => {
    setNekoPort(48916);
    expect(pluginUiUrl(null, '/plugin/foo/ui/')).toBe('http://127.0.0.1:48916/plugin/foo/ui/');
    expect(pluginUiUrl(null, 'plugin/foo/ui/')).toBe('http://127.0.0.1:48916/plugin/foo/ui/');
    setNekoPort(null);
    expect(() => pluginUiUrl(null, '/plugin/foo/ui/')).toThrow();
  });
});

describe('directRequest 非 JSON 响应防护', () => {
  // directRequest 内部调用 AbortSignal.timeout；jsdom 若未实现则打桩兜底
  // （fetch 为 mock，不消费 signal，桩返回值不影响断言）。生产行为不受影响。
  const originalSignalTimeout = AbortSignal.timeout;
  beforeAll(() => {
    if (typeof AbortSignal.timeout !== 'function') {
      (AbortSignal as unknown as { timeout: (ms: number) => AbortSignal }).timeout = () =>
        new AbortController().signal;
    }
  });
  afterAll(() => {
    if (typeof originalSignalTimeout !== 'function') {
      delete (AbortSignal as unknown as { timeout?: unknown }).timeout;
    }
  });

  afterEach(() => {
    setNekoPort(null);
    vi.unstubAllGlobals();
  });

  it('成功状态但响应体非合法 JSON：抛带状态码的解析错误（对齐 ipcRequest 错误风格）', async () => {
    setNekoPort(48916);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => '<html>Bad Gateway</html>',
      }),
    );
    await expect(nekoRequest('GET', '/health')).rejects.toThrow('Neko 响应解析失败 (200)：');
  });

  it('合法 JSON 响应仍正常解析返回（防回归）', async () => {
    setNekoPort(48916);
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: async () => JSON.stringify({ ok: true, version: '1.0' }),
      }),
    );
    await expect(nekoRequest<{ ok: boolean; version: string }>('GET', '/health')).resolves.toEqual({
      ok: true,
      version: '1.0',
    });
  });
});
