import { createJSONStorage } from 'zustand/middleware';
import { isElectron } from './isElectron';
import { electronStorage } from './electronStorage';

export function createStorage() {
  return createJSONStorage(() => isElectron() ? electronStorage : localStorage);
}
