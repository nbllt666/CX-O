/**
 * 会议状态订阅钩子（useMeetingWebSocket）。
 *
 * 订阅机制：「WS 事件优先 + 轮询兜底」。
 *  - WS 优先：经管理窗常驻 /ws 连接（useConfigReload → meetingEvents 事件总线）接收后端
 *    广播 `{type:"meeting_state", room_id, data}`，收到即解析归一化并刷新快照 +
 *    写 setMeetingHint（桌宠说话高亮）。
 *  - 轮询兜底：WS 不可用/未收到事件时，按 intervalMs 周期 GET /api/meeting/{room_id}/state
 *    兜底拉取，保证状态不丢失（与既有逻辑一致）。
 *  - start / end / join / leave / speak / toggleAudience 为 REST 动作，成功后触发一次立即刷新。
 *
 * 请求/响应字段以 CX-O-SERVER/server/core/meeting/models.py 与
 * server/api/routers/meeting.py 为准，见 src/api/clients/meeting.ts。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { meetingApi } from '../api/clients/meeting';
import type {
  MeetingAgentSpec,
  MeetingRoomSnapshot,
  MeetingSpeakOptions,
  MeetingRecentMessage,
  MeetingSpeakResult,
} from '../api/clients/meeting';
import { setMeetingHint } from '../lib/meetingHint';
import { subscribeMeetingState } from '../lib/meetingEvents';

const DEFAULT_INTERVAL_MS = 2000;

/**
 * 纯函数：把后端 `meeting_state` 广播载荷归一化为 MeetingRoomSnapshot。
 * 入参可为整个广播（{room_id, data}）或直接房间 dict；非法/缺 room_id 返回 null。
 */
export function parseMeetingStateEvent(payload: unknown): MeetingRoomSnapshot | null {
  if (typeof payload !== 'object' || payload === null) return null;
  const raw = payload as { data?: unknown };
  const room = (raw.data && typeof raw.data === 'object' ? raw.data : payload) as Record<string, unknown>;
  if (!room || typeof room.room_id !== 'string' || !room.room_id) return null;

  const state = room.state;
  const agents = Array.isArray(room.agents) ? (room.agents as MeetingAgentSpec[]) : [];
  const recent = Array.isArray(room.recent_messages)
    ? (room.recent_messages as MeetingRecentMessage[])
    : [];

  return {
    room_id: String(room.room_id),
    user: typeof room.user === 'string' ? room.user : 'user',
    state: state === 'idle' || state === 'in_meeting' || state === 'paused' ? state : 'idle',
    max_agents: typeof room.max_agents === 'number' ? room.max_agents : 0,
    agents,
    token_holder: typeof room.token_holder === 'string' ? room.token_holder : null,
    transcript_turns: typeof room.transcript_turns === 'number' ? room.transcript_turns : 0,
    audience_enabled: !!room.audience_enabled,
    recent_messages: recent,
  };
}

export interface UseMeetingWebSocketOptions {
  /** 会议房间号；为空时不轮询（尚未建会） */
  roomId: string | null;
  /** 轮询间隔（毫秒，默认 2000） */
  intervalMs?: number;
  /** 每次状态刷新回调（可空；用于会议室视图展示） */
  onChange?: (snapshot: MeetingRoomSnapshot) => void;
}

export interface UseMeetingWebSocketReturn {
  snapshot: MeetingRoomSnapshot | null;
  isPolling: boolean;
  isError: boolean;
  /** 开启会议（可带 audience_enabled 决定建会即开观众席） */
  start: (opts: {
    user: string;
    agents?: MeetingAgentSpec[];
    room_id?: string;
    max_agents?: number;
    audience_enabled?: boolean;
  }) => Promise<MeetingRoomSnapshot | null>;
  /** 结束会议 */
  end: () => Promise<boolean>;
  /** 并入 Agent */
  join: (spec: MeetingAgentSpec) => Promise<MeetingRoomSnapshot | null>;
  /** 移除 Agent */
  leave: (agentId: string) => Promise<MeetingRoomSnapshot | null>;
  /** 用户发言（触发仲裁；可带 role/mention 等选项） */
  speak: (text: string, opts?: MeetingSpeakOptions) => Promise<MeetingSpeakResult | null>;
  /** 开/关观众席 */
  toggleAudience: (enabled: boolean) => Promise<MeetingRoomSnapshot | null>;
  /** 立即刷新一次 */
  refresh: () => Promise<MeetingRoomSnapshot | null>;
}

