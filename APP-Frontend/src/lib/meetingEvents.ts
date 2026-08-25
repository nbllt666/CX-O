/**
 * 会议状态事件总线——模块级轻量订阅。
 *
 * 后端广播 `{type:"meeting_state", room_id, data}` 与
 * `{type:"danmaku_reply", room_id, agent_id, text, username}`（全连接广播、经 /ws 通道）。
 * 管理窗常驻的 /ws 连接（useConfigReload）收到后经 emitMeetingState / emitDanmakuReply 转发，
 * 各 UI（useMeetingWebSocket / 互动空间视图）经 subscribe* 订阅即时刷新——
 * 复用既有 /ws 客户端，无需为会议拉起独立连接，也不耦合 WS 连接生命周期。
 * 与 src/lib/configEvents.ts 相同的事件总线模式。
 */

/** meeting_state 广播载荷（data 为 room.to_dict()，可经 parseMeetingStateEvent 归一化） */
export interface MeetingStateEvent {
  room_id: string;
  data: unknown;
}

/** danmaku_reply 广播载荷（观众被点名回应） */
export interface DanmakuReplyEvent {
  room_id: string;
  agent_id: string;
  text: string;
  username: string;
}

type MeetingStateListener = (payload: MeetingStateEvent) => void;
type DanmakuReplyListener = (payload: DanmakuReplyEvent) => void;

const stateListeners = new Set<MeetingStateListener>();
const danmakuListeners = new Set<DanmakuReplyListener>();

/** 订阅 meeting_state 事件；返回取消订阅函数 */
export function subscribeMeetingState(listener: MeetingStateListener): () => void {
  stateListeners.add(listener);
  return () => {
    stateListeners.delete(listener);
  };
}

/** 订阅 danmaku_reply 事件；返回取消订阅函数 */
export function subscribeDanmakuReply(listener: DanmakuReplyListener): () => void {
  danmakuListeners.add(listener);
  return () => {
    danmakuListeners.delete(listener);
  };
}

/** 广播 meeting_state 事件到所有订阅者 */
export function emitMeetingState(payload: MeetingStateEvent): void {
  for (const listener of stateListeners) {
    try {
      listener(payload);
    } catch (e) {
      console.error('[meetingEvents] state listener error:', e);
    }
  }
}

/** 广播 danmaku_reply 事件到所有订阅者 */
export function emitDanmakuReply(payload: DanmakuReplyEvent): void {
  for (const listener of danmakuListeners) {
    try {
      listener(payload);
    } catch (e) {
      console.error('[meetingEvents] danmaku listener error:', e);
    }
  }
}