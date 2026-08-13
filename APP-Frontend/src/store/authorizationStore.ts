/**
 * 电脑控制授权存储（Task 4：悬浮窗授权控制）。
 *
 * 职责边界（对齐 Task 2 的主进程 AuthorizationStore）：
 * - 渲染层只能读写授权开关，不能直接执行本机控制（电脑控制工具在主进程侧执行）；
 * - 授权为永久授权：authorize 经 window.electronAPI.setComputerControlAuth(true) 写入主进程持久化；
 * - 主动撤销：revoke 经 setComputerControlAuth(false) 关闭，永不自动恢复；
 * - 重启恢复：restore 启动时读 getComputerControlAuth 与 getComputerControlInfo，
 *   以主进程为权威真值覆盖本地的 zustand 持久化镜像；
 * - 门禁：isComputerControlEnabled = 已授权 && 服务运行。未授权时即使 CXFC 已注册工具
 *   （running=true）也不允许控制电脑；注册失败（running=false）时同样不可用，
 *   保证注册失败/授权失效时悬浮窗状态一致。
 *
 * persist 落 createStorage()（Electron 落 userData 文件 + localStorage 备份，
 * 浏览器回退 localStorage）仅作渲染层快速镜像；权威授权状态以主进程为准。
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { createStorage } from '../lib/createStorage';
import { isElectron } from '../lib/isElectron';

export const COMPUTER_CONTROL_AUTH_STORE_NAME = 'cxo-pet-computer-control-auth';

/** getComputerControlInfo 返回的电脑控制插件运行信息（对齐 electron.d.ts） */
export interface ComputerControlInfo {
  running: boolean;
  port: number | null;
  fingerprint: string | null;
  authorized: boolean;
}

/**
 * 电脑控制工具可执行门禁：
 * - 未授权（authorized=false）时，即使 CXFC 已注册工具也不可用 —— 授权优先于注册成功状态；
 * - 服务未运行（running=false，注册失败/服务退出）时同样不可用，状态保持不虚高。
 */
export function isComputerControlEnabled(authorized: boolean, running: boolean): boolean {
  return authorized && running;
}

interface AuthorizationState {
  /** 用户是否已授权电脑控制（权威真值在主进程，此处为渲染层镜像） */
  authorized: boolean;
  /** 电脑控制插件服务是否运行中（注册失败/服务退出时为 false） */
  running: boolean;
  fingerprint: string | null;
  /** 启动恢复进行中（避免闪烁出错误的未授权状态） */
  loading: boolean;
  /** 启动时从主进程恢复授权状态与运行信息（重启恢复入口） */
  restore: () => Promise<void>;
  /** 授权：写主进程并永久保存；写入成功才置 authorized=true */
  authorize: () => Promise<boolean>;
  /** 撤销：写主进程并永久关闭；主动撤销后永不自动恢复 */
  revoke: () => Promise<boolean>;
}

export const useAuthorizationStore = create<AuthorizationState>()(
  persist(
    (set) => ({
      authorized: false,
      running: false,
      fingerprint: null,
      loading: true,

      restore: async () => {
        // 浏览器模式无 IPC：直接结束恢复，维持本地持久化镜像
        if (!isElectron() || !window.electronAPI) {
          set({ loading: false });
          return;
        }
        try {
          const [auth, info] = await Promise.all([
            window.electronAPI.getComputerControlAuth(),
            window.electronAPI.getComputerControlInfo(),
          ]);
          set({
            authorized: auth,
            running: info.running,
            fingerprint: info.fingerprint,
            loading: false,
          });
        } catch {
          // 主进程不可达时保持当前镜像，不抛出
          set({ loading: false });
        }
      },

      authorize: async () => {
        const api = window.electronAPI;
        let persisted = true;
        if (api) {
          try {
            persisted = await api.setComputerControlAuth(true);
          } catch {
            persisted = false;
          }
        }
        set({ authorized: persisted });
        return persisted;
      },

      revoke: async () => {
        const api = window.electronAPI;
        if (api) {
          try {
            await api.setComputerControlAuth(false);
          } catch {
            // 主进程不可达时也关闭本地授权，避免授权残留
          }
        }
        set({ authorized: false });
        return true;
      },
    }),
    {
      name: COMPUTER_CONTROL_AUTH_STORE_NAME,
      storage: createStorage(),
      // 仅镜像授权开关（running/fingerprint 由主进程实时返回，不持久化）
      partialize: (state) => ({ authorized: state.authorized }),
      merge: (persisted, current) => {
        const p = (persisted as Partial<AuthorizationState>) || {};
        return {
          ...current,
          authorized: typeof p.authorized === 'boolean' ? p.authorized : current.authorized,
        };
      },
    },
  ),
);