export function useMeetingWebSocket(options: UseMeetingWebSocketOptions): UseMeetingWebSocketReturn {
  const { roomId, intervalMs = DEFAULT_INTERVAL_MS, onChange } = options;
  const [snapshot, setSnapshot] = useState<MeetingRoomSnapshot | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [isError, setIsError] = useState(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const roomIdRef = useRef(roomId);
  roomIdRef.current = roomId;
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchState = useCallback(async (): Promise<MeetingRoomSnapshot | null> => {
    const id = roomIdRef.current;
    if (!id) return null;
    try {
      const s = await meetingApi.getState(id);
      setSnapshot(s);
      setIsError(false);
      // 跨窗广播当前发言者 → 桌宠说话高亮
      setMeetingHint({ speaker: s.token_holder ?? null, roomId: id });
      onChangeRef.current?.(s);
      return s;
    } catch {
      setIsError(true);
      return null;
    }
  }, []);

  // 启动/停止轮询：roomId 有值时定时拉取，无值时清除
  useEffect(() => {
    if (!roomId) {
      setSnapshot(null);
      setIsPolling(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    void fetchState();
    setIsPolling(true);
    timerRef.current = setInterval(() => void fetchState(), intervalMs);
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [roomId, intervalMs, fetchState]);

  // WS 事件优先订阅：后端经 /ws 广播 meeting_state（管理窗常驻连接 → meetingEvents 总线）。
  // 仅接受当前活动房间的事件；无活动房间时忽略（与轮询空置口径一致）。
  useEffect(() => {
    const unsubscribe = subscribeMeetingState((evt) => {
      const snap = parseMeetingStateEvent(evt);
      if (!snap) return;
      const id = roomIdRef.current;
      if (!id || id !== snap.room_id) return;
      setSnapshot(snap);
      setIsError(false);
      setMeetingHint({ speaker: snap.token_holder ?? null, roomId: snap.room_id });
      onChangeRef.current?.(snap);
    });
    return unsubscribe;
  }, []);

  const start = useCallback(
    async (opts: {
      user: string;
      agents?: MeetingAgentSpec[];
      room_id?: string;
      max_agents?: number;
      audience_enabled?: boolean;
    }): Promise<MeetingRoomSnapshot | null> => {
      try {
        const s = await meetingApi.start(opts);
        setSnapshot(s);
        setIsError(false);
        setMeetingHint({ speaker: s.token_holder ?? null, roomId: s.room_id });
        onChangeRef.current?.(s);
        return s;
      } catch {
        setIsError(true);
        return null;
      }
    },
    [],
  );

  const end = useCallback(async (): Promise<boolean> => {
    const id = roomIdRef.current;
    if (!id) return false;
    try {
      await meetingApi.end(id);
      setMeetingHint({ speaker: null, roomId: null });
      return true;
    } catch {
      setIsError(true);
      return false;
    }
  }, []);

  const join = useCallback(
    async (spec: MeetingAgentSpec): Promise<MeetingRoomSnapshot | null> => {
      const id = roomIdRef.current;
      if (!id) return null;
      try {
        const s = await meetingApi.join(id, spec);
        setSnapshot(s);
        setMeetingHint({ speaker: s.token_holder ?? null, roomId: id });
        onChangeRef.current?.(s);
        return s;
      } catch {
        setIsError(true);
        return null;
      }
    },
    [],
  );

  const leave = useCallback(
    async (agentId: string): Promise<MeetingRoomSnapshot | null> => {
      const id = roomIdRef.current;
      if (!id) return null;
      try {
        const s = await meetingApi.leave(id, agentId);
        setSnapshot(s);
        setMeetingHint({ speaker: s.token_holder ?? null, roomId: id });
        onChangeRef.current?.(s);
        return s;
      } catch {
        setIsError(true);
        return null;
      }
    },
    [],
  );

  const speak = useCallback(
    async (text: string, opts?: MeetingSpeakOptions): Promise<MeetingSpeakResult | null> => {
      const id = roomIdRef.current;
      if (!id) return null;
      try {
        const result = await meetingApi.speak(id, text, opts);
        void fetchState();
        return result;
      } catch {
        setIsError(true);
        return null;
      }
    },
    [fetchState],
  );

  const toggleAudience = useCallback(
    async (enabled: boolean): Promise<MeetingRoomSnapshot | null> => {
      const id = roomIdRef.current;
      if (!id) return null;
      try {
        const s = await meetingApi.toggleAudience(id, enabled);
        setSnapshot(s);
        setMeetingHint({ speaker: s.token_holder ?? null, roomId: id });
        onChangeRef.current?.(s);
        return s;
      } catch {
        setIsError(true);
        return null;
      }
    },
    [],
  );

  const refresh = useCallback(() => fetchState(), [fetchState]);

  return { snapshot, isPolling, isError, start, end, join, leave, speak, toggleAudience, refresh };
}

/** 浏览器兜底：直接拉取房间状态（供非 React 侧或一次性调用）。 */
export function fetchMeetingState(roomId: string): Promise<MeetingRoomSnapshot> {
  return meetingApi.getState(roomId);
}