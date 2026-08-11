/**
 * 配置变更事件总线——模块级轻量订阅。
 *
 * useConfigReload 收到后端 /ws 的 `config_changed` 事件后调用 emitConfigChanged，
 * 各 UI 组件（ManagementLayout / SettingsPage 区块）经 subscribeConfigChanged 订阅，
 * 从而在配置热更新后即时刷新 limits 与本地表单，无需耦合 WS 连接生命周期。
 */

export interface ConfigChangedPayload {
  section: string;
  requiresRestart: boolean;
}

type Listener = (payload: ConfigChangedPayload) => void;

const listeners = new Set<Listener>();

/** 订阅配置变更事件；返回取消订阅函数 */
export function subscribeConfigChanged(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** 广播配置变更事件到所有订阅者 */
export function emitConfigChanged(payload: ConfigChangedPayload): void {
  for (const listener of listeners) {
    try {
      listener(payload);
    } catch (e) {
      console.error('[configEvents] listener error:', e);
    }
  }
}