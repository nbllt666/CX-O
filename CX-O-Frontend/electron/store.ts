import { app } from 'electron';
import * as fs from 'node:fs';
import * as path from 'node:path';

function getStoreDir(): string {
  const userData = app.getPath('userData');
  const storeDir = path.join(userData, 'store');
  if (!fs.existsSync(storeDir)) {
    fs.mkdirSync(storeDir, { recursive: true });
  }
  return storeDir;
}

export function loadStore(name: string): string | null {
  const filePath = path.join(getStoreDir(), `${name}.json`);
  try {
    return fs.readFileSync(filePath, 'utf-8');
  } catch (error: unknown) {
    if ((error as { code?: string }).code === 'ENOENT') {
      return null;
    }
    throw error;
  }
}

export function saveStore(name: string, data: string): void {
  const filePath = path.join(getStoreDir(), `${name}.json`);
  fs.writeFileSync(filePath, data, 'utf-8');
}
