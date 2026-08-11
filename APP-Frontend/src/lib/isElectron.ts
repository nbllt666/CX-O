/**
 * 运行环境检测：preload 通过 contextBridge 暴露 window.electronAPI，
 * 浏览器模式下为 undefined。
 */
export function isElectron(): boolean {
  return typeof window !== 'undefined' && !!window.electronAPI;
}
