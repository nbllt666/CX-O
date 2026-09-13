// @vitest-environment node
/**
 * CxfcClient 单测（tests/cxfc-client.test.ts）
 * ============================================================================
 * 覆盖对齐源项目 APP-Frontend electron/cxfc/client.test.ts，并按迁移版实现补充：
 *  - 注册载荷构造（host/port/name/version/tools/skills/token/指纹/证书 PEM）；
 *  - 注册成功后按心跳周期发送心跳（plugin_id + port）；
 *  - 后端不可达时指数退避重连（base → 2x → 4x，封顶 maxRetryDelayMs）；
 *  - backendUrlResolver 每轮注册/心跳前生效，空值回落构造期快照；
 *  - stop 注销尽力而为（正常注销 + 注销抛错不阻断 + 注册在途 stop 补注销）；
 *  - 请求超时不悬挂（每请求携带 abort signal；超时错误被捕获进入退避重试）。
 *
 * 全部经注入 fetchImpl 模拟，无真实网络；定时器使用 vitest fake timers。
 * ============================================================================
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { CxfcClient, makeRequestId, type PluginRuntimeInfo } from '../src/shared/cxfc-client';

/** 标准插件运行信息样本 */
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

/** 构造 JSON 响应 */
function jsonResponse(status: number, data: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

/** 可编程 fetch 替身：记录调用（url/method/body），按调用次序执行 handler */
function makeFetchMock(
  handler: (url: string, init?: RequestInit) => Promise<Response>,
): { fetchImpl: typeof fetch; calls: Array<{ url: string; method?: string; body?: string }> } {
  const calls: Array<{ url: string; method?: string; body?: string }> = [];
  const fetchImpl = ((url: string | URL | Request, init?: RequestInit) => {
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

  it('注册载荷携带 host/port/name/version/tools/token/指纹与证书 PEM，随后按周期发心跳', async () => {
    let registerCalls = 0;
    const { fetchImpl, calls } = makeFetchMock(async (url, init) => {
      if (url.endsWith('/cxfc/register')) {
        registerCalls += 1;
        const body = JSON.parse(init?.body as string) as Record<string, unknown>;
        // 注册载荷完整构造断言（含 B-1 证书 PEM，供后端 TOFU 首次信任）
        expect(body.token).toBe('reg-token-abc');
        expect(body.tls_cert_fingerprint).toBe('AA:BB:CC:DD');
        expect(body.tls_cert_pem).toContain('BEGIN CERTIFICATE');
        expect(body.host).toBe('127.0.0.1');
        expect(body.port).toBe(8443);
        expect(body.name).toBe('computer-control');
        expect(body.version).toBe('1.0.0');
        expect(body.capabilities).toEqual(['computer_control']);
        expect(body.tools).toEqual([{ name: 'computer_screen_control' }]);
        expect(body.skills).toEqual([]);
        return jsonResponse(200, { status: 'ok', plugin_id: 'cxfc_127.0.0.1_8443' });
      }
      if (url.endsWith('/cxfc/heartbeat')) {
        const body = JSON.parse(init?.body as string) as Record<string, unknown>;
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

    // 推进一个心跳周期 → 发送心跳；再推进半周期 → 不多发
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(500);
    const heartbeatCalls = calls.filter((c) => c.url.endsWith('/cxfc/heartbeat'));
    expect(heartbeatCalls.length).toBe(1);

    await client.stop();
  });

  it('注册失败（后端不可达）时按指数退避重连，恢复后注册成功', async () => {
    let attempts = 0;
    const { fetchImpl } = makeFetchMock(async (url) => {
      if (url.endsWith('/cxfc/register')) {
        attempts += 1;
        if (attempts === 1) return jsonResponse(500, {}); // 首次注册失败（后端不可用）
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

  it('指数退避间隔按 base→2x→4x 增长并封顶 maxRetryDelayMs', async () => {
    // 以 fake 时钟时间戳记录每次尝试（fake timers 会 mock Date.now），断言相邻间隔
    const times: number[] = [];
    const { fetchImpl } = makeFetchMock(async () => {
      times.push(Date.now());
      return jsonResponse(500, {}); // 一直失败，观察退避节奏
    });
    const client = new CxfcClient({
      backendUrl: 'http://b:1',
      readPluginInfo: () => INFO,
      retryBaseDelayMs: 1000,
      maxRetryDelayMs: 4000,
      fetchImpl,
    });
    client.start();
    // 推进足够窗口：应在 +base / +2x / +4x / 封顶 max 各触发一次
    await vi.advanceTimersByTimeAsync(20_000);
    expect(times.length).toBeGreaterThanOrEqual(5);
    const gaps = times.slice(1).map((t, i) => t - times[i]);
    expect(gaps.slice(0, 4)).toEqual([1000, 2000, 4000, 4000]); // base → 2x → 4x → 封顶 max=4000
    expect(gaps[4]).toBe(4000); // 封顶后保持 max
    await client.stop();
  });

  it('backendUrlResolver 每轮生效：注册与心跳分别使用解析地址，空值回落构造期快照', async () => {
    const urls: string[] = [];
    const { fetchImpl } = makeFetchMock(async (url) => {
      urls.push(url);
      if (url.endsWith('/cxfc/register')) return jsonResponse(200, { status: 'ok', plugin_id: 'p1' });
      return jsonResponse(200, { status: 'alive' });
    });

    let current: string | null = 'http://resolver-a:1';
    const client = new CxfcClient({
      backendUrl: 'http://snapshot:9',
      backendUrlResolver: () => current,
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      fetchImpl,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(1); // 注册轮 → resolver-a
    expect(urls[0]).toBe('http://resolver-a:1/cxfc/register');

    current = 'http://resolver-b:2';
    await vi.advanceTimersByTimeAsync(1000); // 心跳轮 → resolver-b（配置变更无需重启）
    expect(urls[1]).toBe('http://resolver-b:2/cxfc/heartbeat');

    current = ''; // 空值 → 回落构造期 backendUrl 快照
    await vi.advanceTimersByTimeAsync(1000);
    expect(urls[2]).toBe('http://snapshot:9/cxfc/heartbeat');

    await client.stop();
  });

  it('心跳返回 404 时重置为未注册以便重新注册', async () => {
    const { fetchImpl } = makeFetchMock(async (url) => {
      if (url.endsWith('/cxfc/register')) return jsonResponse(200, { status: 'ok', plugin_id: 'cxfc_127.0.0.1_8443' });
      if (url.endsWith('/cxfc/heartbeat')) return jsonResponse(404, { detail: '插件不存在' });
      return jsonResponse(404, {});
    });

    const client = new CxfcClient({
      backendUrl: 'http://127.0.0.1:8000',
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      fetchImpl,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(client.isRegistered()).toBe(true);

    // 一个心跳周期后心跳 404 → 重置未注册
    await vi.advanceTimersByTimeAsync(1000);
    expect(client.isRegistered()).toBe(false);

    await client.stop();
  });

  it('stop 注销：注册成功后 stop 发送 DELETE 注销', async () => {
    const { fetchImpl, calls } = makeFetchMock(async (url) => {
      if (url.endsWith('/cxfc/register')) return jsonResponse(200, { status: 'ok', plugin_id: 'cxfc_127.0.0.1_8443' });
      if (url.endsWith('/cxfc/heartbeat')) return jsonResponse(200, { status: 'alive' });
      return jsonResponse(200, { status: 'ok' });
    });

    const client = new CxfcClient({
      backendUrl: 'http://127.0.0.1:8000',
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      fetchImpl,
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

  it('stop 尽力而为：注销请求抛错时 stop 仍正常完成不抛出', async () => {
    const { fetchImpl } = makeFetchMock(async (url) => {
      if (url.endsWith('/cxfc/register')) return jsonResponse(200, { status: 'ok', plugin_id: 'p1' });
      if (url.endsWith('/cxfc/heartbeat')) return jsonResponse(200, { status: 'alive' });
      // DELETE 注销分支：模拟网络错误
      throw new Error('ECONNREFUSED');
    });

    const client = new CxfcClient({
      backendUrl: 'http://b:1',
      readPluginInfo: () => INFO,
      heartbeatIntervalMs: 1000,
      fetchImpl,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(10);
    expect(client.isRegistered()).toBe(true);

    // 注销失败不阻断退出（尽力而为）：stop 正常完成；
    // 实现语义：仅注销成功才翻转 registered（失败保持 true，进程照常退出）
    await expect(client.stop()).resolves.toBeUndefined();
    expect(client.isRegistered()).toBe(true);
  });

  it('注册在途期间 stop：注册完成后补注销（尽力而为），循环终止不再排心跳', async () => {
    let resolveRegister!: (r: Response) => void;
    const { fetchImpl, calls } = makeFetchMock(async (url) => {
      if (String(url).endsWith('/cxfc/register')) {
        // 注册请求挂起在途
        return new Promise<Response>((resolve) => {
          resolveRegister = resolve;
        });
      }
      return jsonResponse(200, { status: 'ok' });
    });

    const client = new CxfcClient({ backendUrl: 'http://b:1', readPluginInfo: () => INFO, fetchImpl });
    client.start();
    await vi.advanceTimersByTimeAsync(1); // 注册请求在途

    // 在途期间 stop：此时 registered=false，stop 内注销分支被跳过
    const stopping = client.stop();
    resolveRegister(jsonResponse(200, { status: 'ok', plugin_id: 'p1' }) as unknown as Response);
    await vi.advanceTimersByTimeAsync(1); // flush 注册响应
    await stopping;

    // 实现的 stop 竞态复查：注册完成后应补注销
    expect(client.isRegistered()).toBe(false);
    const deletes = calls.filter((c) => c.method === 'DELETE' && c.url.endsWith('/cxfc/plugins/p1'));
    expect(deletes.length).toBe(1);
  });

  it('请求超时不悬挂：请求携带 abort signal，超时类错误被捕获并进入退避重试', async () => {
    let sawSignal = false;
    let attempts = 0;
    const { fetchImpl } = makeFetchMock(async (_url, init) => {
      attempts += 1;
      sawSignal = init?.signal instanceof AbortSignal || sawSignal;
      // 模拟后端挂起后由 abort 机制抛出的超时错误
      throw Object.assign(new Error('The operation was aborted due to timeout'), { name: 'TimeoutError' });
    });

    const client = new CxfcClient({
      backendUrl: 'http://b:1',
      readPluginInfo: () => INFO,
      retryBaseDelayMs: 100,
      maxRetryDelayMs: 500,
      fetchImpl,
    });
    client.start();
    await vi.advanceTimersByTimeAsync(1);
    expect(attempts).toBe(1);
    expect(sawSignal).toBe(true); // 每个请求都带超时 abort signal（REQUEST_TIMEOUT_MS），不会永久悬挂

    await vi.advanceTimersByTimeAsync(150);
    expect(attempts).toBe(2); // 超时错误被 runOnce 捕获，循环未卡死、按退避安排重试

    await client.stop();
  });

  it('makeRequestId 生成十六进制随机 id（128 字符内，防重放契约对齐）', () => {
    const a = makeRequestId();
    const b = makeRequestId();
    expect(a).toMatch(/^[0-9a-f]+$/);
    expect(a.length).toBe(32); // randomBytes(16).toString('hex')
    expect(a).not.toBe(b);
  });
});

