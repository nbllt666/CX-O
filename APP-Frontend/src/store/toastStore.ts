/**
 * 全局轻量 toast 状态（D9）：cluster_event（仅切换/故障类主题）与
 * autonomy_cost_alert 由 useWebSocket 写入本 store，GlobalToast 组件负责展示。
 * 不引第三方库——极简有界数组（最多 5 条，FIFO 淘汰），过期由组件侧定时清扫。
 */
import { create } from 'zustand';

export type GlobalToastKind = 'cluster' | 'cost';

export interface GlobalToastItem {
  id: number;
  kind: GlobalToastKind;
  /** cluster 事件主题（如 cluster.failover_started），渲染侧据此取文案 */
  topic?: string;
  /** 事件数据：cluster 为后端事件体（{topic,node_id,data,...}），cost 为 {usage_ratio,daily_used,limit,date} */
  data?: Record<string, unknown>;
  /** 前台打点的过期时间戳（与 ChatPage alarm toast 同口径：组件定时清扫） */
  expireAt: number;
}

/** 展示上限：防事件风暴刷屏，超出丢弃最旧 */
const MAX_TOASTS = 5;
/** 单条存活时长（ms） */
const TOAST_TTL_MS = 6000;

let nextToastId = 1;

interface ToastState {
  toasts: GlobalToastItem[];
  push: (toast: Omit<GlobalToastItem, 'id' | 'expireAt'>) => void;
  dismiss: (id: number) => void;
}

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  push: (toast) =>
    set((state) => {
      const item: GlobalToastItem = {
        ...toast,
        id: nextToastId++,
        expireAt: Date.now() + TOAST_TTL_MS,
      };
      const next = [...state.toasts, item];
      return { toasts: next.length > MAX_TOASTS ? next.slice(next.length - MAX_TOASTS) : next };
    }),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((item) => item.id !== id) })),
}));
