import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

/**
 * 测试 sendMessageStream 的 SSE 解析逻辑。
 *
 * 策略：mock global.fetch 返回 ReadableStream，让真实 sendMessageStream
 * 跑完整路径（TextDecoder + 按 \n 切分 + flushLine + onChunk + [DONE] 终止）。
 *
 * 覆盖：
 * - 标准 data: {...}\n 行解析
 * - data: [DONE] 终止符
 * - data: 与 data:（无空格）两种格式
 * - 单行 JSON 解析错误被吞掉（不影响后续）
 * - 空行 / 非 data 前缀行忽略
 * - \r\n 与 \n 行尾兼容
 * - 跨 chunk 的行拼接（buffer 残留）
 * - 流末尾无 \n 终止的残留帧
 * - 非 2xx 响应抛 Error
 * - 缺失 response.body 抛 Error
 * - 请求 body 含 message/agent_id/images
 */

async function makeStreamResponse(chunks: Uint8Array[], opts: { ok?: boolean; status?: number; statusText?: string } = {}): Promise<Response> {
  const { ok = true, status = 200, statusText = 'OK' } = opts;
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
  return {
    ok,
    status,
    statusText,
    body: stream,
    text: async () => '',
  } as unknown as Response;
}

function sseChunks(lines: string[]): Uint8Array[] {
  const encoder = new TextEncoder();
  return lines.map((line) => encoder.encode(line));
}

type ChatClientInstance = {
  sendMessageStream: (
    message: string,
    onChunk: (chunk: Record<string, unknown>) => void,
    agentId?: string,
    images?: string[]
  ) => Promise<void>;
};

async function makeClient(): Promise<ChatClientInstance> {
  const mod = await import('./chat');
  const Mixin = mod._ChatClientMixin as unknown as new () => ChatClientInstance;
  return new Mixin();
}

