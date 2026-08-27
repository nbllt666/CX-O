/**
 * 工具→CXFC 桥核心逻辑单测（Vitest）
 */
import { describe, expect, it, vi } from 'vitest';
import {
  ToolRegistrarStore,
  parsePluginIdFromSource,
  buildToolSchema,
  handleRegistrarRoute,
  executeNekoToolCall,
  NEKO_FORWARD_TIMEOUT_MS,
} from './toolBridgeCore';

describe('parsePluginIdFromSource', () => {
  it('解析 plugin: 前缀', () => {
    expect(parsePluginIdFromSource('plugin:p1')).toBe('p1');
    expect(parsePluginIdFromSource('plugin:a.b')).toBe('a.b');
    expect(parsePluginIdFromSource('other')).toBeNull();
    expect(parsePluginIdFromSource(undefined)).toBeNull();
    expect(parsePluginIdFromSource(null)).toBeNull();
  });
});

describe('buildToolSchema', () => {
  it('映射 CXFC 工具 schema', () => {
    const schema = buildToolSchema({ name: 't', description: 'd', parameters: { a: { type: 'string' } } });
    expect(schema).toEqual({ name: 't', description: 'd', parameters: { a: { type: 'string' } }, returns: {} });
  });
});

describe('ToolRegistrarStore', () => {
  it('register/unregister/clear/listSchemas', () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't1', source: 'plugin:p1', description: 'x' });
    store.register({ name: 't2', source: 'plugin:p2' });
    expect(store.size()).toBe(2);
    expect(store.get('t1')?.plugin_id).toBe('p1');

    expect(store.unregister('t1')).toBe(true);
    expect(store.size()).toBe(1);

    store.register({ name: 't3', source: 'plugin:p2' });
    expect(store.clearBySource('plugin:p2')).toBe(2);
    expect(store.size()).toBe(0);

    store.register({ name: 'a', source: 'plugin:p' });
    store.register({ name: 'c', source: 'plugin:p' });
    store.register({ name: 'b', source: 'plugin:p' });
    expect(store.list().map((d) => d.name)).toEqual(['a', 'b', 'c']);
    expect(store.listSchemas().length).toBe(3);
  });
});

describe('handleRegistrarRoute（模拟 neko 主服务器 /api/tools/*）', () => {
  it('register → get → clear', () => {
    const store = new ToolRegistrarStore();
    const reg = handleRegistrarRoute(store, 'POST', '/api/tools/register', {
      name: 't1',
      description: 'desc',
      source: 'plugin:p1',
      parameters: { x: { type: 'number' } },
      timeout_seconds: 30,
    });
    expect(JSON.parse(reg.body)).toMatchObject({ ok: true, plugin_id: 'p1' });
    expect(store.get('t1')?.description).toBe('desc');

    const listResult = handleRegistrarRoute(store, 'GET', '/api/tools', null);
    const list = JSON.parse(listResult.body) as { tools: Record<string, unknown> };
    expect(Object.keys(list.tools)).toContain('t1');

    const clear = handleRegistrarRoute(store, 'POST', '/api/tools/clear', { source: 'plugin:p1' });
    expect(JSON.parse(clear.body).removed).toBe(1);
  });

  it('非 POST 返回 400', () => {
    const store = new ToolRegistrarStore();
    const r = handleRegistrarRoute(store, 'PUT', '/api/tools/register', { name: 'x' });
    expect(r.status).toBe(400);
  });
});

describe('executeNekoToolCall', () => {
  it('把工具调用转发到插件服务器并映射结果', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body));
      expect(body.arguments).toEqual({ a: 1 });
      return new Response(JSON.stringify({ output: { done: true }, is_error: false }), { status: 200 });
    });
    const out = await executeNekoToolCall(store, { tool: 't', arguments: { a: 1 }, request_id: 'req1' }, { pluginPort: 48916, fetchImpl });
    expect(out).toEqual({ ok: true, result: { done: true } });
    expect(fetchImpl).toHaveBeenCalledWith(
      expect.stringContaining('/api/llm-tools/callback/p1/t'),
      expect.anything(),
    );
  });

  it('is_error 映射为失败', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ output: null, is_error: true, error: 'boom' }), { status: 200 }));
    const out = await executeNekoToolCall(store, { tool: 't', arguments: {} }, { pluginPort: 48916, fetchImpl });
    expect(out).toEqual({ ok: false, code: 'EXECUTION_FAILED', message: 'boom' });
  });

  it('未知工具 / 缺插件端口 → 失败', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    expect((await executeNekoToolCall(store, { tool: 'missing', arguments: {} }, { pluginPort: 48916 })).ok).toBe(false);
    expect((await executeNekoToolCall(store, { tool: 't', arguments: {} }, { pluginPort: 0 })).ok).toBe(false);
  });

  it('M-G：转发请求携带 abort signal（超时上限 NEKO_FORWARD_TIMEOUT_MS）', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    let capturedSignal: AbortSignal | null | undefined;
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      capturedSignal = init?.signal ?? null;
      return new Response(JSON.stringify({ output: null, is_error: false }), { status: 200 });
    });
    await executeNekoToolCall(store, { tool: 't', arguments: {} }, { pluginPort: 48916, fetchImpl });
    expect(capturedSignal).toBeInstanceOf(AbortSignal);
    expect(NEKO_FORWARD_TIMEOUT_MS).toBe(15000);
  });

  it('M-G：超时中止映射为 PLUGIN_OFFLINE（语义与邻近网络错误一致，message 标明超时）', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    const timeoutLikeError = Object.assign(new Error('The operation was aborted due to timeout'), {
      name: 'TimeoutError',
    });
    const fetchImpl = vi.fn(async () => {
      throw timeoutLikeError;
    }) as unknown as typeof fetch;
    const out = await executeNekoToolCall(store, { tool: 't', arguments: {} }, { pluginPort: 48916, fetchImpl });
    expect(out.ok).toBe(false);
    if (!out.ok) {
      expect(out.code).toBe('PLUGIN_OFFLINE');
      expect(out.message).toContain('超时');
    }
  });

  it('M-G：网络拒绝（非超时）仍映射为 PLUGIN_OFFLINE', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    const fetchImpl = vi.fn(async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const out = await executeNekoToolCall(store, { tool: 't', arguments: {} }, { pluginPort: 48916, fetchImpl });
    expect(out).toMatchObject({ ok: false, code: 'PLUGIN_OFFLINE', message: expect.stringContaining('ECONNREFUSED') });
  });
});
