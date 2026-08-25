/**
 * storage 工厂单测：createStorage() 按运行环境选择持久化后端。
 *
 * - 浏览器模式：包装 localStorage（createJSONStorage 语义：setItem 收字符串、getItem 返回解析值）
 * - Electron 模式：包装 electronStorage（内存 cache + localStorage 备份 + IPC storeSave）
 *
 * electronStorage 含模块级 cache，用例间通过 vi.resetModules() 隔离。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

type StorageModule = typeof import('./createStorage');

function mockElectronApi() {
  const storeSave = vi.fn().mockResolvedValue(undefined);
  window.electronAPI = {
    storeLoad: vi.fn().mockResolvedValue(null),
    storeSave,
    openManagementWindow: vi.fn().mockResolvedValue(undefined),
    toggleDanmakuWindow: vi.fn().mockResolvedValue(undefined),
    openPet: vi.fn().mockResolvedValue(undefined),
    closePet: vi.fn().mockResolvedValue(undefined),
    setDanmakuVisible: vi.fn().mockResolvedValue(undefined),
    onDanmakuVisibility: vi.fn().mockReturnValue(() => undefined),
    moveWindow: vi.fn().mockResolvedValue(undefined),
    setIgnoreMouseEvents: vi.fn().mockResolvedValue(undefined),
    setAlwaysOnTop: vi.fn().mockResolvedValue(undefined),
    setWindowSize: vi.fn().mockResolvedValue(undefined),
    openExternal: vi.fn().mockResolvedValue(undefined),
    getBackendUrl: vi.fn().mockResolvedValue(null),
    setBackendUrl: vi.fn().mockResolvedValue(undefined),
    getComputerControlAuth: vi.fn().mockResolvedValue(false),
    setComputerControlAuth: vi.fn().mockResolvedValue(false),
    getComputerControlInfo: vi.fn().mockResolvedValue({
      running: false,
      port: null,
      fingerprint: null,
      authorized: false,
    }),
    pickModelFile: vi.fn().mockResolvedValue({ canceled: true, path: undefined }),
    readModelFile: vi.fn().mockResolvedValue(null),
    getStartupSettings: vi.fn().mockResolvedValue({
      supported: false,
      autoStart: false,
      runAsAdmin: false,
      isAdmin: false,
    }),
    setAutoStart: vi.fn().mockResolvedValue({
      supported: false,
      autoStart: false,
      runAsAdmin: false,
      isAdmin: false,
    }),
    setRunAsAdmin: vi.fn().mockResolvedValue({
      supported: false,
      autoStart: false,
      runAsAdmin: false,
      isAdmin: false,
    }),
  };
  return { storeSave };
}

beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
});

afterEach(() => {
  delete window.electronAPI;
  localStorage.clear();
});

describe('浏览器模式', () => {
  it('setItem 经 JSON 层编码写入 localStorage，getItem 解码还原原值', async () => {
    const { createStorage }: StorageModule = await import('./createStorage');
    const storage = createStorage();
    const payload = { state: { n: 42 }, version: 0 };

    storage?.setItem('cxo-pet-test', payload);

    // createJSONStorage 语义：底层存 JSON.stringify(payload)，读回 JSON.parse 一次
    expect(localStorage.getItem('cxo-pet-test')).toBe(JSON.stringify(payload));
    expect(storage?.getItem('cxo-pet-test')).toEqual(payload);
  });

  it('removeItem 清除 localStorage 键', async () => {
    const { createStorage }: StorageModule = await import('./createStorage');
    const storage = createStorage();

    storage?.setItem('cxo-pet-test', { state: null, version: 0 });
    storage?.removeItem('cxo-pet-test');

    expect(localStorage.getItem('cxo-pet-test')).toBeNull();
    expect(storage?.getItem('cxo-pet-test')).toBeNull();
  });

  it('未命中时 getItem 返回 null', async () => {
    const { createStorage }: StorageModule = await import('./createStorage');
    const storage = createStorage();
    expect(storage?.getItem('not-exist')).toBeNull();
  });
});

describe('Electron 模式', () => {
  it('setItem 三写：内存 cache、localStorage 备份、IPC storeSave', async () => {
    const { storeSave } = mockElectronApi();
    const { createStorage }: StorageModule = await import('./createStorage');
    const storage = createStorage();
    const payload = { state: { theme: 'dark' }, version: 1 };
    // createJSONStorage 对 payload 做 JSON 编码，electronStorage 收到的是编码后的串
    const encoded = JSON.stringify(payload);

    storage?.setItem('cxo-pet-theme', payload);

    expect(localStorage.getItem('cxo-pet-theme')).toBe(encoded);
    expect(storeSave).toHaveBeenCalledWith('cxo-pet-theme', encoded);
    // 内存 cache 命中：即使删掉 localStorage 备份，getItem 仍可读回原始 payload
    localStorage.removeItem('cxo-pet-theme');
    expect(storage?.getItem('cxo-pet-theme')).toEqual(payload);
  });

  it('removeItem 清 cache 与 localStorage，并以空串通知主进程', async () => {
    const { storeSave } = mockElectronApi();
    const { createStorage }: StorageModule = await import('./createStorage');
    const storage = createStorage();

    storage?.setItem('cxo-pet-theme', { state: null, version: 0 });
    storeSave.mockClear();
    storage?.removeItem('cxo-pet-theme');

    expect(localStorage.getItem('cxo-pet-theme')).toBeNull();
    expect(storage?.getItem('cxo-pet-theme')).toBeNull();
    expect(storeSave).toHaveBeenCalledWith('cxo-pet-theme', '');
  });

  it('IPC storeSave 失败不影响本地写入', async () => {
    const { storeSave } = mockElectronApi();
    storeSave.mockRejectedValue(new Error('ipc down'));
    const { createStorage }: StorageModule = await import('./createStorage');
    const storage = createStorage();

    expect(() =>
      storage?.setItem('cxo-pet-theme', { state: null, version: 0 }),
    ).not.toThrow();
    expect(localStorage.getItem('cxo-pet-theme')).not.toBeNull();
  });
});
