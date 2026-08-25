/**
 * 会议状态 → 桌宠窗视觉提示 的跨窗传递通道。
 *
 * 不同 Electron 桌宠窗（及管理窗）共享同一 origin（dev http / 生产 file://），
 * localStorage 跨窗共享、`storage` 事件可在其他窗口触发。会议室视图据此把
 * 当前发言者广播给各桌宠窗；桌宠窗监听本键，当 speaker === 自身 agentId 时
 * 显示说话高亮，否则清除。
 */
export const MEETING_HINT_KEY = 'cxo-meeting-hint';

export interface MeetingHintPayload {
  speaker: string | null;
  roomId: string | null;
}

/** 写入最新会议发言提示（由会议室视图 / useMeetingSubscription 调用）。 */
export function setMeetingHint(payload: MeetingHintPayload): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(MEETING_HINT_KEY, JSON.stringify(payload));
  } catch {
    // 持久化异常时静默忽略（仅影响视觉提示，不阻断会议主流程）
  }
}

/** 读取当前会议发言提示（上一次写入，无则返回 null）。 */
export function getMeetingHint(): MeetingHintPayload | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(MEETING_HINT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as MeetingHintPayload;
    return { speaker: parsed.speaker ?? null, roomId: parsed.roomId ?? null };
  } catch {
    return null;
  }
}