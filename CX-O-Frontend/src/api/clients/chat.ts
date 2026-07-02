/**
 * ApiClient mixin: chat & session
 * Extracted from client.ts as part of M16 split.
 */
import { getApiBaseUrl, _ApiClientBase } from './_common';
import type { ChatMessage, Session } from './_types';

export class _ChatClientMixin extends _ApiClientBase {
  async sendMessage(message: string, agentId: string = 'default', sessionId?: string): Promise<{ response: string; session_id: string }> {
    const response = await this.request<{ status: string; response: string; session_id: string }>({
      url: '/api/chat',
      method: 'post',
      data: { message, agent_id: agentId, session_id: sessionId }
    });
    return { response: response.response, session_id: response.session_id };
  }

  async getChatHistory(agentId: string = 'default'): Promise<{ messages: ChatMessage[] }> {
    const sessionId = `agent-${agentId}`;
    const response = await this.request<{ status: string; messages: ChatMessage[] }>({ url: `/api/chat/history/${sessionId}` });
    return { messages: response.messages || [] };
  }

  async createSession(title: string, agentId: string = 'default'): Promise<Session> {
    return this.request<Session>({ url: '/api/context/sessions', method: 'post', data: { title, agent_id: agentId } });
  }

  async getSessions(): Promise<Session[]> {
    const response = await this.request<{ status: string; sessions: Session[]; total: number }>({ url: '/api/context/sessions' });
    return response.sessions || [];
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request({ url: `/api/context/sessions/${sessionId}`, method: 'delete' });
  }

  async sendMessageStream(
    message: string,
    onChunk: (chunk: Record<string, unknown>) => void,
    agentId: string = 'default',
    images?: string[]
  ): Promise<void> {
    const baseUrl = getApiBaseUrl();
    const token = localStorage.getItem('cxhms-token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json', Accept: 'text/event-stream' };
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(`${baseUrl}/api/chat/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ message, agent_id: agentId, images }),
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
        const chunk = JSON.parse(dataPayload) as Record<string, unknown>;
        onChunk(chunk);
      } catch {
        // 忽略单行解析错误
      }
    };

    while (!streamDone) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // 按行处理；保留最后未换行的部分到 buffer
      const parts = buffer.split('\n');
      buffer = parts.pop() ?? '';
      for (const line of parts) {
        flushLine(line);
      }
    }

    // 处理流结束时 buffer 中可能残留的最后一帧（无 \n 终止）
    if (buffer.length > 0) {
      flushLine(buffer);
    }
  }

  async sendMemoryAgentMessageStream(
    message: string,
    onChunk: (chunk: Record<string, unknown>) => void,
    sessionId?: string
  ): Promise<void> {
    const axiosInstance = this.client;

    const response = await axiosInstance.post('/api/memory-agent/chat/stream', {
      message,
      session_id: sessionId,
    }, {
      responseType: 'text',
      transformResponse: [(data: string) => data],
    });

    const lines = response.data.split('\n');
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const jsonStr = line.slice(6);
          if (jsonStr.trim()) {
            const chunk = JSON.parse(jsonStr) as Record<string, unknown>;
            onChunk(chunk);
          }
        } catch {
          /* 忽略无法解析的 SSE 数据行 */
        }
      }
    }
  }
}
