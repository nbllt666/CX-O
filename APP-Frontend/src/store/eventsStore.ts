/**
 * 后端广播事件存档（D9）：skill_triggered / plugin_status_changed / system.wake
 * 由 useWebSocket 写入本 store——只入 store 不做 UI，供后续功能查询。
 * 有界数组：最多保留最近 50 条（FIFO 淘汰），防止长期运行内存无界增长。
 */
import { create } from 'zustand';

export interface StoredEvent {
  id: number;
  /** 后端广播事件 type（如 skill_triggered） */
  type: string;
  /** 事件原始 data 载荷 */
  data: unknown;
  /** 前台接收时间戳 */
  receivedAt: number;
}

/** 存档上限 */
const MAX_EVENTS = 50;

let nextEventId = 1;

interface EventsState {
  events: StoredEvent[];
  push: (type: string, data: unknown) => void;
  clear: () => void;
}

export const useEventsStore = create<EventsState>()((set) => ({
  events: [],
  push: (type, data) =>
    set((state) => {
      const next: StoredEvent[] = [
        ...state.events,
        { id: nextEventId++, type, data, receivedAt: Date.now() },
      ];
      return { events: next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next };
    }),
  clear: () => set({ events: [] }),
}));
