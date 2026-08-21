/**
 * VRM 模型加载源解析。
 *
 * settingsStore.vrm.modelPath 的三种取值形态：
 * - '/models/CX-OPEN.vrm'：打包内默认资源（经 resolveAssetUrl 归一化，dev http 与生产 file 均可用）
 * - 本地绝对路径（Electron 用户选择的 .vrm，如 C:\...\xxx.vrm / \\server\...）
 * - 'blob:...'：浏览器模式用户上传的临时 URL（不持久化，刷新即失效）
 *
 * 本地路径在 Electron 下经主进程 IPC（model:read-file）读取为字节流并生成 blob URL；
 * 其余形态直接返回可加载 URL。resolveVrmModelUrl 返回的 blob URL 需在模型卸载时 revoke。
 */
import { isElectron } from './isElectron';
import { resolveAssetUrl } from './assetUrl';

/** 打包内默认 VRM 模型路径（settingsStore 默认值 / 设置页"恢复默认"目标） */
export const DEFAULT_VRM_MODEL_PATH = '/models/CX-OPEN.vrm';

/** 判断是否为本地文件系统路径（Windows 盘符 / UNC 前缀） */
export function isLocalModelPath(p: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith('\\\\');
}

export interface ResolvedModelSource {
  /** 可直接交给 GLTFLoader 加载的 URL */
  url: string;
  /** 释放临时 blob URL；非本地读取生成的源为 noop */
  revoke: () => void;
}

/** 解析模型路径 → 可加载 URL + 资源释放函数。失败抛出带 MODEL_ 前缀的错误消息 */
export async function resolveVrmModelUrl(modelPath: string): Promise<ResolvedModelSource> {
  if (modelPath.startsWith('blob:')) {
    return { url: modelPath, revoke: () => undefined };
  }

  if (isLocalModelPath(modelPath)) {
    if (isElectron() && window.electronAPI?.readModelFile) {
      const data = await window.electronAPI.readModelFile(modelPath);
      if (!data) {
        throw new Error(`MODEL_READ_FAILED: ${modelPath}`);
      }
      const blob = new Blob([data], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      return {
        url,
        revoke: () => URL.revokeObjectURL(url),
      };
    }
    throw new Error(`LOCAL_MODEL_UNSUPPORTED: ${modelPath}`);
  }

  // 打包内资源 / http(s) 地址：直接走原 URL 归一化
  return { url: resolveAssetUrl(modelPath), revoke: () => undefined };
}

/** 选择模型文件（Electron 走系统对话框；浏览器回退隐藏 file input）。返回选中的本地路径或 null */
export async function pickModelFile(): Promise<string | null> {
  if (isElectron() && window.electronAPI?.pickModelFile) {
    const result = await window.electronAPI.pickModelFile();
    if (result.canceled || !result.path) return null;
    return result.path;
  }
  return null;
}
