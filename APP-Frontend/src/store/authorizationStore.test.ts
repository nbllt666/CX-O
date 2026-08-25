/**
 * authorizationStore 单测（Task 4：悬浮窗授权控制）。
 * 覆盖：授权门禁纯函数、授权持久化（setComputerControlAuth）、主动撤销、
 * 重启恢复（restore 读主进程权威值）、未授权时工具不可用。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  COMPUTER_CONTROL_AUTH_STORE_NAME,
  isComputerControlEnabled,
  useAuthorizationStore,
} from './authorizationStore';

function mockElectronApi(overrides: Partial<{
  getComputerControlAuth: boolean;
  infoRunning: boolean;
  infoAuthorized: boolean;
  setResult: boolean;
}> = {}) {
  const setComputerControlAuth = vi.fn().mockResolvedValue(overrides.setResult ?? true);
  const getComputerControlAuth = vi
    .fn()
    .mockResolvedValue(overrides.getComputerControlAuth ?? false);
  const getComputerControlInfo = vi.fn().mockResolvedValue({
    running: overrides.infoRunning ?? false,
    port: null,
    fingerprint: 'fp-test',
    authorized: overrides.infoAuthorized ?? false,
  });
  window.electronAPI = {
    storeLoad: vi.fn().mockResolvedValue(null),
    storeSave: vi.fn().mockResolvedValue(undefined),
    openManagementWindow: vi.fn().mockResolvedValue(undefined),
    toggleDanmakuWindow: vi.fn().mockResolvedValue(undefined),
    openPet: vi.fn().mockResolvedValue(undefined),
    closePet: vi.fn().mockResolvedValue(undefined),
    listPetWindows: vi.fn().mockResolvedValue([]),
    setDanmakuVisible: vi.fn().mockResolvedValue(undefined),
    onDanmakuVisibility: vi.fn().mockReturnValue(() => undefined),
    moveWindow: vi.fn().mockResolvedValue(undefined),
    setIgnoreMouseEvents: vi.fn().mockResolvedValue(undefined),
    setAlwaysOnTop: vi.fn().mockResolvedValue(undefined),
    setWindowSize: vi.fn().mockResolvedValue(undefined),
    openExternal: vi.fn().mockResolvedValue(undefined),
    getBackendUrl: vi.fn().mockResolvedValue(null),
    setBackendUrl: vi.fn().mockResolvedValue(undefined),
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
    getComputerControlAuth,
    setComputerControlAuth,
    getComputerControlInfo,
  };
  return { setComputerControlAuth, getComputerControlAuth, getComputerControlInfo };
}

function resetStore() {
  useAuthorizationStore.setState({
    authorized: false,
    running: false,
    fingerprint: null,
    loading: true,
  });
}

beforeEach(() => {
  resetStore();
  localStorage.clear();
});

afterEach(() => {
  delete window.electronAPI;
  localStorage.clear();
});

describe('isComputerControlEnabled（工具可执行门禁）', () => {
  it('未授权时工具不可用——即使 CXFC 已注册（running=true）', () => {
    expect(isComputerControlEnabled(false, true)).toBe(false);
  });

  it('服务未运行（注册失败）时工具不可用', () => {
    expect(isComputerControlEnabled(true, false)).toBe(false);
  });

  it('已授权且服务运行才可用', () => {
    expect(isComputerControlEnabled(true, true)).toBe(true);
  });
});

describe('authorize（授权持久化）', () => {
  it('调用 setComputerControlAuth(true) 并将 authorized 置 true', async () => {
    const { setComputerControlAuth } = mockElectronApi();
    const ok = await useAuthorizationStore.getState().authorize();

    expect(ok).toBe(true);
    expect(setComputerControlAuth).toHaveBeenCalledWith(true);
    expect(useAuthorizationStore.getState().authorized).toBe(true);
  });

  it('授权后本地镜像持久化到存储（重启恢复依据）', async () => {
    mockElectronApi();
    await useAuthorizationStore.getState().authorize();

    const raw = localStorage.getItem(COMPUTER_CONTROL_AUTH_STORE_NAME);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!) as { state: { authorized: boolean } };
    expect(parsed.state.authorized).toBe(true);
  });

  it('主进程写入失败时不置 authorized=true（不虚报授权）', async () => {
    mockElectronApi({ setResult: false });
    const ok = await useAuthorizationStore.getState().authorize();
    expect(ok).toBe(false);
    expect(useAuthorizationStore.getState().authorized).toBe(false);
  });
});

describe('revoke（主动撤销）', () => {
  it('调用 setComputerControlAuth(false) 并将 authorized 置 false', async () => {
    const { setComputerControlAuth } = mockElectronApi();
    useAuthorizationStore.setState({ authorized: true });
    const ok = await useAuthorizationStore.getState().revoke();

    expect(ok).toBe(true);
    expect(setComputerControlAuth).toHaveBeenCalledWith(false);
    expect(useAuthorizationStore.getState().authorized).toBe(false);
  });
});

describe('restore（重启恢复）', () => {
  it('浏览器模式（无 IPC）恢复后 loading=false 且保持本地镜像', async () => {
    // 不设置 window.electronAPI → isElectron() 为 false
    await useAuthorizationStore.getState().restore();
    const s = useAuthorizationStore.getState();
    expect(s.loading).toBe(false);
    expect(s.authorized).toBe(false);
  });

  it('启动时读主进程权威值覆盖本地镜像', async () => {
    const { getComputerControlAuth, getComputerControlInfo } = mockElectronApi({
      getComputerControlAuth: true,
      infoRunning: true,
      infoAuthorized: true,
    });
    // 本地镜像与主进程不一致（本地曾错误为未授权），restore 以主进程为准
    useAuthorizationStore.setState({ authorized: false });

    await useAuthorizationStore.getState().restore();

    expect(getComputerControlAuth).toHaveBeenCalled();
    expect(getComputerControlInfo).toHaveBeenCalled();
    const s = useAuthorizationStore.getState();
    expect(s.authorized).toBe(true);
    expect(s.running).toBe(true);
    expect(s.fingerprint).toBe('fp-test');
    expect(s.loading).toBe(false);
  });

  it('主进程返回未授权时 restore 将状态收敛为未授权', async () => {
    mockElectronApi({ getComputerControlAuth: false, infoRunning: true });
    useAuthorizationStore.setState({ authorized: true });

    await useAuthorizationStore.getState().restore();

    expect(useAuthorizationStore.getState().authorized).toBe(false);
  });
});
