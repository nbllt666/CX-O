/**
 * 桌面应用配置持久化（连接面板用）。
 *
 * - 持久化位置：Electron userData/modelstation-desktop.json（由主进程传入绝对路径）；
 * - 纯函数 normalizeAppConfig 供浏览器 localStorage 形态复用；
 * - 浏览器（非 Electron）环境下由渲染层退回 localStorage，不经过本模块文件 IO。
 */
import * as fs from "node:fs";
import * as path from "node:path";

import { DEFAULT_BACKEND_BASE_URL } from "./backend";

export const APP_CONFIG_FILENAME = "modelstation-desktop.json";

export interface AppConfig {
  /** 后端连接地址（默认 http://127.0.0.1:8300） */
  backendBaseUrl: string;
  /** 可写数据根（默认 %LOCALAPPDATA%\\CXO-ModelStation\\data） */
  dataRoot: string;
  /** 前端本地站点首选端口（默认 3300，实际端口可能顺延） */
  preferredFrontendPort: number;
}

export function defaultAppConfig(dataRoot: string, preferredFrontendPort = 3300): AppConfig {
  return {
    backendBaseUrl: DEFAULT_BACKEND_BASE_URL,
    dataRoot,
    preferredFrontendPort,
  };
}

function normalizeBaseUrl(value: unknown, fallback: string): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw) return fallback;
  try {
    const url = new URL(raw);
    if (url.protocol !== "http:" && url.protocol !== "https:") return fallback;
    return raw.replace(/\/+$/, "");
  } catch {
    return fallback;
  }
}

function normalizePort(value: unknown, fallback: number): number {
  const num = Number(value);
  if (!Number.isInteger(num) || num < 0 || num > 65535) return fallback;
  return num;
}

/** 归一化外部输入（含越界/非法回退），保证面板写入的配置始终可用 */
export function normalizeAppConfig(raw: unknown, defaults: AppConfig): AppConfig {
  const data = (raw ?? {}) as Partial<Record<keyof AppConfig, unknown>>;
  const dataRoot =
    typeof data.dataRoot === "string" && data.dataRoot.trim()
      ? path.resolve(data.dataRoot.trim())
      : defaults.dataRoot;
  return {
    backendBaseUrl: normalizeBaseUrl(data.backendBaseUrl, defaults.backendBaseUrl),
    dataRoot,
    preferredFrontendPort: normalizePort(
      data.preferredFrontendPort,
      defaults.preferredFrontendPort,
    ),
  };
}

export function configFilePath(userDataDir: string): string {
  return path.join(userDataDir, APP_CONFIG_FILENAME);
}

/** 读取配置：文件缺失/损坏一律回退默认值（不抛异常） */
export function readAppConfig(
  filePath: string,
  defaults: AppConfig,
  fsImpl: Pick<typeof fs, "readFileSync"> = fs,
): AppConfig {
  try {
    const raw = fsImpl.readFileSync(filePath, "utf8");
    return normalizeAppConfig(JSON.parse(raw), defaults);
  } catch {
    return defaults;
  }
}

/** 写入配置（原子性：先写临时文件再 rename） */
export function writeAppConfig(
  filePath: string,
  config: AppConfig,
  fsImpl: Pick<typeof fs, "mkdirSync" | "writeFileSync" | "renameSync"> = fs,
): AppConfig {
  fsImpl.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.tmp`;
  fsImpl.writeFileSync(tmpPath, JSON.stringify(config, null, 2), "utf8");
  fsImpl.renameSync(tmpPath, filePath);
  return config;
}

/** 合并补丁并落盘 */
export function patchAppConfig(
  filePath: string,
  defaults: AppConfig,
  patch: unknown,
  fsImpl?: Pick<typeof fs, "readFileSync" | "mkdirSync" | "writeFileSync" | "renameSync">,
): AppConfig {
  const current = readAppConfig(filePath, defaults, (fsImpl ?? fs) as Pick<typeof fs, "readFileSync">);
  const merged = normalizeAppConfig({ ...current, ...(patch as object) }, defaults);
  return writeAppConfig(filePath, merged, (fsImpl ?? fs) as Pick<
    typeof fs,
    "mkdirSync" | "writeFileSync" | "renameSync"
  >);
}