// @vitest-environment node
/**
 * SubTask 3.4 CxfcClient mock 测试。
 * 覆盖：注册携带 token/指纹、心跳携带 plugin_id+port、后端不可用退避重连、
 * 退出注销（DELETE）。全部经注入的 fetchImpl 模拟，无真实网络。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { CxfcClient, type PluginRuntimeInfo } from './client';

const INFO: PluginRuntimeInfo = {
  host: '127.0.0.1',
  port: 8443,
  name: 'computer-control',
  version: '1.0.0',
  capabilities: ['computer_control'],
  tools: [{ name: 'computer_screen_control' }],
  skills: [],
  token: 'reg-token-abc',
  tls_cert_fingerprint: 'AA:BB:CC:DD',
  tls_cert_pem: '-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----\n',
};

function jsonResponse(status: number, data: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

/** 可编程 fetch 替身：记录调用，按调用次序执行 handler。 */
function makeFetchMock(
  handler: (url: string, init?: RequestInit) => Promise<Response>,
): { fetchImpl: typeof fetch; calls: Array<{ url: string; method?: string; body?: string }> } {
  const calls: Array<{ url: string; method?: string; body?: string }> = [];
  const fetchImpl = ((url: string, init?: RequestInit) => {
    const u = String(url);
    calls.push({ url: u, method: init?.method, body: init?.body as string | undefined });
    return handler(u, init);
  }) as typeof fetch;
  return { fetchImpl, calls };
}

describe('CxfcClient', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('注册携带 token 与指纹，随后按周期发心跳', async () => {
    let registerCalls = 0;
    const { fetchImpl, calls } = makeFetchMock(async (url, init) => {
      if (url.endsWith('/cxfc/register')) {
        registerCalls += 1;
        const body = JSON.parse(init?.body as string);
        // 断言注册载荷包含令牌与指纹
        expect(body.token).toBe('reg-token-abc');
        expect(body.tls_cert_fingerprint).toBe('AA:BB:CC:DD');
        expect(body.tls_cert_pem).toContain('BEGIN CERTIFICATE');
        expect(body.host).toBe('127.0.0.1');
        expect(body.port).toBe(8443);
        return jsonResponse(200, { status: 'ok', plugin_id: 'cxfc_127.0.0.1_8443' });
      }
      if (url.endsWith('/cxfc/heartbeat')) {
        const body = JSON.parse(init?.body as string);
        expect(body.plugin_id).toBe('cxfc_127.0.0.1_8443');
        expect(body.port).toBe(8443);
        return jsonResponse(200, { status: 'alive' });
      }
      return jsonResponse(404, {});
    });

    const client = new CxfcClient({
      backendUrl: 'http://127.0.0.1:8000',
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      retryBaseDelayMs: 100,
      maxRetryDelayMs: 500,
      fetchImpl,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(10); // 完成注册
    expect(registerCalls).toBe(1);
    expect(client.isRegistered()).toBe(true);
    expect(client.getPluginId()).toBe('cxfc_127.0.0.1_8443');

    // 推进一个心跳周期 → 发送心跳
    await vi.advanceTimersByTimeAsync(1000);
    const heartbeatCalls = calls.filter((c) => c.url.endsWith('/cxfc/heartbeat'));
    expect(heartbeatCalls.length).toBe(1);

    await client.stop();
  });

  it('后端不可用时退避重连，恢复后注册成功', async () => {
    let attempts = 0;
    const { fetchImpl } = makeFetchMock(async (url, _init) => {
      if (url.endsWith('/cxfc/register')) {
        attempts += 1;
        if (attempts === 1) {
          // 首次注册失败（后端不可用）
          return jsonResponse(500, {});
        }
        return jsonResponse(200, { status: 'ok', plugin_id: 'cxfc_127.0.0.1_8443' });
      }
      return jsonResponse(200, { status: 'alive' });
    });

    const client = new CxfcClient({
      backendUrl: 'http://127.0.0.1:8000',
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      retryBaseDelayMs: 100,
      maxRetryDelayMs: 500,
      fetchImpl,
      logger: () => undefined,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(attempts).toBe(1);
    expect(client.isRegistered()).toBe(false);

    // 推进退避窗口 → 触发重试并成功
    await vi.advanceTimersByTimeAsync(500);
    expect(attempts).toBeGreaterThanOrEqual(2);
    expect(client.isRegistered()).toBe(true);

    await client.stop();
  });

  it('心跳返回 404 时重置为未注册以便重新注册', async () => {
    const { fetchImpl } = makeFetchMock(async (url, _init) => {
      if (url.endsWith('/cxfc/register')) {
        return jsonResponse(200, { status: 'ok', plugin_id: 'cxfc_127.0.0.1_8443' });
      }
      if (url.endsWith('/cxfc/heartbeat')) {
        return jsonResponse(404, { detail: '插件不存在' });
      }
      return jsonResponse(404, {});
    });

    const client = new CxfcClient({
      backendUrl: 'http://127.0.0.1:8000',
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      fetchImpl,
      logger: () => undefined,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(client.isRegistered()).toBe(true);

    // 一个心跳周期后心跳 404 → 重置未注册
    await vi.advanceTimersByTimeAsync(1000);
    expect(client.isRegistered()).toBe(false);

    await client.stop();
  });

  it('退出 stop 时调用 DELETE 注销', async () => {
    const { fetchImpl, calls } = makeFetchMock(async (url, _init) => {
      if (url.endsWith('/cxfc/register')) {
        return jsonResponse(200, { status: 'ok', plugin_id: 'cxfc_127.0.0.1_8443' });
      }
      if (url.endsWith('/cxfc/heartbeat')) {
        return jsonResponse(200, { status: 'alive' });
      }
      return jsonResponse(200, { status: 'ok' });
    });

    const client = new CxfcClient({
      backendUrl: 'http://127.0.0.1:8000',
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      fetchImpl,
      logger: () => undefined,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(client.isRegistered()).toBe(true);

    await client.stop();
    const deleteCalls = calls.filter(
      (c) => c.method === 'DELETE' && c.url.endsWith('/cxfc/plugins/cxfc_127.0.0.1_8443'),
    );
    expect(deleteCalls.length).toBe(1);
    expect(client.isRegistered()).toBe(false);
  });
});
