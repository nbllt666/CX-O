export function isElectron(): boolean {
  return typeof window !== 'undefined' && !!window.electronAPI;
}
