import { afterEach, describe, expect, it, vi } from 'vitest';
import { chatApi } from './chat';

afterEach(() => vi.unstubAllGlobals());

describe('SSE 业务错误与读取资源', () => {
  it('跳过坏 JSON，但消费方收到 error 抛出的错误会传播并取消 reader', async () => {
    const cancel = vi.fn().mockResolvedValue(undefined);
    const releaseLock = vi.fn();
    const read = vi.fn().mockResolvedValue({ done: false, value: new TextEncoder().encode(
      'data: broken-json\n\ndata: {"type":"error","error":"upstream failed"}\n\n',
    ) });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body: { getReader: () => ({ read, cancel, releaseLock }) } }));
    await expect(chatApi.sendMessageStream('hello', (chunk) => {
      if (chunk.type === 'error') throw new Error(String(chunk.error));
    })).rejects.toThrow('upstream failed');
    expect(read).toHaveBeenCalledOnce();
    expect(cancel).toHaveBeenCalledOnce();
    expect(releaseLock).toHaveBeenCalledOnce();
  });
});
