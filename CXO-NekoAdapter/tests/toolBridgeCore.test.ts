/**
 * 桥接核心纯逻辑迁移验证（骨架期最小单测，保障行为等价）
 * 完整测试套件由后续任务补齐。
 */
import { describe, it, expect, vi } from 'vitest';
import {
  ToolRegistrarStore,
  parsePluginIdFromSource,
  buildToolSchema,
  handleRegistrarRoute,
  executeNekoToolCall,
  NEKO_FORWARD_TIMEOUT_MS,
  jsonPayload,
  type JsonBody,
} from '../src/bridge/toolBridgeCore';

describe('parsePluginIdFromSource', () => {
  it('解析 plugin:{id} 标签', () => {
    expect(parsePluginIdFromSource('plugin:abc-123')).toBe('abc-123');
    expect(parsePluginIdFromSource('plugin:a.b')).toBe('a.b'); // 点号 id（对齐源用例）
  });
  it('非 plugin 前缀/空值返回 null', () => {
    expect(parsePluginIdFromSource('builtin:xx')).toBeNull();
    expect(parsePluginIdFromSource('other')).toBeNull();
    expect(parsePluginIdFromSource(null)).toBeNull();
    expect(parsePluginIdFromSource(undefined)).toBeNull();
  });
});

describe('buildToolSchema', () => {
  it('映射 CXFC 工具 schema（returns 固定空对象）', () => {
    const schema = buildToolSchema({ name: 't', description: 'd', parameters: { a: { type: 'string' } } });
    expect(schema).toEqual({ name: 't', description: 'd', parameters: { a: { type: 'string' } }, returns: {} });
  });
  it('缺省 description/parameters 回落空值（对齐源用例语义）', () => {
    expect(buildToolSchema({ name: 't' })).toEqual({ name: 't', description: '', parameters: {}, returns: {} });
  });
});

describe('ToolRegistrarStore', () => {
  it('注册/更新并从 source 解析 plugin_id', () => {
    const store = new ToolRegistrarStore();
    const res = store.register({ name: 't1', source: 'plugin:p1', role: 'r1' });
    expect(res.ok).toBe(true);
    expect(store.get('t1')?.plugin_id).toBe('p1');
    expect(store.size()).toBe(1);
  });
  it('unregister/clearBySource 语义', () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 'a', source: 'plugin:p1' });
    store.register({ name: 'b', source: 'plugin:p2' });
    expect(store.unregister('a')).toBe(true);
    expect(store.unregister('a')).toBe(false);
    expect(store.clearBySource('plugin:p2')).toBe(1);
    expect(store.size()).toBe(0);
  });
  it('list 按名排序稳定；schema 含 name/description/parameters/returns', () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 'zz', description: 'd2', parameters: { a: 1 } });
    store.register({ name: 'aa' });
    const names = store.list().map((d) => d.name);
    expect(names).toEqual(['aa', 'zz']);
    const schemas = store.listSchemas() as Array<Record<string, unknown>>;
    expect(schemas[1]).toEqual(buildToolSchema({ name: 'zz', description: 'd2', parameters: { a: 1 } }));
  });
});

describe('handleRegistrarRoute', () => {
  it('register 缺 name 返回 400', () => {
    const res = handleRegistrarRoute(new ToolRegistrarStore(), 'POST', '/api/tools/register', {} as JsonBody);
    expect(res.status).toBe(400);
  });
  it('register 成功返回 affected_roles 与 plugin_id', () => {
    const res = handleRegistrarRoute(
      new ToolRegistrarStore(), 'POST', '/api/tools/register',
      { name: 't', source: 'plugin:p9', role: 'rr' } as JsonBody,
    );
    const parsed = JSON.parse(res.body) as { ok: boolean; affected_roles: string[]; plugin_id: string | null };
    expect(res.status).toBe(200);
    expect(parsed.affected_roles).toEqual(['rr']);
    expect(parsed.plugin_id).toBe('p9');
  });
  it('GET /api/tools 返回全量定义；未知路由 404', () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't1' });
    const list = handleRegistrarRoute(store, 'GET', '/api/tools', null);
    expect(list.status).toBe(200);
    expect(JSON.parse(list.body)).toHaveProperty('tools.t1');
    expect(handleRegistrarRoute(store, 'POST', '/api/nope', null).status).toBe(404);
  });
});

