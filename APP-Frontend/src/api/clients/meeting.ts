/**
 * meeting 域客户端：多 Agent 语音会议协调器 REST。
 * 请求体 / 响应字段对齐 CX-O-SERVER/server/core/meeting/models.py 与
 * server/api/routers/meeting.py（StartRequest / AgentIdRequest / SpeakRequest / room.to_dict()）。
 *
 * 端点：
 *   POST /api/meeting/start
 *   POST /api/meeting/{room_id}/end
 *   GET  /api/meeting/{room_id}/state
 *   POST /api/meeting/{room_id}/join
 *   POST /api/meeting/{room_id}/leave
 *   POST /api/meeting/{room_id}/speak
 *
 * 响应统一为 APIResponse 封装：{ success, data, message, error, timestamp, request_id }。
 */
import { request } from '../base';

/** 参会 Agent 描述（StartRequest.agents 与 join 请求体共用，见 AgentIdRequest） */
export interface MeetingAgentSpec {
  agent_id: string;
  name?: string;
  persona?: string;
  relevance?: number;
  desire_to_speak?: number;
  voice?: string | null;
}

/** 消息流单条（room.to_dict().recent_messages，最近 20 条） */
export interface MeetingRecentMessage {
  role: 'user' | 'agent' | 'audience';
  speaker: string;
  text: string;
  ts?: string | number;
}

/** 房间状态快照（room.to_dict()） */
export interface MeetingRoomSnapshot {
  room_id: string;
  user: string;
  state: 'idle' | 'in_meeting' | 'paused';
  max_agents: number;
  agents: MeetingAgentSpec[];
  token_holder: string | null;
  transcript_turns: number;
  /** 观众席是否开启（弹幕通道是否在采集） */
  audience_enabled: boolean;
  /** 最近消息流（user/agent/audience 三态，供互动空间渲染） */
  recent_messages: MeetingRecentMessage[];
}

/** speak 请求可选字段（SpeakRequest：role / userid / username / mention） */
export interface MeetingSpeakOptions {
  role?: 'user' | 'audience';
  userid?: string;
  username?: string;
  /** 点名目标 agent_id（@agent 快捷点名时填写） */
  mention?: string;
}

/** 发言权裁决（decision.to_dict()） */
export interface MeetingDecision {
  mode: string;
  speaker: string | null;
  participants: string[];
  intent: string | null;
  reason: string;
}

/** 单轮发言（_drive_turn 结果形状） */
export interface MeetingTurn {
  speaker: string;
  text: string;
  audio_allowed: boolean;
  voice?: string | null;
}

/** speak 响应 data（process_user_speech 返回值） */
export interface MeetingSpeakResult {
  decision: MeetingDecision;
  turns: MeetingTurn[];
  transcript_turns: number;
}

/** 通用 APIResponse 泛型封装 */
interface ApiResponse<T> {
  success: boolean;
  data?: T | null;
  message?: string | null;
  error?: string | null;
  timestamp?: string;
  request_id?: string | null;
}

function dataOf<T>(res: ApiResponse<T>): T {
  // M4：失败响应显式抛出携带真实原因的异常，让上游 catch 拿到 error/message
  // 而非 undefined 静默传播（res.data as T 会把 null/undefined 当成功值返回）。
  if (!res?.success || res.data == null) {
    throw new Error(res?.error || res?.message || '会议请求失败');
  }
  return res.data;
}

export const meetingApi = {
  /** 开启会议：data=房间状态快照（含 room_id / agents / state / audience_enabled） */
  async start(opts: {
    user: string;
    agents?: MeetingAgentSpec[];
    room_id?: string;
    max_agents?: number;
    audience_enabled?: boolean;
  }): Promise<MeetingRoomSnapshot> {
    const res = await request<ApiResponse<MeetingRoomSnapshot>>({
      url: '/api/meeting/start',
      method: 'post',
      data: {
        user: opts.user,
        agents: opts.agents ?? [],
        room_id: opts.room_id,
        max_agents: opts.max_agents,
        audience_enabled: opts.audience_enabled,
      },
    });
    return dataOf(res);
  },

  /** 结束会议：data={ summary } */
  async end(roomId: string): Promise<{ summary: string }> {
    const res = await request<ApiResponse<{ summary: string }>>({
      url: `/api/meeting/${encodeURIComponent(roomId)}/end`,
      method: 'post',
    });
    return dataOf(res);
  },

  /** 查询房间状态快照（轮询兜底即此端点） */
  async getState(roomId: string): Promise<MeetingRoomSnapshot> {
    const res = await request<ApiResponse<MeetingRoomSnapshot>>({
      url: `/api/meeting/${encodeURIComponent(roomId)}/state`,
      method: 'get',
    });
    return dataOf(res);
  },

  /** 向会议并入一个 Agent：data=房间状态快照 */
  async join(roomId: string, spec: MeetingAgentSpec): Promise<MeetingRoomSnapshot> {
    const res = await request<ApiResponse<MeetingRoomSnapshot>>({
      url: `/api/meeting/${encodeURIComponent(roomId)}/join`,
      method: 'post',
      data: { agent_id: spec.agent_id, name: spec.name ?? '', persona: spec.persona ?? '' },
    });
    return dataOf(res);
  },

  /** 移除 Agent：data=房间状态快照 */
  async leave(roomId: string, agentId: string): Promise<MeetingRoomSnapshot> {
    const res = await request<ApiResponse<MeetingRoomSnapshot>>({
      url: `/api/meeting/${encodeURIComponent(roomId)}/leave`,
      method: 'post',
      data: { agent_id: agentId },
    });
    return dataOf(res);
  },

  /** 开/关观众席（同时启停弹幕连接器）：data=房间状态快照 */
  async toggleAudience(roomId: string, enabled: boolean): Promise<MeetingRoomSnapshot> {
    const res = await request<ApiResponse<MeetingRoomSnapshot>>({
      url: `/api/meeting/${encodeURIComponent(roomId)}/audience/toggle`,
      method: 'post',
      data: { enabled },
    });
    return dataOf(res);
  },

  /** 用户发言，触发发言权仲裁：data={ decision, turns, transcript_turns } */
  async speak(roomId: string, text: string, opts?: MeetingSpeakOptions): Promise<MeetingSpeakResult> {
    const res = await request<ApiResponse<MeetingSpeakResult>>({
      url: `/api/meeting/${encodeURIComponent(roomId)}/speak`,
      method: 'post',
      data: {
        text,
        role: opts?.role ?? 'user',
        userid: opts?.userid,
        username: opts?.username,
        mention: opts?.mention,
      },
    });
    return dataOf(res);
  },
};