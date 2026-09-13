/**
 * 路径解析模块
 * ============================================================================
 * 统一解析适配器项目根目录，全项目禁止直接书写跨层相对路径（避免相对路径歧义）。
 * 解析方式：本文件编译后位于 dist/shared/ 下、开发态位于 src/shared/ 下，
 * 两种情况下 __dirname 向上两级均为项目根（CXO-NekoAdapter）。
 * ============================================================================
 */
import * as fs from 'node:fs';
import * as path from 'node:path';

/** 适配器项目根目录（src 上两级） */
export const projectRoot = path.resolve(__dirname, '..', '..');

/**
 * 数据目录覆盖环境变量：设置后所有持久化数据（config.json / certs）改存该目录。
 * 用于测试与验证的隔离（如 vitest / curl 验证用临时目录），未设置时行为不变。
 * 注意：本模块加载时读取一次并固化，因此必须在首次 import 前设置。
 */
export const DATA_DIR_OVERRIDE_ENV = 'CXO_NEKO_ADAPTER_DATA_DIR';

/** 数据目录（配置、证书等持久化数据均在此）；环境变量 CXO_NEKO_ADAPTER_DATA_DIR 优先 */
export const dataDir = process.env[DATA_DIR_OVERRIDE_ENV]
  ? path.resolve(process.env[DATA_DIR_OVERRIDE_ENV])
  : path.join(projectRoot, 'data');

/** 证书根目录（各组件证书以其下子目录隔离，如 neko-toolBridge） */
export const certsDir = path.join(dataDir, 'certs');

/** 配置文件路径 */
export const configPath = path.join(dataDir, 'config.json');

/** 确保 data 目录结构存在（幂等；模块加载时即保证可用） */
export function ensureDataDirs(): void {
  fs.mkdirSync(certsDir, { recursive: true });
}

// 模块加载时立即确保目录存在
ensureDataDirs();
