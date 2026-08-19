/**
 * 对话页（SubTask 6.3）
 *
 * 功能口径对齐 CX-O-Frontend ChatPage 的文本对话面：
 * - Agent 选择器（chatStore.agents / currentAgentId，过滤 memory-agent 由 store 完成）
 * - 历史消息加载（chatApi.getChatHistory，agent 切换时重新加载，带竞态取消）
 * - 消息列表：user/assistant 气泡、思考过程折叠、工具调用状态链、错误态气泡
 * - 流式输出：WS 优先（useWebSocket chat_stream），未连接时回退 HTTP SSE（/api/chat/stream），
 *   两条链路共用 chatStream.ts 的纯函数归约，行为一致
 * - 发送 / 停止（cancelGeneration）；Enter 发送、Shift+Enter 换行
 *
 * 语音/双流式/头像面板不在本页范围（归 Task 4 与桌宠侧）。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Bell, Bot, Send, Sparkles, Square, User, X } from 'lucide-react';
import { useChatStore } from '@/store/chatStore';
import { useWebSocket } from '@/hooks/useWebSocket';
import type { WebSocketMessage } from '@/hooks/useWebSocket';
import { chatApi } from '@/api/clients/chat';
import { Button } from '@/components/ui-v2/button';
import { cn } from '@/lib/utils';
import {
  applyStreamEvent,
  createAssistantMessage,
  createUserMessage,
  finalizeStreamMessage,
  normalizeStreamChunk,
} from './chatStream';
import type { ChatMsg, StreamEvent } from './chatStream';
import { MarkdownContent } from './MarkdownContent';
import { ThinkingProcess } from './ThinkingProcess';
import { SummaryModal } from './SummaryModal';

/** 消息气泡（user 右 / assistant 左；thinking 折叠；工具调用链状态徽章；assistant 正文 Markdown 渲染） */
function MessageBubble(props: { msg: ChatMsg; loading?: boolean }) {
  const { msg, loading } = props;
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
        {!isUser && (
          <ThinkingProcess thinking={msg.thinking} toolCalls={msg.toolCalls} loading={loading} />
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
            {isUser ? (
              <p className="whitespace-pre-wrap break-words">{msg.content}</p>
            ) : (
              <MarkdownContent content={msg.content} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const { t } = useTranslation();
  const {
    agents,
    currentAgentId,
    isLoadingAgents,
    fetchAgents,
    setCurrentAgentId,
  } = useChatStore();

  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [historyError, setHistoryError] = useState(false);
  const [alarms, setAlarms] = useState<{ message: string; triggeredAt: string }[]>([]);
  const [showSummaryModal, setShowSummaryModal] = useState(false);
  const [autoStartSummary, setAutoStartSummary] = useState(false);

  const tempAssistantIdRef = useRef('');
  const historyTokenRef = useRef<{ cancelled: boolean }>({ cancelled: false });
  const listRef = useRef<HTMLDivElement>(null);
  const alarmTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Agent 列表
  useEffect(() => {
    void fetchAgents();
  }, [fetchAgents]);

  // 历史消息：agent 切换时重新加载（token 取消防竞态）
  useEffect(() => {
    historyTokenRef.current.cancelled = true;
    const token = { cancelled: false };
    historyTokenRef.current = token;
    setHistoryError(false);

    if (!currentAgentId) {
      setMessages([]);
      return () => {
        token.cancelled = true;
      };
    }

    void (async () => {
      try {
        const { messages: history } = await chatApi.getChatHistory(currentAgentId);
        if (token.cancelled) return;
        setMessages(
          history.map((m) => ({
            id: m.id || `h-${Math.random().toString(36).slice(2)}`,
            role: m.role === 'assistant' ? 'assistant' : 'user',
            content: m.content,
            timestamp: m.created_at || new Date().toISOString(),
          })),
        );
      } catch (error) {
        if (token.cancelled) return;
        console.error('History load failed:', error);
        setMessages([]);
        setHistoryError(true);
      }
    })();

    return () => {
      token.cancelled = true;
    };
  }, [currentAgentId]);

  // 自动滚动到底部（jsdom 无 scrollIntoView，直接写 scrollTop）
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  /** 应用归一化事件到当前流式消息 */
  const applyEvent = useCallback((event: StreamEvent) => {
    setMessages((prev) => applyStreamEvent(prev, tempAssistantIdRef.current, event));
  }, []);

  /** 收尾：停止 loading + 空正文兜底 */
  const finalize = useCallback(
    (fallbackKey: 'management.chat.doneEmpty' | 'management.chat.cancelled') => {
      setIsLoading(false);
      setMessages((prev) =>
        finalizeStreamMessage(prev, tempAssistantIdRef.current, t(fallbackKey)),
      );
    },
    [t],
  );

  const handleWsMessage = useCallback(
    (data: WebSocketMessage) => {
      switch (data.type) {
        case 'content':
        case 'chat_chunk':
        case 'thinking':
          applyEvent({ type: data.type === 'chat_chunk' ? 'content' : data.type, content: data.content });
          break;
        case 'tool_call':
          applyEvent({ type: 'tool_call', tool_call: data.tool_call as StreamEvent['tool_call'] });
          break;
        case 'tool_start':
          applyEvent({ type: 'tool_start', tool_name: data.tool_name });
          break;
        case 'tool_result':
          applyEvent({ type: 'tool_result', tool_name: data.tool_name, result: data.result });
          break;
        case 'done':
        case 'chat_done':
          finalize('management.chat.doneEmpty');
          break;
        case 'chat_response':
          if (data.content) {
            applyEvent({ type: 'content', content: data.content });
          }
          finalize('management.chat.doneEmpty');
          break;
        case 'cancelled':
          finalize('management.chat.cancelled');
          break;
        default:
          break;
      }
    },
    [applyEvent, finalize],
  );

  const handleWsError = useCallback(
    (error: string) => {
      setIsLoading(false);
      applyEvent({
        type: 'error',
        error: t('management.chat.errorMessage', { message: error }),
      });
    },
    [applyEvent, t],
  );

  /** 后端提醒（alarm）事件：追加到右上角 toast，5s 后自动收起 */
  const handleAlarm = useCallback((message: string, triggeredAt: string) => {
    setAlarms((prev) => [...prev, { message, triggeredAt }]);
    if (alarmTimeoutRef.current) {
      clearTimeout(alarmTimeoutRef.current);
    }
    alarmTimeoutRef.current = setTimeout(() => {
      setAlarms((prev) => prev.slice(1));
      alarmTimeoutRef.current = null;
    }, 5000);
  }, []);

  const dismissAlarm = useCallback((index: number) => {
    setAlarms((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const { isConnected, sendMessage: wsSendMessage, cancelGeneration } = useWebSocket({
    agentId: currentAgentId || '',
    timeout: 60,
    onMessage: handleWsMessage,
    onError: handleWsError,
    onAlarm: handleAlarm,
  });

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading || !currentAgentId) return;

    const assistantId = `a-${Date.now()}`;
    tempAssistantIdRef.current = assistantId;
    setMessages((prev) => [
      ...prev,
      createUserMessage(`u-${Date.now()}`, text),
      createAssistantMessage(assistantId),
    ]);
    setInput('');
    setIsLoading(true);

    // WS 优先；未连接或发送失败回退 HTTP SSE 流式
    let sentViaWs = false;
    if (isConnected) {
      sentViaWs = wsSendMessage(text);
    }
    if (sentViaWs) return;

    try {
      await chatApi.sendMessageStream(
        text,
        (chunk) => {
          const event = normalizeStreamChunk(chunk);
          if (event.type === 'done') {
            setIsLoading(false);
            setMessages((prev) =>
              finalizeStreamMessage(prev, assistantId, t('management.chat.doneEmpty')),
            );
            return;
          }
          if (event.type === 'error') {
            throw new Error(event.error || 'unknown');
          }
          setMessages((prev) => applyStreamEvent(prev, assistantId, event));
        },
        currentAgentId,
      );
      // SSE 自然结束（[DONE] 不产生 chunk）：确保 loading 复位
      setIsLoading(false);
      setMessages((prev) =>
        finalizeStreamMessage(prev, assistantId, t('management.chat.doneEmpty')),
      );
    } catch (error) {
      setIsLoading(false);
      setMessages((prev) =>
        applyStreamEvent(prev, assistantId, {
          type: 'error',
          error: t('management.chat.errorMessage', {
            message: error instanceof Error ? error.message : String(error),
          }),
        }),
      );
    }
  }, [input, isLoading, currentAgentId, isConnected, wsSendMessage, t]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-4">
      {/* 提醒通知 toast（右上角固定；alarm 事件驱动） */}
      {alarms.length > 0 && (
        <div className="fixed right-4 top-4 z-50 space-y-2">
          {alarms.map((alarm, index) => (
            <div
              key={`${alarm.triggeredAt}-${index}`}
              className="flex max-w-sm items-start gap-2 rounded-lg bg-primary px-4 py-3 text-primary-foreground shadow-lg"
            >
              <Bell className="mt-0.5 h-5 w-5 shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{t('management.chat.alarmTitle')}</p>
                <p className="text-sm opacity-90">{alarm.message}</p>
              </div>
              <button
                type="button"
                onClick={() => dismissAlarm(index)}
                aria-label={t('management.chat.alarmClose')}
                className="shrink-0 rounded p-0.5 transition-opacity hover:opacity-70"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 工具行：Agent 选择 + 通道状态 */}
      <div className="flex shrink-0 items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <Bot className="h-4 w-4 text-primary" />
          {t('management.chat.agentLabel')}
        </label>
        <select
          value={currentAgentId ?? ''}
          onChange={(e) => setCurrentAgentId(e.target.value || null)}
          disabled={isLoadingAgents || agents.length === 0}
          className="rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-3 py-1.5 text-sm backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none disabled:opacity-50"
        >
          {isLoadingAgents ? (
            <option value="">{t('management.chat.agentLoading')}</option>
          ) : agents.length === 0 ? (
            <option value="">{t('management.chat.noAgent')}</option>
          ) : (
            agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name || a.id}
              </option>
            ))
          )}
        </select>

        <span
          className={cn(
            'ml-auto flex items-center gap-1.5 text-xs',
            isConnected ? 'text-emerald-400' : 'text-muted-foreground',
          )}
        >
          <span
            className={cn(
              'h-1.5 w-1.5 rounded-full',
              isConnected ? 'bg-emerald-400' : 'bg-amber-400',
            )}
          />
          {isConnected ? t('management.chat.wsOnline') : t('management.chat.wsOffline')}
        </span>

        {messages.length > 0 && (
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={<Sparkles className="h-3.5 w-3.5 text-primary" />}
              onClick={() => {
                setAutoStartSummary(true);
                setShowSummaryModal(true);
              }}
            >
              {t('management.chat.autoSummary')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Bot className="h-3.5 w-3.5 text-secondary" />}
              onClick={() => {
                setAutoStartSummary(false);
                setShowSummaryModal(true);
              }}
            >
              {t('management.chat.customSummary')}
            </Button>
          </div>
        )}
      </div>

      {historyError && (
        <div className="shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
          {t('management.chat.historyFailed')}
        </div>
      )}

      {/* 消息列表 */}
      <div
        ref={listRef}
        className="glass-panel min-h-0 flex-1 space-y-5 overflow-y-auto p-5"
      >
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            {t('management.chat.empty')}
          </div>
        ) : (
          messages.map((msg, i) => (
            <MessageBubble key={msg.id} msg={msg} loading={isLoading && i === messages.length - 1} />
          ))
        )}
      </div>

      {/* 输入区 */}
        <div className="glass-panel flex shrink-0 items-end gap-3 p-4">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t('management.chat.inputPlaceholder')}
            rows={2}
            className="min-h-[44px] flex-1 resize-none rounded-lg border border-[var(--glass-border)] bg-[rgba(255,255,255,0.06)] px-4 py-2.5 text-sm backdrop-blur-sm transition-colors focus:border-[rgba(255,183,225,0.4)] focus:outline-none"
          />
          {isLoading ? (
            <button
              type="button"
              onClick={cancelGeneration}
              title={t('management.chat.stop')}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-red-500/85 text-white transition-opacity hover:opacity-90"
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={!input.trim() || !currentAgentId}
              title={t('management.chat.send')}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/85 text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* 摘要助手弹窗 */}
        <SummaryModal
          isOpen={showSummaryModal}
          onClose={() => {
            setShowSummaryModal(false);
            setAutoStartSummary(false);
          }}
          contextText={messages.map((m) => `${m.role === 'user' ? '用户' : '助手'}: ${m.content}`).join('\n\n')}
          agentId={currentAgentId || 'default'}
          autoStart={autoStartSummary}
        />
      </div>
  );
}
