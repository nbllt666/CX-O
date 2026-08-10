/**
 * 弹幕流纯逻辑层（无 React 依赖，可单测）。
 *
 * 状态机：
 * - append：弹幕直接入渲染队列（上限 MAX_ITEMS，先进先出截断）
 * - buffer：暂停滚动时弹幕进缓存队列（上限 MAX_PENDING），不触发渲染滚动
 * - flush：恢复滚动时把缓存并入渲染队列尾部
 * - clear：清屏，渲染队列与缓存队列同时清空
 */

export interface DanmakuItem {
  id: string;
  /** 昵称；空串由展示层兜底为 i18n 匿名文案 */
  username: string;
  content: string;
  /** 弹幕颜色（WS 下发，可选）；缺省时展示层用主题 accent 色 */
  color?: string;
  /** 接收时间戳（ms epoch） */
  ts: number;
}

export interface DanmakuFeedState {
  /** 已入列、参与渲染的弹幕 */
  items: DanmakuItem[];
  /** 暂停期缓存的弹幕（恢复后并入 items） */
  pending: DanmakuItem[];
}

export type DanmakuFeedAction =
  | { type: 'append'; item: DanmakuItem }
  | { type: 'buffer'; item: DanmakuItem }
  | { type: 'flush' }
  | { type: 'clear' };

/** 渲染队列上限：超出丢弃最旧，控制透明窗体重绘成本 */
export const MAX_ITEMS = 200;
/** 缓存队列上限：长时间暂停时防内存膨胀 */
export const MAX_PENDING = 500;

export const initialDanmakuFeedState: DanmakuFeedState = { items: [], pending: [] };

export function danmakuFeedReducer(
  state: DanmakuFeedState,
  action: DanmakuFeedAction,
): DanmakuFeedState {
  switch (action.type) {
    case 'append':
      return { ...state, items: [...state.items, action.item].slice(-MAX_ITEMS) };
    case 'buffer':
      return { ...state, pending: [...state.pending, action.item].slice(-MAX_PENDING) };
    case 'flush':
      if (state.pending.length === 0) return state;
      return {
        items: [...state.items, ...state.pending].slice(-MAX_ITEMS),
        pending: [],
      };
    case 'clear':
      return initialDanmakuFeedState;
  }
}

/** WS 弹幕数据的最小入参形状（与 useLiveWebSocket 的 LiveDanmakuData 兼容） */
export interface RawDanmakuData {
  id?: string;
  content?: string;
  username?: string;
  color?: string;
}

/**
 * 将 WS 下发的原始弹幕规整为 DanmakuItem。
 * - content 去空白；空内容（含纯空白）返回 null，调用方丢弃
 * - id 缺省兜底 `dm-{now}-{seq}`（seq 由调用方单调递增，防同毫秒碰撞）
 * - username 仅做 trim，空串留给展示层按 i18n 兜底
 */
export function toDanmakuItem(
  data: RawDanmakuData,
  now: number,
  seq: number,
): DanmakuItem | null {
  const content = (data.content ?? '').trim();
  if (!content) return null;
  return {
    id: data.id || `dm-${now}-${seq}`,
    username: (data.username ?? '').trim(),
    content,
    color: data.color || undefined,
    ts: now,
  };
}
