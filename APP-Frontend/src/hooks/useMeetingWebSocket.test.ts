/**
 * parseMeetingStateEvent 纯函数单测（T5：广播事件解析归一化）。
 * 仅验证归一化逻辑本身，不涉及 WS/轮询 IO。
 */
import { describe, it, expect } from 'vitest';
import { parseMeetingStateEvent } from './useMeetingWebSocket';

describe('parseMeetingStateEvent', () => {
  it('归一化合法 meeting_state 广播载荷（含 audience/recent_messages 三态）', () => {
    const snap = parseMeetingStateEvent({
      room_id: 'room-1',
      data: {
        room_id: 'room-1',
        user: 'u',
        state: 'in_meeting',
        max_agents: 3,
        agents: [{ agent_id: 'a1', name: 'A' }],
        token_holder: 'a1',
        transcript_turns: 2,
        audience_enabled: true,
        recent_messages: [
          { role: 'user', speaker: 'u', text: 'hi', ts: 1 },
          { role: 'audience', speaker: '观众甲', text: '弹幕', ts: 2 },
          { role: 'agent', speaker: 'A', text: 'hello', ts: 3 },
        ],
      },
    });
    expect(snap).not.toBeNull();
    expect(snap!.room_id).toBe('room-1');
    expect(snap!.state).toBe('in_meeting');
    expect(snap!.audience_enabled).toBe(true);
    expect(snap!.token_holder).toBe('a1');
    expect(snap!.recent_messages).toHaveLength(3);
    expect(snap!.agents).toHaveLength(1);
  });

  it('非法/缺 room_id 载荷返回 null', () => {
    expect(parseMeetingStateEvent(null)).toBeNull();
    expect(parseMeetingStateEvent('str')).toBeNull();
    expect(parseMeetingStateEvent(42)).toBeNull();
    expect(parseMeetingStateEvent({ data: {} })).toBeNull();
    expect(parseMeetingStateEvent({ data: { room_id: '' } })).toBeNull();
  });

  it('缺省字段补默认、非法 state 回退 idle', () => {
    const snap = parseMeetingStateEvent({ data: { room_id: 'r', state: 'weird' } });
    expect(snap?.state).toBe('idle');
    expect(snap?.audience_enabled).toBe(false);
    expect(snap?.recent_messages).toEqual([]);
    expect(snap?.max_agents).toBe(0);
    expect(snap?.token_holder).toBeNull();
  });
});