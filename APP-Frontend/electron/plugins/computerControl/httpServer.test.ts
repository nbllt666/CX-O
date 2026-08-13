// @vitest-environment node
/**
 * SubTask 2.2/2.3 HTTPS 插件服务端到端安全测试。
 * 覆盖：健康检查、认证、防重放、授权、参数错误、成功路径，并断言认证/授权失败时
 * 不调用任何工具（无 OS 副作用）。
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import * as https from 'node:https';
import { ComputerControlHttpServer, type ToolHandler } from './httpServer';
import { Authenticator } from './auth';
import { generateSelfSignedCertificate } from './tls';

interface Resp {
  status: number;
  json: Record<string, unknown> | null;
}

function request(opts: {
  port: number;
  path: string;
  method: string;
  headers?: Record<string, string>;
  body?: unknown;
}): Promise<Resp> {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        host: '127.0.0.1',
        port: opts.port,
        path: opts.path,
        method: opts.method,
        headers: opts.headers,
        rejectUnauthorized: false,
      },
      (res) => {
        let data = '';
        res.on('data', (c) => (data += c));
        res.on('end', () => {
          let json: Record<string, unknown> | null = null;
          try {
            json = JSON.parse(data) as Record<string, unknown>;
          } catch {
            json = null;
          }
          resolve({ status: res.statusCode ?? 0, json });
        });
      },
    );
    req.on('error', reject);
    if (opts.body !== undefined) req.write(JSON.stringify(opts.body));
    req.end();
  });
}

const TOKEN = 'registration-token';
let authorized = false;
const screenTool = vi.fn(async () => ({ ok: true, code: 'OK', output: { done: true } }));

async function setupServer(): Promise<ComputerControlHttpServer> {
  const { cert, key } = generateSelfSignedCertificate();
  const authenticator = new Authenticator({ token: TOKEN });
  const tools: Record<string, ToolHandler> = {
    computer_screen_control: screenTool as unknown as ToolHandler,
  };
  const server = new ComputerControlHttpServer({
    authenticator,
    isAuthorized: () => authorized,
    tools,
    skills: [{ name: 'computer_screen_control', description: 'd', arguments: {} }],
    config: { host: '127.0.0.1', port: 0, tls: { cert, key } },
    fingerprint: 'AA:BB:CC',
    logger: () => undefined,
  });
  await server.start();
  return server;
}

describe('ComputerControlHttpServer', () => {
  let server: ComputerControlHttpServer;

  afterEach(async () => {
    authorized = false;
    screenTool.mockClear();
    await server?.stop();
  });

  it('GET /health 匿名可访问并返回指纹', async () => {
    server = await setupServer();
    const r = await request({ port: server.getPort(), path: '/health', method: 'GET' });
    expect(r.status).toBe(200);
    expect(r.json).toMatchObject({ ok: true, status: 'ok', fingerprint: 'AA:BB:CC' });
  });

  it('GET /tools 无令牌 → 401 UNAUTHORIZED', async () => {
    server = await setupServer();
    const r = await request({ port: server.getPort(), path: '/tools', method: 'GET' });
    expect(r.status).toBe(401);
    expect((r.json as { error: { code: string } }).error.code).toBe('UNAUTHORIZED');
  });

  it('GET /tools 令牌正确但未授权 → 403 NOT_AUTHORIZED', async () => {
    server = await setupServer();
    const r = await request({
      port: server.getPort(),
      path: '/tools',
      method: 'GET',
      headers: { Authorization: `Bearer ${TOKEN}` },
    });
    expect(r.status).toBe(403);
    expect((r.json as { error: { code: string } }).error.code).toBe('NOT_AUTHORIZED');
  });

  it('GET /tools 已授权 + 令牌 → 200 返回工具清单', async () => {
    authorized = true;
    server = await setupServer();
    const r = await request({
      port: server.getPort(),
      path: '/tools',
      method: 'GET',
      headers: { Authorization: `Bearer ${TOKEN}` },
    });
    expect(r.status).toBe(200);
    expect((r.json as { tools: string[] }).tools).toContain('computer_screen_control');
  });

  it('POST /call 无令牌 → 401 且不调用工具', async () => {
    authorized = true;
    server = await setupServer();
    const r = await request({
      port: server.getPort(),
      path: '/call',
      method: 'POST',
      body: { request_id: 'r1', tool: 'computer_screen_control', arguments: { action: 'capture' } },
    });
    expect(r.status).toBe(401);
    expect(screenTool).not.toHaveBeenCalled();
  });

  it('POST /call 令牌正确但未授权 → 403 且不调用工具', async () => {
    server = await setupServer();
    const r = await request({
      port: server.getPort(),
      path: '/call',
      method: 'POST',
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: { request_id: 'r2', tool: 'computer_screen_control', arguments: {} },
    });
    expect(r.status).toBe(403);
    expect(screenTool).not.toHaveBeenCalled();
  });

  it('POST /call 成功路径返回 200 并调用工具', async () => {
    authorized = true;
    server = await setupServer();
    const r = await request({
      port: server.getPort(),
      path: '/call',
      method: 'POST',
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: { request_id: 'r3', tool: 'computer_screen_control', arguments: { action: 'capture' } },
    });
    expect(r.status).toBe(200);
    expect((r.json as { result: unknown }).result).toEqual({ done: true });
    expect(screenTool).toHaveBeenCalledTimes(1);
  });

  it('POST /call 重复 request_id → 409 REPLAY_DETECTED 且工具只执行一次', async () => {
    authorized = true;
    server = await setupServer();
    const body = { request_id: 'dup', tool: 'computer_screen_control', arguments: { action: 'capture' } };
    const headers = { Authorization: `Bearer ${TOKEN}` };
    const first = await request({ port: server.getPort(), path: '/call', method: 'POST', headers, body });
    expect(first.status).toBe(200);
    const second = await request({ port: server.getPort(), path: '/call', method: 'POST', headers, body });
    expect(second.status).toBe(409);
    expect((second.json as { error: { code: string } }).error.code).toBe('REPLAY_DETECTED');
    expect(screenTool).toHaveBeenCalledTimes(1);
  });

  it('POST /call 未知工具 → 400 INVALID_ARGUMENT 且不调用工具', async () => {
    authorized = true;
    server = await setupServer();
    const r = await request({
      port: server.getPort(),
      path: '/call',
      method: 'POST',
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: { request_id: 'r4', tool: 'no_such_tool', arguments: {} },
    });
    expect(r.status).toBe(400);
    expect((r.json as { error: { code: string } }).error.code).toBe('INVALID_ARGUMENT');
    expect(screenTool).not.toHaveBeenCalled();
  });

  it('POST /call 请求体非对象 → 400 INVALID_ARGUMENT', async () => {
    authorized = true;
    server = await setupServer();
    const r = await request({
      port: server.getPort(),
      path: '/call',
      method: 'POST',
      headers: { Authorization: `Bearer ${TOKEN}` },
      body: [1, 2, 3],
    });
    expect(r.status).toBe(400);
    expect((r.json as { error: { code: string } }).error.code).toBe('INVALID_ARGUMENT');
  });

  it('未知端点 → 400 INVALID_ARGUMENT', async () => {
    server = await setupServer();
    const r = await request({ port: server.getPort(), path: '/nope', method: 'GET' });
    expect(r.status).toBe(400);
  });
});
