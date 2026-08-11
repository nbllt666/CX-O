/**
 * zustand persist 存储工厂：Electron 下走 IPC 文件持久化，
 * 浏览器模式回退 localStorage。
 */
import { createJSONStorage } from 'zustand/middleware';
import { isElectron } from './isElectron';
import { electronStorage } from './electronStorage';

export function createStorage() {
  return createJSONStorage(() => (isElectron() ? electronStorage : localStorage));
}
