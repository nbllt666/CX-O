/**
 * chat 域客户端：会话与消息。
 * 端点面对齐 CX-O-Frontend clients/chat.ts（含 SSE 流式聊天）。
 */
import { getApiBaseUrl, getHttpClient, normalizeError, request, STORAGE_KEYS } from '../base';
import type { ChatMessage, Session } from '../types';

export type StreamChunk = Record<string, unknown>;

export const chatApi = {
  async sendMessage(
    message: string,
    agentId = 'default',
    sessionId?: string,
  ): Promise<{ response: string; session_id: string }> {
    const response = await request<{ status: string; response: string; session_id: string }>({
      url: '/api/chat',
      method: 'post',
      data: { message, agent_id: agentId, session_id: sessionId },
    });
    return { response: response.response, session_id: response.session_id };
  },

  async getChatHistory(agentId = 'default'): Promise<{ messages: ChatMessage[] }> {
    const sessionId = `agent-${agentId}`;
    const response = await request<{ status: string; messages: ChatMessage[] }>({
      url: `/api/chat/history/${sessionId}`,
    });
    return { messages: response.messages || [] };
  },

  createSession(title: string, agentId = 'default'): Promise<Session> {
    return request<Session>({
      url: '/api/context/sessions',
      method: 'post',
      data: { title, agent_id: agentId },
    });
  },

  async getSessions(): Promise<Session[]> {
    const response = await request<{ status: string; sessions: Session[]; total: number }>({
      url: '/api/context/sessions',
    });
    return response.sessions || [];
  },

  async deleteSession(sessionId: string): Promise<void> {
    await request({ url: `/api/context/sessions/${sessionId}`, method: 'delete' });
  },

  /**
   * SSE 流式聊天：fetch + ReadableStream 逐行解析 `data:` 帧。
   * 带图片消息走此端点（WS chat_stream 不支持 images）。
   * 支持传入 AbortSignal 以外部中断流式请求（C3 修复）。
   */
  async sendMessageStream(
    message: string,
    onChunk: (chunk: StreamChunk) => void,
    agentId = 'default',
    images?: string[],
    signal?: AbortSignal,
  ): Promise<void> {
    const baseUrl = getApiBaseUrl();
    const token = localStorage.getItem(STORAGE_KEYS.token);
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    };
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(`${baseUrl}/api/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ message, agent_id: agentId, images }),
      // C3 修复：透传 AbortSignal，reader.read() 在中止时会抛 AbortError
      signal,
    });

    if (!response.ok || !response.body) {
      const errorText = await response.text().catch(() => '');
      throw new Error(`请求失败: ${response.status} ${response.statusText} ${errorText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let streamDone = false;

    const flushLine = (rawLine: string) => {
      if (!rawLine) return;
      const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
      if (!line.startsWith('data:')) return;
      const dataPayload = line.startsWith('data: ') ? line.slice(6) : line.slice(5);
      if (!dataPayload) return;
      if (dataPayload.trim() === '[DONE]') {
        streamDone = true;
        return;
      }
      try {
        onChunk(JSON.parse(dataPayload) as StreamChunk);
      } catch {
        // 忽略单行解析错误
      }
    };

    while (!streamDone) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n');
      buffer = parts.pop() ?? '';
      for (const line of parts) {
        flushLine(line);
      }
    }
    // 流结束时处理 buffer 中可能残留的最后一帧（无 \n 终止）
    if (buffer.length > 0) {
      flushLine(buffer);
    }
  },

  /** memory-agent 流式聊天（axios responseType:text 一次性接收后逐行解析）；支持 AbortSignal（C3 修复） */
  async sendMemoryAgentMessageStream(
    message: string,
    onChunk: (chunk: StreamChunk) => void,
    sessionId?: string,
    signal?: AbortSignal,
  ): Promise<void> {
    try {
      const response = await getHttpClient().post(
        '/api/memory-agent/chat/stream',
        { message, session_id: sessionId },
        { responseType: 'text', transformResponse: [(data: string) => data], signal },
      );
      const lines = String(response.data).split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const jsonStr = line.slice(6);
            if (jsonStr.trim()) {
              onChunk(JSON.parse(jsonStr) as StreamChunk);
            }
          } catch {
            /* 忽略无法解析的 SSE 数据行 */
          }
        }
      }
    } catch (error) {
      throw normalizeError(error);
    }
  },
};
