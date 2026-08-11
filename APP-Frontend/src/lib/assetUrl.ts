/**
 * 资产 URL 归一化。
 *
 * 生产模式 Electron 经 loadFile(dist/index.html) 以 file:// 加载页面，
 * 以 '/' 开头的路径会被解析到文件系统根（file:///models/x.vrm）导致加载失败；
 * 转为相对路径后相对 dist/index.html 解析，dev(http) 与生产(file) 均正确。
 */
export function resolveAssetUrl(p: string): string {
  if (
    p.startsWith('/') &&
    typeof window !== 'undefined' &&
    window.location.protocol === 'file:'
  ) {
    return `.${p}`;
  }
  return p;
}
