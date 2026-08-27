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

// 存储槽位名必须为纯净标识符，禁止路径分隔符/相对路径：
// 否则 name 含 `../` 时可穿越出 userData/store，落到任意目录。
const SAFE_NAME_RE = /^[\w-]+$/;

function isSafeName(name: unknown): name is string {
  return typeof name === 'string' && SAFE_NAME_RE.test(name);
}

export function loadStore(name: string): string | null {
  // 非法槽位名：不落盘也不抛错，视作不存在，与 ENOENT 语义一致（返回默认 null）
  if (!isSafeName(name)) return null;
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
  // 非法槽位名：阻断写入（抛错让调用方知晓），避免路径穿越
  if (!isSafeName(name)) {
    throw new Error(`store:save 非法 store 名（拒绝路径穿越）: ${JSON.stringify(name)}`);
  }
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
