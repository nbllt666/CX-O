/**
 * 本地配置持久化模块
 * ============================================================================
 * 以 JSON 文件（data/config.json）持久化适配器配置，替代原宿主应用 userData
 * 的配置存储。要点：
 *  - auto_init：加载时自动补全缺失/非法键为默认值；
 *  - 防并发截断：Node 单线程 + 同步 fs，写路径在临界区内完成，先写临时文件
 *    再原子 rename 替换，杜绝写入中途异常导致的 JSON 截断；
 *  - 提供 getConfig / setConfig(partial) / getAll 三个入口。
 * ============================================================================
 */
import * as fs from 'node:fs';
import { configPath, dataDir, ensureDataDirs } from './paths';

/** 适配器配置结构（与 data/config.json 一一对应） */
export interface AdapterConfig {
  /** Python 可执行路径；空则用 PATH 中的 python */
  python: string;
  /** neko 源码目录（含 config/plugin/utils 包） */
  sourceDir: string;
  /** 插件服务器端口 */
  port: number;
  /** CX-O 后端基址（CXFC 注册/心跳目标） */
  backendUrl: string;
  /** 控制面 HTTP 端口（后续任务使用） */
  controlPort: number;
  /** 是否随适配器启动自动拉起 neko 运行时 */
  autoStart: boolean;
}

export const DEFAULT_CONFIG: AdapterConfig = {
  python: 'python',
  sourceDir: 'C:\\N.E.K.O-main',
  port: 48916,
  backendUrl: 'http://127.0.0.1:8000',
  controlPort: 48920,
  autoStart: false,
};

type ConfigShape = Partial<Record<keyof AdapterConfig, unknown>>;

/** 写入临界区标记：Node 单线程内同步写不会被打断，标记仅用于防御性互斥 */
let writing = false;

function readConfigFile(): ConfigShape {
  try {
    const parsed: unknown = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
    if (typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)) {
      return parsed as ConfigShape;
    }
    return {};
  } catch {
    // 文件不存在/损坏：按空配置处理，随后由合并逻辑回填默认值（auto_init）
    return {};
  }
}

function writeConfigFile(data: ConfigShape): void {
  if (writing) {
    throw new Error('配置写入冲突：上一次写入尚未完成');
  }
  writing = true;
  try {
    ensureDataDirs();
    // 先写临时文件再原子替换，防止写入中途进程异常导致 config.json 截断
    const tmpPath = `${configPath}.tmp`;
    fs.writeFileSync(tmpPath, `${JSON.stringify(data, null, 2)}\n`, 'utf-8');
    fs.renameSync(tmpPath, configPath);
  } finally {
    writing = false;
  }
}

/**
 * 合并存储值与默认值（auto_init）。
 * 空值/类型不符的键回填默认值，语义与原宿主配置「空字符串回落默认」一致：
 * - python/sourceDir/backendUrl：非空字符串才生效；
 * - port/controlPort：Number() 为 0 或 NaN 时回落默认（与原 `Number(x) || default` 等价）；
 * - autoStart：严格等于 true 才生效。
 */
function mergeWithDefaults(stored: ConfigShape): AdapterConfig {
  const merged: AdapterConfig = { ...DEFAULT_CONFIG };
  if (typeof stored.python === 'string' && stored.python) merged.python = stored.python;
  if (typeof stored.sourceDir === 'string' && stored.sourceDir) merged.sourceDir = stored.sourceDir;
  if (typeof stored.backendUrl === 'string' && stored.backendUrl) merged.backendUrl = stored.backendUrl;
  const storedPort = Number(stored.port);
  if (Number.isFinite(storedPort) && storedPort > 0) merged.port = storedPort;
  const storedControlPort = Number(stored.controlPort);
  if (Number.isFinite(storedControlPort) && storedControlPort > 0) merged.controlPort = storedControlPort;
  if (stored.autoStart === true) merged.autoStart = true;
  return merged;
}

/** 读取全部配置（缺失键已按默认值补全） */
export function getAll(): AdapterConfig {
  return mergeWithDefaults(readConfigFile());
}

/** 读取单个配置项（含默认值补全） */
export function getConfig<K extends keyof AdapterConfig>(key: K): AdapterConfig[K] {
  return getAll()[key];
}

/** 归一化单个写入值（trim / 端口取整下限 0 / 布尔化），非法值保持原样交由合并回落 */
function normalizeValue<K extends keyof AdapterConfig>(key: K, value: AdapterConfig[K]): unknown {
  if (key === 'python' || key === 'sourceDir' || key === 'backendUrl') {
    return typeof value === 'string' ? value.trim() : value;
  }
  if (key === 'port' || key === 'controlPort') {
    return typeof value === 'number' ? Math.max(0, Math.floor(value)) : value;
  }
  if (key === 'autoStart') {
    return !!value;
  }
  return value;
}

/**
 * 部分更新配置并持久化，返回更新后的完整配置。
 * 仅写入传入的键，未传入的键保持磁盘原值。
 */
export function setConfig(partial: Partial<AdapterConfig>): AdapterConfig {
  const current = readConfigFile();
  const next: ConfigShape = { ...current };
  for (const key of Object.keys(partial) as (keyof AdapterConfig)[]) {
    const value = partial[key];
    if (value !== undefined) {
      next[key] = normalizeValue(key, value as never);
    }
  }
  writeConfigFile(next);
  return getAll();
}
