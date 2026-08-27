/**
 * PhysioUploader 单元测试（Vitest）。
 * 重点验证 M-G 修复项：HR 上送必须走每轮解析的最新后端地址（baseUrl()），
 * 不能沿用构造期 backendUrl 快照——设置页换址后下一轮即发新地址。
 */
import { describe, expect, it, vi } from 'vitest';
import { PhysioUploader } from './uploader';

function makeFetchCapture(): { impl: typeof fetch; urls: string[] } {
  const urls: string[] = [];
  const impl = (async (url: string | URL | Request) => {
    urls.push(String(url));
    return new Response('{}', { status: 200 });
  }) as unknown as typeof fetch;
  return { impl, urls };
}

describe('PhysioUploader 后端地址解析', () => {
  it('reportHr 每轮上送经 resolver 取最新地址（不再沿用构造期快照）', async () => {
    const { impl, urls } = makeFetchCapture();
    let currentUrl: string | null = 'http://127.0.0.1:8000';
    const up = new PhysioUploader({
      backendUrl: 'http://127.0.0.1:8000',
      backendUrlResolver: () => currentUrl,
      hrThrottleMs: 0,
      fetchImpl: impl,
    });

    await up.reportHr({ bpm: 70, ts: 1000, device_fingerprint: 'fp' });
    expect(urls[0]).toBe('http://127.0.0.1:8000/api/physio/hr');

    // 设置页换址后：下一轮 HR 上送必须命中新地址
    currentUrl = 'http://192.168.1.50:9000/';
    await up.reportHr({ bpm: 72, ts: 1001, device_fingerprint: 'fp' });
    expect(urls[1]).toBe('http://192.168.1.50:9000/api/physio/hr');
  });

  it('reportState 同样跟随最新地址；resolver 返回空值时回落构造期快照', async () => {
    const { impl, urls } = makeFetchCapture();
    let currentUrl: string | null = null;
    const up = new PhysioUploader({
      backendUrl: 'http://fallback:8000',
      backendUrlResolver: () => currentUrl,
      fetchImpl: impl,
    });

    // resolver 空 → 回落构造期快照
    await up.reportState({ system_idle_sec: 5, user_active: true });
    expect(urls[0]).toBe('http://fallback:8000/api/physio/state');

    // resolver 提供新地址 → 生效
    currentUrl = 'http://10.0.0.2:8000';
    await up.reportState({ system_idle_sec: 6, user_active: false });
    expect(urls[1]).toBe('http://10.0.0.2:8000/api/physio/state');
  });

  it('后端不可用时 reportHr 丢弃不抛异常（离线隔离语义保持）', async () => {
    const impl = (async () => {
      throw new Error('ECONNREFUSED');
    }) as unknown as typeof fetch;
    const logger = vi.fn();
    const up = new PhysioUploader({
      backendUrl: 'http://127.0.0.1:8000',
      hrThrottleMs: 0,
      fetchImpl: impl,
      logger,
    });
    await expect(up.reportHr({ bpm: 60, ts: 1, device_fingerprint: 'fp' })).resolves.toBe(false);
    expect(logger).toHaveBeenCalled();
  });
});
