/**
 * 前端启动配置单元测试（Task 5：自启动 / 管理员权限启动）。
 * 纯逻辑层测试：mock electron.app 与 config 及 child_process，避免真实登录项/UAC 副作用。
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  app: {
    setLoginItemSettings: vi.fn<(_settings: { openAtLogin: boolean }) => void>(),
    getLoginItemSettings: vi.fn(() => ({ openAtLogin: false })),
  },
  config: {
    getConfig: vi.fn<(_key: string) => string | null>(() => null),
    setConfig: vi.fn<(_key: string, _value: string) => void>(),
  },
  cp: {
    execFileSync: vi.fn<(_cmd: string, _args: string[], _opts?: unknown) => unknown>(),
    spawn: vi.fn<
      (
        _cmd: string,
        _args: string[],
        _opts: { detached: boolean; stdio: string },
      ) => { unref: () => void }
    >(() => ({ unref: () => {} })),
  },
}));

vi.mock('electron', () => ({ app: mocks.app }));
vi.mock('./config', () => mocks.config);
vi.mock('node:child_process', () => ({
  default: {
    execFileSync: mocks.cp.execFileSync,
    spawn: mocks.cp.spawn,
  },
  execFileSync: mocks.cp.execFileSync,
  spawn: mocks.cp.spawn,
}));

import {
  applyStartupOnLaunch,
  getStartupSettings,
  isRunningAsAdmin,
  isSupportedPlatform,
  setAutoStart,
  setRunAsAdmin,
} from './startup';

function setPlatform(p: NodeJS.Platform): void {
  Object.defineProperty(process, 'platform', { value: p, configurable: true });
}

describe('startup 启动配置', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setPlatform('win32');
    mocks.config.getConfig.mockReturnValue(null);
    mocks.config.setConfig.mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('isSupportedPlatform：仅 Windows 返回 true', () => {
    setPlatform('win32');
    expect(isSupportedPlatform()).toBe(true);
    setPlatform('darwin');
    expect(isSupportedPlatform()).toBe(false);
    setPlatform('linux');
    expect(isSupportedPlatform()).toBe(false);
  });

  it('isRunningAsAdmin：net session 成功判定为管理员，抛错则非管理员', () => {
    mocks.cp.execFileSync.mockReturnValue(undefined);
    expect(isRunningAsAdmin()).toBe(true);
    mocks.cp.execFileSync.mockImplementation(() => {
      throw new Error('access denied');
    });
    expect(isRunningAsAdmin()).toBe(false);
  });

  it('isRunningAsAdmin：非 Windows 恒为 false，且不调用 net', () => {
    setPlatform('linux');
    expect(isRunningAsAdmin()).toBe(false);
    expect(mocks.cp.execFileSync).not.toHaveBeenCalled();
  });

  it('getStartupSettings：配置缺失时返回默认关闭态', () => {
    mocks.config.getConfig.mockReturnValue(null);
    const s = getStartupSettings();
    expect(s.supported).toBe(true);
    expect(s.autoStart).toBe(false);
    expect(s.runAsAdmin).toBe(false);
    expect(s.isAdmin).toBe(false);
  });

  it('getStartupSettings：读取持久化的 auto_start 与 run_as_admin', () => {
    mocks.config.getConfig.mockImplementation((k: string) =>
      k === 'auto_start' ? 'true' : k === 'run_as_admin' ? 'true' : null,
    );
    mocks.cp.execFileSync.mockReturnValue(undefined); // 管理员
    const s = getStartupSettings();
    expect(s.autoStart).toBe(true);
    expect(s.runAsAdmin).toBe(true);
    expect(s.isAdmin).toBe(true);
  });

  it('setAutoStart：持久化并同步系统登录项', () => {
    mocks.config.getConfig.mockReturnValue(null);
    const ok = setAutoStart(true);
    expect(ok).toBe(true);
    expect(mocks.config.setConfig).toHaveBeenCalledWith('auto_start', 'true');
    expect(mocks.app.setLoginItemSettings).toHaveBeenCalledWith({ openAtLogin: true });
  });

  it('setAutoStart：登录项更新失败时回滚持久化并返回 false', () => {
    mocks.config.getConfig.mockReturnValue(null);
    mocks.app.setLoginItemSettings.mockImplementation(() => {
      throw new Error('registry error');
    });
    const ok = setAutoStart(true);
    expect(ok).toBe(false);
    // 回滚为关闭态
    expect(mocks.config.setConfig).toHaveBeenLastCalledWith('auto_start', 'false');
  });

  it('setAutoStart：非 Windows 平台不写登录项', () => {
    setPlatform('darwin');
    expect(setAutoStart(true)).toBe(false);
    expect(mocks.app.setLoginItemSettings).not.toHaveBeenCalled();
  });

  it('setRunAsAdmin：仅持久化 run_as_admin', () => {
    expect(setRunAsAdmin(true)).toBe(true);
    expect(mocks.config.setConfig).toHaveBeenCalledWith('run_as_admin', 'true');
    expect(mocks.cp.spawn).not.toHaveBeenCalled(); // 提权在启动时处理，开关本身不触发 UAC
  });

  it('applyStartupOnLaunch：run_as_admin=true 且未提权时请求提权 relaunch', () => {
    mocks.config.getConfig.mockImplementation((k: string) => (k === 'run_as_admin' ? 'true' : null));
    mocks.cp.execFileSync.mockImplementation(() => {
      throw new Error('not admin'); // 非管理员
    });
    const triggered = applyStartupOnLaunch();
    expect(triggered).toBe(true);
    expect(mocks.cp.spawn).toHaveBeenCalledTimes(1);
    // 以 runas verb 请求 UAC
    expect(mocks.cp.spawn.mock.calls[0][0]).toBe('powershell.exe');
    expect(mocks.cp.spawn.mock.calls[0][2]).toMatchObject({ detached: true });
  });

  it('applyStartupOnLaunch：已提权时不重复请求', () => {
    mocks.config.getConfig.mockImplementation((k: string) => (k === 'run_as_admin' ? 'true' : null));
    mocks.cp.execFileSync.mockReturnValue(undefined); // 已是管理员
    expect(applyStartupOnLaunch()).toBe(false);
    expect(mocks.cp.spawn).not.toHaveBeenCalled();
  });

  it('applyStartupOnLaunch：run_as_admin 关闭时不触发提权', () => {
    mocks.config.getConfig.mockReturnValue(null);
    expect(applyStartupOnLaunch()).toBe(false);
    expect(mocks.cp.spawn).not.toHaveBeenCalled();
  });

  it('applyStartupOnLaunch：非 Windows 平台不触发提权', () => {
    setPlatform('linux');
    mocks.config.getConfig.mockImplementation((k: string) => (k === 'run_as_admin' ? 'true' : null));
    expect(applyStartupOnLaunch()).toBe(false);
    expect(mocks.cp.spawn).not.toHaveBeenCalled();
  });
});
