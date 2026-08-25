/**
 * 会议状态订阅钩子（useMeetingWebSocket）。
 *
 * 服务端 meeting 模块未提供状态 WS 广播通道（coordinator 的 register_broadcast
 * 未接到端点/WS），故以轮询 GET /api/meeting/{room_id}/state 兜底：
 *  - 传入 roomId（可空）后按 intervalMs 周期拉取状态快照；
 *  - 每次拿到快照把当前发言者写入 localStorage（setMeetingHint），供各桌宠窗
 *    经 `storage` 事件做说话高亮（跨窗同源共享）。
 *  - start / end / join / leave / speak 为 REST 动作，调用成功后触发一次立即刷新。
 *
 * 请求/响应字段以 CX-O-SERVER/server/core/meeting/models.py 与
 * server/api/routers/meeting.py 为准，见 src/api/clients/meeting.ts。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { meetingApi } from '../api/clients/meeting';
import type { MeetingAgentSpec, MeetingRoomSnapshot, MeetingSpeakResult } from '../api/clients/meeting';
import { setMeetingHint } from '../lib/meetingHint';

const DEFAULT_INTERVAL_MS = 2000;

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
  /** 开启会议 */
  start: (opts: {
    user: string;
    agents?: MeetingAgentSpec[];
    room_id?: string;
    max_agents?: number;
  }) => Promise<MeetingRoomSnapshot | null>;
  /** 结束会议 */
  end: () => Promise<boolean>;
  /** 并入 Agent */
  join: (spec: MeetingAgentSpec) => Promise<MeetingRoomSnapshot | null>;
  /** 移除 Agent */
  leave: (agentId: string) => Promise<MeetingRoomSnapshot | null>;
  /** 用户发言（触发仲裁） */
  speak: (text: string) => Promise<MeetingSpeakResult | null>;
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

  const start = useCallback(
    async (opts: {
      user: string;
      agents?: MeetingAgentSpec[];
      room_id?: string;
      max_agents?: number;
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
    async (text: string): Promise<MeetingSpeakResult | null> => {
      const id = roomIdRef.current;
      if (!id) return null;
      try {
        const result = await meetingApi.speak(id, text);
        void fetchState();
        return result;
      } catch {
        setIsError(true);
        return null;
      }
    },
    [fetchState],
  );

  const refresh = useCallback(() => fetchState(), [fetchState]);

  return { snapshot, isPolling, isError, start, end, join, leave, speak, refresh };
}

/** 浏览器兜底：直接拉取房间状态（供非 React 侧或一次性调用）。 */
export function fetchMeetingState(roomId: string): Promise<MeetingRoomSnapshot> {
  return meetingApi.getState(roomId);
}