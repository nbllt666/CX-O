/**
 * base client 地址解析单测。
 *
 * base.ts 存在模块级缓存（cachedBackendUrl / cachedWsUrl），
 * 每个用例通过 vi.resetModules() + 动态 import 获得全新模块实例隔离状态。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const BASE_PATH = './base';

type BaseModule = typeof import('./base');

async function loadBase(): Promise<BaseModule> {
  return import(BASE_PATH);
}

function mockElectronApi(overrides: Partial<NonNullable<Window['electronAPI']>> = {}) {
  window.electronAPI = {
    storeLoad: vi.fn().mockResolvedValue(null),
    storeSave: vi.fn().mockResolvedValue(undefined),
    openManagementWindow: vi.fn().mockResolvedValue(undefined),
    toggleDanmakuWindow: vi.fn().mockResolvedValue(undefined),
    closePet: vi.fn().mockResolvedValue(undefined),
    setDanmakuVisible: vi.fn().mockResolvedValue(undefined),
    onDanmakuVisibility: vi.fn().mockReturnValue(() => undefined),
    moveWindow: vi.fn().mockResolvedValue(undefined),
    setIgnoreMouseEvents: vi.fn().mockResolvedValue(undefined),
    setAlwaysOnTop: vi.fn().mockResolvedValue(undefined),
    setWindowSize: vi.fn().mockResolvedValue(undefined),
    getBackendUrl: vi.fn().mockResolvedValue(null),
    setBackendUrl: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
});

afterEach(() => {
  delete window.electronAPI;
  localStorage.clear();
});

describe('httpToWsUrl', () => {
  it('http → ws，并去除末尾斜杠', async () => {
    const { httpToWsUrl } = await loadBase();
    expect(httpToWsUrl('http://127.0.0.1:8100')).toBe('ws://127.0.0.1:8100');
    expect(httpToWsUrl('http://example.com/')).toBe('ws://example.com');
  });

  it('https → wss', async () => {
    const { httpToWsUrl } = await loadBase();
    expect(httpToWsUrl('https://api.example.com:8443')).toBe('wss://api.example.com:8443');
  });

  it('保留路径段，且不被路径中的 http 子串干扰', async () => {
    const { httpToWsUrl } = await loadBase();
    expect(httpToWsUrl('https://example.com/http-proxy')).toBe('wss://example.com/http-proxy');
  });

  it('非法 URL 走朴素替换兜底（仅替换 http 前缀，https 残留 s 与参考实现口径一致）', async () => {
    const { httpToWsUrl } = await loadBase();
    // 兜底逻辑为 replace(/^http/i, ...)：https 被替换为 wss 后残留原 s 后缀
    expect(httpToWsUrl('https://broken url space')).toBe('wsss://broken url space');
    expect(httpToWsUrl('http://broken url space/')).toBe('ws://broken url space');
  });
});

describe('getApiBaseUrl 优先级', () => {
  it('无缓存无存储时返回默认值', async () => {
    const { getApiBaseUrl, DEFAULT_BACKEND_URL } = await loadBase();
    expect(getApiBaseUrl()).toBe(DEFAULT_BACKEND_URL);
  });

  it('localStorage 值优先于默认值', async () => {
    const { getApiBaseUrl, STORAGE_KEYS } = await loadBase();
    localStorage.setItem(STORAGE_KEYS.backendUrl, 'http://192.168.1.10:9000');
    expect(getApiBaseUrl()).toBe('http://192.168.1.10:9000');
  });

  it('setBackendUrl 写入的缓存优先于 localStorage', async () => {
    const { getApiBaseUrl, setBackendUrl, STORAGE_KEYS } = await loadBase();
    localStorage.setItem(STORAGE_KEYS.backendUrl, 'http://old:1');
    setBackendUrl('http://new:2');
    expect(getApiBaseUrl()).toBe('http://new:2');
    expect(localStorage.getItem(STORAGE_KEYS.backendUrl)).toBe('http://new:2');
  });
});

describe('getWsBaseUrl 优先级与推导', () => {
  it('无任何显式 WS 配置时由 HTTP 地址推导', async () => {
    const { getWsBaseUrl, setBackendUrl } = await loadBase();
    setBackendUrl('https://pet.example.com');
    expect(getWsBaseUrl()).toBe('wss://pet.example.com');
  });

  it('localStorage 显式 WS 地址优先于推导', async () => {
    const { getWsBaseUrl, getApiBaseUrl, setBackendUrl, STORAGE_KEYS } = await loadBase();
    localStorage.setItem(STORAGE_KEYS.wsUrl, 'ws://explicit:1234');
    setBackendUrl('http://backend:8100');
    expect(getApiBaseUrl()).toBe('http://backend:8100');
    expect(getWsBaseUrl()).toBe('ws://explicit:1234');
  });

  it('setWsUrl 运行时覆盖并持久化', async () => {
    const { getWsBaseUrl, setWsUrl, STORAGE_KEYS } = await loadBase();
    setWsUrl('wss://ws.example.com');
    expect(getWsBaseUrl()).toBe('wss://ws.example.com');
    expect(localStorage.getItem(STORAGE_KEYS.wsUrl)).toBe('wss://ws.example.com');
  });
});

describe('setBackendUrl 的 Electron 持久化', () => {
  it('Electron 环境下同步调用 IPC setBackendUrl', async () => {
    mockElectronApi();
    const { setBackendUrl } = await loadBase();
    setBackendUrl('http://remote:8100');
    expect(window.electronAPI!.setBackendUrl).toHaveBeenCalledWith('http://remote:8100');
  });

  it('浏览器环境下不触碰 electronAPI', async () => {
    const { setBackendUrl } = await loadBase();
    expect(() => setBackendUrl('http://remote:8100')).not.toThrow();
  });
});

describe('initBackendUrl 启动解析', () => {
  it('浏览器模式：localStorage > env > 默认', async () => {
    const { initBackendUrl, STORAGE_KEYS } = await loadBase();
    localStorage.setItem(STORAGE_KEYS.backendUrl, 'http://lan:8100');
    await expect(initBackendUrl()).resolves.toBe('http://lan:8100');
  });

  it('Electron 模式：IPC 返回地址优先，写缓存与 localStorage，https 推导 wss', async () => {
    mockElectronApi({ getBackendUrl: vi.fn().mockResolvedValue('https://cloud.example.com') });
    const { initBackendUrl, getApiBaseUrl, getWsBaseUrl, STORAGE_KEYS } = await loadBase();
    await expect(initBackendUrl()).resolves.toBe('https://cloud.example.com');
    expect(getApiBaseUrl()).toBe('https://cloud.example.com');
    expect(localStorage.getItem(STORAGE_KEYS.backendUrl)).toBe('https://cloud.example.com');
    expect(getWsBaseUrl()).toBe('wss://cloud.example.com');
  });

  it('Electron 模式：IPC 抛错时回退常规链', async () => {
    mockElectronApi({ getBackendUrl: vi.fn().mockRejectedValue(new Error('ipc down')) });
    const { initBackendUrl, DEFAULT_BACKEND_URL } = await loadBase();
    await expect(initBackendUrl()).resolves.toBe(DEFAULT_BACKEND_URL);
  });
});
