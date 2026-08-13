/**
 * Electron 文件持久化存储适配层（zustand StateStorage）。
 *
 * 行为口径对齐 CX-O-Frontend src/lib/electronStorage.ts：
 * - 内存 cache 保证 zustand persist 的同步读写；
 * - setItem 同时写 localStorage（备份）与 IPC storeSave（userData/store/{name}.json）；
 * - initElectronStorage() 在应用渲染前调用：预载各 store 数据、
 *   迁移 localStorage 旧数据、同步 app-config 中的后端地址类配置。
 *
 * 与参考实现的差异：
 * - store 命名采用 cxo-pet-* 前缀（本工程独立命名空间）；
 * - 配置同步键复用 api/base.ts 的 STORAGE_KEYS（cxo-backend-url 等）。
 */
import { type StateStorage } from 'zustand/middleware';
import { isElectron } from './isElectron';
import { STORAGE_KEYS } from '../api/base';

// 同步访问的内存缓存
const cache = new Map<string, string>();

// 需要预载/迁移的 zustand store 名称
// 注：cxo-pet-danmaku 与 src/store/danmakuStore.ts 的 DANMAKU_STORE_NAME 保持一致
// （此处不 import 以避免 lib → store 反向依赖）
const STORE_NAMES = [
  'cxo-pet-theme',
  'cxo-pet-settings',
  'cxo-pet-chat',
  'cxo-pet-danmaku',
  'cxo-pet-computer-control-auth',
];

// 需要与 Electron 主进程 app-config 双向同步的配置键
const CONFIG_SYNC_KEYS: string[] = [
  STORAGE_KEYS.backendUrl,
  STORAGE_KEYS.wsUrl,
  STORAGE_KEYS.controlUrl,
  STORAGE_KEYS.voiceWsUrl,
  STORAGE_KEYS.token,
  STORAGE_KEYS.offlineTimeout,
];

const CONFIG_STORE_NAME = 'app-config';

/**
 * 初始化 Electron 存储缓存：预载 IPC 数据并迁移 localStorage 旧数据。
 * 必须在 Electron 模式下应用渲染前 await 调用。
 */
export async function initElectronStorage(): Promise<void> {
  if (!isElectron()) return;

  // 预载 zustand store 数据
  for (const name of STORE_NAMES) {
    try {
      const data = await window.electronAPI!.storeLoad(name);
      if (data) cache.set(name, data);
    } catch {
      // IPC 读取失败则回退 localStorage
    }
  }

  // 迁移：IPC 无数据但 localStorage 有 → 写入 IPC
  for (const name of STORE_NAMES) {
    if (!cache.has(name)) {
      const localData = localStorage.getItem(name);
      if (localData) {
        cache.set(name, localData);
        window.electronAPI!.storeSave(name, localData).catch(() => {});
      }
    }
  }

  // 主进程 app-config → localStorage（仅补缺，不覆盖本地显式值）
  try {
    const raw = await window.electronAPI!.storeLoad(CONFIG_STORE_NAME);
    if (raw) {
      const data = JSON.parse(raw) as Record<string, string>;
      for (const key of CONFIG_SYNC_KEYS) {
        if (data[key] && !localStorage.getItem(key)) {
          localStorage.setItem(key, data[key]);
        }
      }
    }
  } catch {
    // 静默忽略
  }

  // 当前 localStorage 配置 → 主进程 app-config
  await syncConfigToElectron();
}

/** 将当前 localStorage 中的配置键持久化到 Electron 主进程 */
export async function syncConfigToElectron(): Promise<void> {
  if (!isElectron()) return;

  try {
    const data: Record<string, string> = {};
    for (const key of CONFIG_SYNC_KEYS) {
      const value = localStorage.getItem(key);
      if (value) {
        data[key] = value;
      }
    }
    await window.electronAPI!.storeSave(CONFIG_STORE_NAME, JSON.stringify(data));
  } catch {
    // 静默忽略
  }
}

export const electronStorage: StateStorage = {
  getItem(name: string): string | null {
    return cache.get(name) ?? localStorage.getItem(name);
  },

  setItem(name: string, value: string): void {
    cache.set(name, value);
    localStorage.setItem(name, value); // 备份
    if (isElectron()) {
      window.electronAPI!.storeSave(name, value).catch(() => {});
    }
  },

  removeItem(name: string): void {
    cache.delete(name);
    localStorage.removeItem(name);
    if (isElectron()) {
      window.electronAPI!.storeSave(name, '').catch(() => {});
    }
  },
};