describe('executeNekoToolCall 错误映射', () => {
  it('缺少工具名 / 未知工具 / 缺插件归属 / 端口无效', async () => {
    const store = new ToolRegistrarStore();
    expect((await executeNekoToolCall(store, {}, { pluginPort: 1 })).code).toBe('INVALID_ARGUMENT');
    expect((await executeNekoToolCall(store, { tool: 'x' }, { pluginPort: 1 })).code).toBe('INVALID_ARGUMENT');
    store.register({ name: 'noPlugin' });
    expect((await executeNekoToolCall(store, { tool: 'noPlugin' }, { pluginPort: 1 })).code).toBe('INVALID_ARGUMENT');
    store.register({ name: 't', source: 'plugin:p1' });
    expect((await executeNekoToolCall(store, { tool: 't' }, { pluginPort: 0 })).code).toBe('PLUGIN_OFFLINE');
  });
  it('转发成功映射 output；is_error 映射 EXECUTION_FAILED', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    const okFetch = (async () => new Response(JSON.stringify({ output: 42, is_error: false }), { status: 200 })) as unknown as typeof fetch;
    expect(await executeNekoToolCall(store, { tool: 't' }, { pluginPort: 1234, fetchImpl: okFetch })).toEqual({ ok: true, result: 42 });
    const errFetch = (async () => new Response(JSON.stringify({ is_error: true, error: 'boom' }), { status: 200 })) as unknown as typeof fetch;
    const r = await executeNekoToolCall(store, { tool: 't' }, { pluginPort: 1234, fetchImpl: errFetch });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe('EXECUTION_FAILED');
  });
  it('转发抛错映射 PLUGIN_OFFLINE；超时常量为 15s', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    const failFetch = (async () => { throw new Error('conn refused'); }) as unknown as typeof fetch;
    const r = await executeNekoToolCall(store, { tool: 't' }, { pluginPort: 1234, fetchImpl: failFetch });
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe('PLUGIN_OFFLINE');
      expect(r.message).toContain('conn refused'); // 网络拒绝 message 保留原始错误（对齐源用例）
    }
    expect(NEKO_FORWARD_TIMEOUT_MS).toBe(15_000);
  });
});

describe('executeNekoToolCall 转发细节（M-G 修复回归，对齐源用例）', () => {
  it('把工具调用转发到插件服务器并映射结果（URL/arguments/call_id）', async () => {
    const store = new ToolRegistrarStore();
    store.register({ name: 't', source: 'plugin:p1' });
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { arguments?: unknown; call_id?: string };
      expect(body.arguments).toEqual({ a: 1 });
      expect(body.call_id).toBe('req1'); // request_id 透传为 call_id
      return new Response(JSON.stringify({ output: { done: true }, is_error: false }), { status: 200 });
    });
    const out = await executeNekoToolCall(
      store, { tool: 't', arguments: { a: 1 }, request_id: 'req1' }, { pluginPort: 48916, fetchImpl },
    );
    expect(out).toEqual({ ok: true, result: { done: true } });
    expect(fetchImpl).toHaveBeenCalledWith(
      expect.stringContaining('/api/llm-tools/callback/p1/t'),
      expect.anything(),
    );
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
});

describe('jsonPayload', () => {
  it('携带 JSON 头与 Content-Length', () => {
    const p = jsonPayload('{"a":1}', 200);
    expect(p.headers['Content-Type']).toContain('application/json');
    expect(p.headers['Content-Length']).toBe(String(Buffer.byteLength('{"a":1}')));
  });
});
