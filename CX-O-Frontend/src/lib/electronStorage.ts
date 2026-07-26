import { type StateStorage } from 'zustand/middleware';
import { isElectron } from './isElectron';

// In-memory cache for synchronous access
const cache = new Map<string, string>();

// Known zustand store names for pre-loading and migration
const STORE_NAMES = ['cxhms-theme', 'cxhms-settings', 'cxhms-chat-storage'];

// App config keys to sync to Electron main process
const CONFIG_SYNC_KEYS = [
  'cxhms-backend-url',
  'cxhms-ws-url',
  'cxhms-control-url',
  'cxhms-voicews-url',
  'cxhms-token',
  'cxhms-offline-timeout',
];

const CONFIG_STORE_NAME = 'app-config';

/**
 * Initialize the electron storage cache by pre-loading data from IPC
 * and migrating any existing localStorage data.
 * Must be called before the app renders when running in Electron.
 */
export async function initElectronStorage(): Promise<void> {
  if (!isElectron()) return;

  // Pre-load zustand store data from IPC
  for (const name of STORE_NAMES) {
    try {
      const data = await window.electronAPI!.storeLoad(name);
      if (data) cache.set(name, data);
    } catch {
      // IPC load failed, will fall back to localStorage
    }
  }

  // Migrate zustand stores from localStorage: if IPC has no data but localStorage does
  for (const name of STORE_NAMES) {
    if (!cache.has(name)) {
      const localData = localStorage.getItem(name);
      if (localData) {
        cache.set(name, localData);
        window.electronAPI!.storeSave(name, localData).catch(() => {});
      }
    }
  }

  // Sync app config keys from Electron main process to localStorage
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
    // Silently ignore
  }

  // Persist current localStorage config values to Electron main process
  await syncConfigToElectron();
}

/**
 * Persist current localStorage config values to Electron main process.
 */
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
    // Silently ignore
  }
}

export const electronStorage: StateStorage = {
  getItem(name: string): string | null {
    return cache.get(name) ?? localStorage.getItem(name);
  },

  setItem(name: string, value: string): void {
    cache.set(name, value);
    localStorage.setItem(name, value); // backup
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
