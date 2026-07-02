/**
 * H4 拆分：ChatPage 共享类型定义。
 *
 * 从 ChatPage.tsx 提取，供 ChatPage 及其子组件共享。
 */

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  memory_refs?: number[];
  tool_calls?: ToolCall[];
  thinking?: string;
  images?: string[];
  type?: string;
  eventData?: Record<string, unknown>;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments?: unknown;
  result?: unknown;
  status?: 'pending' | 'executing' | 'completed' | 'failed';
}

export interface StreamToolCall {
  id?: string;
  name?: string;
  arguments?: unknown;
  function?: {
    name?: string;
    arguments?: unknown;
  };
}
