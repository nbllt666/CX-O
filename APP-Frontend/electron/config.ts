/**
 * 应用级配置读写（userData/config.json）
 * 仅存放后端地址等少量键值；业务数据请走 store.ts
 */
import { app } from 'electron';
import * as fs from 'node:fs';
import * as path from 'node:path';

function getConfigPath(): string {
  return path.join(app.getPath('userData'), 'config.json');
}

function readConfig(): Record<string, string> {
  const configPath = getConfigPath();
  let data: string;
  try {
    data = fs.readFileSync(configPath, 'utf-8');
  } catch (error: unknown) {
    if ((error as { code?: string }).code === 'ENOENT') {
      return {};
    }
    throw error;
  }
  try {
    return JSON.parse(data) as Record<string, string>;
  } catch (error: unknown) {
    // M-G 修复：损坏 JSON（如崩溃写半截）不再 rethrow——否则所有网络回调持续抛异常。
    // 记 warning 后返回 {} 触发默认配置重建（下次 setConfig 会覆盖重写）。
    console.warn(`[config] 配置文件损坏，回退默认配置并将在下次写入时重建 ${configPath}:`, error);
    return {};
  }
}

function writeConfig(config: Record<string, string>): void {
  const configPath = getConfigPath();
  // M-G 修复：原子替换——先写临时文件再 rename，避免进程中断留下半截 config.json
  const tmpPath = `${configPath}.tmp`;
  try {
    fs.writeFileSync(tmpPath, JSON.stringify(config, null, 2), 'utf-8');
    try {
      fs.renameSync(tmpPath, configPath);
    } catch {
      // Windows 上目标被占用/存在时 rename 可能报 EPERM/EEXIST：
      // 先删除目标再 rename（极小窗口非原子，但崩溃最坏回到「缺配置→重建默认」，可接受）
      try {
        fs.rmSync(configPath, { force: true });
      } catch {
        /* 目标不存在时忽略 */
      }
      fs.renameSync(tmpPath, configPath);
    }
  } catch (error: unknown) {
    console.error(`[config] 写入失败 ${configPath}:`, error);
    try {
      fs.rmSync(tmpPath, { force: true });
    } catch {
      /* 清理失败忽略 */
    }
  }
}

export function getConfig(key: string): string | null {
  const config = readConfig();
  return config[key] ?? null;
}

export function setConfig(key: string, value: string): void {
  const config = readConfig();
  config[key] = value;
  writeConfig(config);
}
