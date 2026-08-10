/**
 * 记忆代理页（SubTask 7.3）
 *
 * 功能口径对齐 CX-O-Frontend MemoryAgentPage：
 * - 记忆管理助手对话：自然语言执行记忆搜索/更新/删除/导出等操作
 * - 历史消息加载（agentsApi.getAgentContext('memory-agent')，仅取 user/assistant）
 * - 流式输出（chatApi.sendMemoryAgentMessageStream，SSE chunk 一次性接收后逐帧归约）
 * - 思考过程折叠 + 工具调用链状态徽章（复用 chatStream 纯函数归约，与对话页行为一致）
 * - 清空对话（前端状态 + agentsApi.clearAgentContext 后端上下文）
 *
 * 与对话页的差异：本页固定 memory-agent，不做 WS 通道（参考前端亦无），无 Agent 选择器。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Bot, Loader2, Send, User, Wrench, X } from 'lucide-react';
import { agentsApi } from '@/api/clients/agents';
import { chatApi } from '@/api/clients/chat';
import { cn } from '@/lib/utils';
import {
  applyStreamEvent,
  createAssistantMessage,
  createUserMessage,
  finalizeStreamMessage,
  normalizeStreamChunk,
} from './chatStream';
import type { ChatMsg } from './chatStream';

const MEMORY_AGENT_ID = 'memory-agent';

/** 消息气泡（与对话页同构：user 右 / assistant 左；thinking 折叠；工具链徽章） */
function MessageBubble(props: { msg: ChatMsg }) {
  const { t } = useTranslation();
  const { msg } = props;
  const isUser = msg.role === 'user';

  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div
        className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
          isUser ? 'bg-primary/15 text-primary' : 'bg-secondary/15 text-secondary',
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>

      <div className={cn('min-w-0 max-w-[75%] space-y-2', isUser && 'flex flex-col items-end')}>
        {msg.thinking && (
          <details className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.03)] px-3 py-2 text-xs text-muted-foreground">
            <summary className="cursor-pointer select-none font-medium">
              {t('management.memoryAgent.thinking')}
            </summary>
            <p className="mt-2 whitespace-pre-wrap break-words">{msg.thinking}</p>
          </details>
        )}

        {msg.toolCalls && msg.toolCalls.length > 0 && (
          <div className="space-y-1">
            {msg.toolCalls.map((tc) => (
              <div
                key={tc.id}
                className="flex items-center gap-2 rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.03)] px-3 py-1.5 text-xs"
              >
                <Wrench className="h-3 w-3 text-accent" />
                <span className="font-medium">{tc.name}</span>
                <span
                  className={cn(
                    'ml-auto flex items-center gap-1',
                    tc.status === 'executing' && 'text-amber-400',
                    tc.status === 'completed' && 'text-emerald-400',
                    tc.status === 'pending' && 'text-muted-foreground',
                  )}
                >
                  {tc.status === 'executing' && <Loader2 className="h-3 w-3 animate-spin" />}
                  {tc.status === 'executing'
                    ? t('management.memoryAgent.toolExecuting')
                    : t('management.memoryAgent.toolCall')}
                </span>
              </div>
            ))}
          </div>
        )}

        {(msg.content || !isUser) && (
          <div
            className={cn(
              'rounded-xl px-4 py-2.5 text-sm leading-relaxed',
              isUser
                ? 'bg-primary/85 text-primary-foreground'
                : msg.isError
                  ? 'border border-red-500/30 bg-red-500/10 text-red-400'
                  : 'border border-[var(--glass-border)] bg-[var(--glass-bg)]',
            )}
          >
            <p className="whitespace-pre-wrap break-words">{msg.content}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function MemoryAgentPage() {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [historyError, setHistoryError] = useState(false);

  const tempAssistantIdRef = useRef('');
  const listRef = useRef<HTMLDivElement>(null);

  // 历史消息加载（仅取 user/assistant 角色）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await agentsApi.getAgentContext(MEMORY_AGENT_ID);
        if (cancelled) return;
        setMessages(
          data.recent_messages
            .filter((m) => m.role === 'user' || m.role === 'assistant')
            .map((m, idx) => ({
              id: `history-${idx}`,
              role: m.role as 'user' | 'assistant',
              content: m.content,
              timestamp: m.created_at || new Date().toISOString(),
            })),
        );
      } catch (error) {
        if (cancelled) return;
        console.error('Memory-agent history load failed:', error);
        setHistoryError(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 自动滚动到底部（jsdom 无 scrollIntoView，直接写 scrollTop）
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    const userMessage = createUserMessage(`u-${Date.now()}`, text);
    const assistantId = `a-${Date.now()}`;
    tempAssistantIdRef.current = assistantId;
    setMessages((prev) => [...prev, userMessage, createAssistantMessage(assistantId)]);
    setInput('');
    setIsLoading(true);

    try {
      await chatApi.sendMemoryAgentMessageStream(text, (chunk) => {
        const event = normalizeStreamChunk(chunk);
        setMessages((prev) => applyStreamEvent(prev, assistantId, event));
        if (event.type === 'done') {
          setMessages((prev) =>
            finalizeStreamMessage(prev, assistantId, t('management.memoryAgent.doneEmpty')),
          );
        }
      });
      // 流正常结束但未收到 done 帧时同样兜底
      setMessages((prev) =>
        finalizeStreamMessage(prev, assistantId, t('management.memoryAgent.doneEmpty')),
      );
    } catch (error) {
      console.error('Memory-agent send failed:', error);
      setMessages((prev) =>
        applyStreamEvent(prev, assistantId, {
          type: 'error',
          error: t('management.memoryAgent.sendFailed'),
        }),
      );
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, t]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  // 清空对话：前端状态 + 后端 agent 上下文
  const clearChat = async () => {
    setMessages([]);
    try {
      await agentsApi.clearAgentContext(MEMORY_AGENT_ID);
    } catch (error) {
      console.error('Memory-agent context clear failed:', error);
    }
  };

  const EXAMPLES = [
    t('management.memoryAgent.exSearch'),
    t('management.memoryAgent.exDelete'),
    t('management.memoryAgent.exExport'),
    t('management.memoryAgent.exStats'),
    t('management.memoryAgent.exClean'),
  ];

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-4">
      {/* 头部 */}
      <div className="flex shrink-0 items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">{t('management.memoryAgent.subtitle')}</p>
        <button
          type="button"
          onClick={() => void clearChat()}
          aria-label={t('management.memoryAgent.clear')}
          className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--glass-border)] px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-[rgba(255,255,255,0.06)]"
        >
          <X className="h-3.5 w-3.5" />
          {t('management.memoryAgent.clear')}
        </button>
      </div>

      {historyError && (
        <p className="shrink-0 text-xs text-red-400">{t('management.memoryAgent.historyFailed')}</p>
      )}

      {/* 消息区 */}
      <div ref={listRef} className="glass-panel min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-secondary/15 text-secondary">
              <Bot className="h-7 w-7" />
            </div>
            <div>
              <h3 className="text-lg font-semibold">{t('management.memoryAgent.emptyTitle')}</h3>
              <p className="mt-1 max-w-md text-sm text-muted-foreground">
                {t('management.memoryAgent.emptyDesc')}
              </p>
            </div>
            <div className="max-w-md rounded-xl border border-[var(--glass-border)] bg-[rgba(255,255,255,0.03)] p-4 text-left text-sm text-muted-foreground">
              <p className="mb-2 font-medium">{t('management.memoryAgent.examplesTitle')}</p>
              <ul className="space-y-1">
                {EXAMPLES.map((ex) => (
                  <li key={ex}>• {ex}</li>
                ))}
              </ul>
            </div>
          </div>
        ) : (
          messages.map((msg) => <MessageBubble key={msg.id} msg={msg} />)
        )}
      </div>

      {/* 输入区 */}
      <div className="flex shrink-0 items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={2}
          aria-label={t('management.memoryAgent.inputPlaceholder')}
          placeholder={t('management.memoryAgent.inputPlaceholder')}
          className="min-w-0 flex-1 resize-none rounded-xl border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-4 py-2.5 text-sm focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
        />
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={!input.trim() || isLoading}
          aria-label={t('management.memoryAgent.send')}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/85 text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {isLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  );
}