describe('_ChatClientMixin.sendMessageStream - SSE 解析', () => {
  let originalFetch: typeof global.fetch;
  let originalLocalStorage: Storage;

  beforeEach(() => {
    originalFetch = global.fetch;
    originalLocalStorage = global.localStorage;
    const store: Record<string, string> = {};
    Object.defineProperty(globalThis, 'localStorage', {
      value: {
        getItem: vi.fn((k: string) => store[k] ?? null),
        setItem: vi.fn((k: string, v: string) => { store[k] = v; }),
        removeItem: vi.fn((k: string) => { delete store[k]; }),
        clear: vi.fn(() => { for (const k of Object.keys(store)) delete store[k]; }),
        key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
        get length() { return Object.keys(store).length; },
      },
      configurable: true,
    });
  });

  afterEach(() => {
    global.fetch = originalFetch;
    Object.defineProperty(globalThis, 'localStorage', { value: originalLocalStorage, configurable: true });
    vi.restoreAllMocks();
  });

  it('逐行解析 data: {...} 并回调 onChunk', async () => {
    const response = await makeStreamResponse(sseChunks([
      'data: {"type":"start","message_id":"m1"}\n',
      'data: {"type":"partial","content":"hello"}\n',
      'data: {"type":"done","message_id":"m1"}\n',
      'data: [DONE]\n',
    ]));
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([
      { type: 'start', message_id: 'm1' },
      { type: 'partial', content: 'hello' },
      { type: 'done', message_id: 'm1' },
    ]);
  });

  it('data: [DONE] 终止读取循环（即使后续仍有数据也不回调）', async () => {
    const response = await makeStreamResponse(sseChunks([
      'data: {"type":"start"}\n',
      'data: [DONE]\n',
      'data: {"type":"partial","content":"should-not-receive"}\n',
    ]));
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }]);
  });

  it('兼容 data:{...} 无空格格式', async () => {
    const response = await makeStreamResponse(sseChunks([
      'data:{"type":"start"}\n',
      'data:[DONE]\n',
    ]));
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }]);
  });

  it('空 data: 行（payload 为空）被忽略，不回调', async () => {
    const response = await makeStreamResponse(sseChunks([
      'data: \n',
      'data: {"type":"start"}\n',
      'data:\n',
      'data: [DONE]\n',
    ]));
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }]);
  });

  it('非 data: 前缀行被忽略（注释行 / event / id 等）', async () => {
    const response = await makeStreamResponse(sseChunks([
      ': comment line\n',
      'event: message\n',
      'data: {"type":"start"}\n',
      'id: 42\n',
      'data: [DONE]\n',
    ]));
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }]);
  });

  it('JSON 解析失败的行被吞掉，不影响后续有效行', async () => {
    const response = await makeStreamResponse(sseChunks([
      'data: {invalid json}\n',
      'data: {"type":"start"}\n',
      'data: not-json\n',
      'data: {"type":"done"}\n',
      'data: [DONE]\n',
    ]));
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }, { type: 'done' }]);
  });

  it('兼容 \\r\\n 行尾（行尾 \\r 被剥离）', async () => {
    const response = await makeStreamResponse(sseChunks([
      'data: {"type":"start"}\r\n',
      'data: [DONE]\r\n',
    ]));
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }]);
  });

  it('跨 chunk 的行被正确拼接（一行被切到多个 chunk）', async () => {
    const encoder = new TextEncoder();
    const response = await makeStreamResponse([
      encoder.encode('data: {"type'),
      encoder.encode('":"start"}'),
      encoder.encode('\ndata: [DONE]\n'),
    ]);
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }]);
  });

  it('流末尾无 \\n 的残留帧也被处理', async () => {
    const encoder = new TextEncoder();
    const response = await makeStreamResponse([
      encoder.encode('data: {"type":"start"}\n'),
      encoder.encode('data: {"type":"done"}'),
    ]);
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    const received: Record<string, unknown>[] = [];
    await client.sendMessageStream('hi', (chunk) => received.push(chunk));

    expect(received).toEqual([{ type: 'start' }, { type: 'done' }]);
  });

  it('请求 body 含 message/agent_id/images 字段', async () => {
    const response = await makeStreamResponse(sseChunks(['data: [DONE]\n']));
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    await client.sendMessageStream('hello', () => {}, 'agent-7', ['img1']);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const callArgs = fetchSpy.mock.calls[0];
    expect(callArgs[0]).toContain('/api/chat/stream');
    const reqInit = callArgs[1] as RequestInit;
    expect(reqInit.method).toBe('POST');
    const body = JSON.parse(reqInit.body as string);
    expect(body).toEqual({ message: 'hello', agent_id: 'agent-7', images: ['img1'] });
  });

  it('非 2xx 响应抛 Error 含 status 与响应文本', async () => {
    const response = {
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      body: null,
      text: async () => 'server boom',
    } as unknown as Response;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    const client = await makeClient();
    await expect(client.sendMessageStream('hi', () => {})).rejects.toThrow(/500.*server boom/);
  });

  it('缺失 response.body 抛 Error', async () => {
    const response = {
      ok: true,
      status: 200,
      statusText: 'OK',
      body: null,
      text: async () => '',
    } as unknown as Response;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response);

    const client = await makeClient();
    await expect(client.sendMessageStream('hi', () => {})).rejects.toThrow(/请求失败/);
  });

  it('无 token 时不注入 Authorization 头', async () => {
    const response = await makeStreamResponse(sseChunks(['data: [DONE]\n']));
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    await client.sendMessageStream('hi', () => {});

    const reqInit = fetchSpy.mock.calls[0][1] as RequestInit;
    const headers = reqInit.headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
    expect(headers['Content-Type']).toBe('application/json');
    expect(headers.Accept).toBe('text/event-stream');
  });

  it('有 token 时注入 Bearer Authorization 头', async () => {
    localStorage.setItem('cxhms-token', 'test-token-abc');
    const response = await makeStreamResponse(sseChunks(['data: [DONE]\n']));
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(response);

    const client = await makeClient();
    await client.sendMessageStream('hi', () => {});

    const reqInit = fetchSpy.mock.calls[0][1] as RequestInit;
    const headers = reqInit.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer test-token-abc');
  });
});
