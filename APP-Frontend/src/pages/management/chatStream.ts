/**
 * 对话页流式消息归约（SubTask 6.3 纯逻辑层）
 *
 * WS onMessage 与 HTTP SSE onChunk 两条链路共用同一套事件归约，
 * 保证「WS 优先、SSE 兜底」下消息列表行为一致。本模块为纯函数，
 * 不依赖 React / i18n / 网络，文案兜底由页面层注入。
 */

export interface ToolCallItem {
  id: string;
  name: string;
  status: 'pending' | 'executing' | 'completed' | 'failed';
  /** 工具调用参数（来自 tool_call 事件，供参数摘要折叠展示） */
  arguments?: unknown;
  /** 工具调用结果（来自 tool_result 事件，供结果折叠展示） */
  result?: unknown;
}

export interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  /** 思考过程（type=thinking 事件累积） */
  thinking?: string;
  /** 工具调用链（tool_call / tool_start / tool_result 事件驱动状态机） */
  toolCalls?: ToolCallItem[];
  /** 错误消息标记（渲染为错误态气泡） */
  isError?: boolean;
}

/** 归一化后的流式事件最小面（WS 消息与 SSE chunk 均可映射到此结构） */
export interface StreamEvent {
  type: string;
  content?: string;
  tool_call?: {
    id?: string;
    name?: string;
    arguments?: unknown;
    function?: { name?: string; arguments?: unknown };
  };
  tool_name?: string;
  result?: unknown;
  error?: string;
}

export function createUserMessage(id: string, content: string): ChatMsg {
  return { id, role: 'user', content, timestamp: new Date().toISOString() };
}

export function createAssistantMessage(id: string): ChatMsg {
  return { id, role: 'assistant', content: '', timestamp: new Date().toISOString() };
}

function replaceMessage(messages: ChatMsg[], index: number, next: ChatMsg): ChatMsg[] {
  const updated = [...messages];
  updated[index] = next;
  return updated;
}

/**
 * 将一条流式事件归约到消息列表（不可变更新）。
 * 按 assistantId 更新目标消息，允许梦境等独立消息插入在它之后。
 * 目标不存在或不是 assistant 时原样返回；未变更消息保持引用，供 UI memo 复用。
 *
 * 事件口径：
 * - content     → 追加正文
 * - thinking    → 追加思考过程
 * - tool_call   → 追加一条 pending 工具调用
 * - tool_start  → 同名工具调用置 executing
 * - tool_result → 同名工具调用置 completed
 * - error       → 标记 isError 并以 error 文本覆盖正文（文案由页面层组合）
 * - done / cancelled / 其余 → 不动消息体（页面层负责收尾状态）
 */
export function applyStreamEvent(
  messages: ChatMsg[],
  assistantId: string,
  event: StreamEvent,
): ChatMsg[] {
  const index = messages.findIndex((message) => message.id === assistantId && message.role === 'assistant');
  const last = messages[index];
  if (!last) return messages;

  switch (event.type) {
    case 'content': {
      if (!event.content) return messages;
      return replaceMessage(messages, index, { ...last, content: last.content + event.content });
    }
    case 'thinking': {
      if (!event.content) return messages;
      return replaceMessage(messages, index, {
        ...last,
        thinking: (last.thinking ?? '') + event.content,
      });
    }
    case 'tool_call': {
      const tc = event.tool_call;
      if (!tc) return messages;
      const item: ToolCallItem = {
        id: tc.id || `tc-${assistantId}-${last.toolCalls?.length ?? 0}`,
        name: tc.name || tc.function?.name || 'unknown',
        status: 'pending',
        arguments: tc.arguments ?? tc.function?.arguments,
      };
      return replaceMessage(messages, index, {
        ...last,
        toolCalls: [...(last.toolCalls ?? []), item],
      });
    }
    case 'tool_start': {
      if (!event.tool_name || !last.toolCalls) return messages;
      return replaceMessage(messages, index, {
        ...last,
        toolCalls: last.toolCalls.map((t) =>
          t.name === event.tool_name && t.status === 'pending'
            ? { ...t, status: 'executing' as const }
            : t,
        ),
      });
    }
    case 'tool_result': {
      if (!event.tool_name || !last.toolCalls) return messages;
      return replaceMessage(messages, index, {
        ...last,
        toolCalls: last.toolCalls.map((t) =>
          t.name === event.tool_name
            ? { ...t, status: 'completed' as const, result: event.result }
            : t,
        ),
      });
    }
    case 'error': {
      return replaceMessage(messages, index, {
        ...last,
        isError: true,
        content: event.error ?? '',
      });
    }
    default:
      return messages;
  }
}

/**
 * 收尾兜底：done / cancelled 时若正文仍为空，以页面层注入的兜底文案填充。
 * fallback 为空串时不做替换。
 */
export function finalizeStreamMessage(
  messages: ChatMsg[],
  assistantId: string,
  fallback: string,
): ChatMsg[] {
  const index = messages.findIndex((message) => message.id === assistantId && message.role === 'assistant');
  const last = messages[index];
  if (!last || last.isError || last.content || !fallback) return messages;
  return replaceMessage(messages, index, { ...last, content: fallback });
}

/** SSE chunk（Record<string, unknown>）→ StreamEvent 归一化 */
export function normalizeStreamChunk(chunk: Record<string, unknown>): StreamEvent {
  const toolCall = chunk.tool_call as StreamEvent['tool_call'] | undefined;
  const type = typeof chunk.type === 'string' ? chunk.type : '';
  const errorDetail = chunk.error && typeof chunk.error === 'object'
    ? (chunk.error as { message?: unknown }).message
    : chunk.error;
  // HTTP SSE 使用 message，底层模型流使用 content；保留既有 error 字段优先级。
  const errorCandidates = type === 'error'
    ? [errorDetail, chunk.message, chunk.content]
    : [errorDetail];
  const error = errorCandidates.find((value): value is string => typeof value === 'string' && value.length > 0);
  return {
    type,
    content: typeof chunk.content === 'string' ? chunk.content : undefined,
    tool_call: toolCall,
    tool_name: typeof chunk.tool_name === 'string' ? chunk.tool_name : undefined,
    result: chunk.result,
    error: error ?? (chunk.error ? String(chunk.error) : undefined),
  };
}
