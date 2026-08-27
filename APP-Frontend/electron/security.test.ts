/**
 * IPC 来源守卫单测（Vitest）
 * 覆盖：file:// 信任 / 本机 http(任意端口) 信任 / 外部 http 与私有 IP 拒绝 /
 *       senderFrame null 拒绝 / 旧事件形态 sender?url 回退 / registerIpcHandler 守卫行为
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

// vi.mock 工厂会被提升到文件顶，须用 vi.hoisted 同步创建 mock，避免 TDZ 引用错误
const { ipcHandleMock } = vi.hoisted(() => ({ ipcHandleMock: vi.fn() }));

vi.mock('electron', () => ({
  ipcMain: { handle: ipcHandleMock },
}));

// 必须在 mock 之后导入被测模块
import {
  isTrustedSender,
  isTrustedUrl,
  registerIpcHandler,
  truncateForLog,
} from './security';

const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

/** 构造仅含 senderFrame 的伪 invoke event */
function evWithFrame(url: string | null | undefined): unknown {
  return { senderFrame: url === null ? null : { url } };
}

describe('isTrustedUrl', () => {
  it('file:// 来源信任（打包产物页面）', () => {
    expect(isTrustedUrl('file:///C:/app/dist/index.html')).toBe(true);
    expect(isTrustedUrl('FILE:///C:/app/index.html')).toBe(true); // 大小写不敏感
  });

  it('http://localhost:* 任意端口信任（dev server）', () => {
    expect(isTrustedUrl('http://localhost:3100/')).toBe(true);
    expect(isTrustedUrl('http://localhost:5173/pet?agentId=a1')).toBe(true);
    expect(isTrustedUrl('http://localhost')).toBe(true); // 无端口仍属本机回环
  });

  it('http://127.0.0.1:* 信任', () => {
    expect(isTrustedUrl('http://127.0.0.1:3100/#/danmaku')).toBe(true);
    expect(isTrustedUrl('http://127.0.0.1:9999')).toBe(true);
  });

  it('evil http 来源拒绝', () => {
    expect(isTrustedUrl('http://evil.example.com/pet')).toBe(false);
    expect(isTrustedUrl('https://localhost.evil.com/x')).toBe(false); // 锚定结尾防伪装域
    expect(isTrustedUrl('http://evil.com?fake=http://localhost')).toBe(false);
  });

  it('私有 IP 及其它网段 http 拒绝', () => {
    expect(isTrustedUrl('http://192.168.1.9:8000/api')).toBe(false);
    expect(isTrustedUrl('http://10.0.0.5/')).toBe(false);
    expect(isTrustedUrl('http://172.16.0.2:8200/')).toBe(false);
    expect(isTrustedUrl('http://[::1]:3100/')).toBe(false); // 未在白名单的 IPv6 回环写法
  });

  it('非法输入一律不可信', () => {
    expect(isTrustedUrl(null)).toBe(false);
    expect(isTrustedUrl(undefined)).toBe(false);
    expect(isTrustedUrl('')).toBe(false);
    expect(isTrustedUrl('about:blank')).toBe(false);
    expect(isTrustedUrl(12345)).toBe(false);
  });
});

describe('isTrustedSender（senderFrame 形态）', () => {
  it('正常 frame URL 判定透传', () => {
    expect(isTrustedSender(evWithFrame('file:///C:/app/index.html'))).toBe(true);
    expect(isTrustedSender(evWithFrame('http://localhost:3100/pet'))).toBe(true);
    expect(isTrustedSender(evWithFrame('http://evil.example.com/pet'))).toBe(false);
  });

  it('senderFrame 为 null（页面销毁瞬间）一律不可信', () => {
    expect(isTrustedSender(evWithFrame(null))).toBe(false);
  });

  it('senderFrame.url 为空串/undefined 不可信', () => {
    expect(isTrustedSender(evWithFrame(''))).toBe(false);
    expect(isTrustedSender(evWithFrame(undefined))).toBe(false);
  });

  it('frame 对象标记已销毁或 url getter 抛错 → 不可信', () => {
    expect(
      isTrustedSender({ senderFrame: { url: 'file:///a.html', isDestroyed: () => true } }),
    ).toBe(false);
    const throwing = {
      get url(): string {
        throw new Error('Object has been destroyed');
      },
    };
    expect(isTrustedSender({ senderFrame: throwing })).toBe(false);
  });

  it('旧事件形态（无 senderFrame 字段）回退 sender?url', () => {
    // 无 senderFrame 字段 + sender.getURL()
    expect(
      isTrustedSender({ sender: { getURL: () => 'file:///C:/app/index.html' } }),
    ).toBe(true);
    expect(
      isTrustedSender({ sender: { getURL: () => 'http://192.168.1.9:8000/' } }),
    ).toBe(false);
    // sender.url 属性回退
    expect(isTrustedSender({ sender: { url: 'http://127.0.0.1:3100/' } })).toBe(true);
    // 回退也拿不到 → 不可信
    expect(isTrustedSender({})).toBe(false);
    expect(isTrustedSender(null)).toBe(false);
  });
});

describe('registerIpcHandler 守卫行为', () => {
  beforeEach(() => {
    ipcHandleMock.mockClear();
    warnSpy.mockClear();
  });

  type WrappedHandler = (event: unknown, ...args: unknown[]) => Promise<unknown>;

  function captureWrappedHandler(): WrappedHandler {
    registerIpcHandler('test:channel', (_event, a: string) => `handled:${a}`);
    expect(ipcHandleMock).toHaveBeenCalledTimes(1);
    const [, wrapped] = ipcHandleMock.mock.calls[0] as unknown as [string, WrappedHandler];
    return wrapped;
  }

  it('可信来源放行业务 handler 并透传返回值', async () => {
    const wrapped = captureWrappedHandler();
    await expect(wrapped(evWithFrame('file:///C:/app/index.html'), 'x')).resolves.toBe(
      'handled:x',
    );
  });

  it('不可信来源拒绝：业务 handler 不执行，返回 undefined 且不抛错', async () => {
    const handler = vi.fn((_event, a: string) => `handled:${a}`);
    registerIpcHandler('test:reject', handler as never);
    const [, wrapped] = ipcHandleMock.mock.calls[0] as [string, (e: unknown, ...a: unknown[]) => Promise<unknown>];
    warnSpy.mockClear();
    await expect(wrapped(evWithFrame('http://evil.example.com/'), 'x')).resolves.toBeUndefined();
    expect(handler).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(String(warnSpy.mock.calls[0]?.[0])).toContain('channel=test:reject');
    // 被拒 URL 截断出现在 warning 中
    expect(String(warnSpy.mock.calls[0]?.[0])).toContain('evil.example.com');
  });

  it('warning 日志对超长 URL 做截断', () => {
    const long = `file:///${'a'.repeat(500)}.html`;
    const truncated = truncateForLog(long, 120);
    expect(truncated.length).toBeLessThanOrEqual(130);
    expect(truncated).toContain('[截断]');
    expect(truncateForLog(null)).toBe('(null)');
  });
});
