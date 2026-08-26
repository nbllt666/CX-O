/**
 * 渲染层持久化存储（userData/store/<name>.json）
 * 供 zustand persist 等以 JSON 字符串形式整体读写
 */
import { app } from 'electron';
import * as fs from 'node:fs';
import * as path from 'node:path';

function getStoreDir(): string {
  const storeDir = path.join(app.getPath('userData'), 'store');
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
  if (data === '') {
    // F4: removeItem 语义——渲染层 removeItem 调用 storeSave(name, '')，
    // 空内容表示删除文件；否则残留旧数据会在下次预载时回灌，覆盖删除意图。
    try {
      fs.unlinkSync(filePath);
    } catch (error: unknown) {
      if ((error as { code?: string }).code !== 'ENOENT') {
        throw error;
      }
    }
    return;
  }
  fs.writeFileSync(filePath, data, 'utf-8');
}
